from __future__ import annotations

import os
import struct
from typing import Any, Dict, List, Optional

import redis
from redis.commands.search.field import VectorField
from redis.commands.search.index_definition import (
    IndexDefinition,
    IndexType,
)
from redis.commands.search.query import Query


class CacheEngine:
    """
    Redis Stack backed cache engine.

    Responsibilities:
        - Exact cache lookup
        - Cache persistence
        - Redis HNSW vector search
        - Redis health check
        - Cache size / clear
        - Diagnostics

    Redis structure:

        cache:entry:<sha256>

    Hash fields:

        identifier
        answer
        embedding

    Vector configuration:

        TYPE            FLOAT32
        DIM             512
        DISTANCE_METRIC COSINE
        ALGORITHM       HNSW
    """

    INDEX_NAME = "cache_idx"
    KEY_PREFIX = "cache:entry:"

    VECTOR_FIELD = "embedding"
    VECTOR_DIM = 512

    VECTOR_ALGORITHM = "HNSW"
    VECTOR_DISTANCE_METRIC = "COSINE"

    HNSW_M = 16
    HNSW_EF_CONSTRUCTION = 200

    def __init__(
        self,
        redis_url: Optional[str] = None,
        index_name: Optional[str] = None,
        key_prefix: Optional[str] = None,
    ) -> None:

        self.redis_url = (
            redis_url
            or os.getenv(
                "REDIS_URL",
                "redis://localhost:6379/0",
            )
        )

        self.index_name = (
            index_name
            or os.getenv(
                "REDIS_INDEX_NAME",
                self.INDEX_NAME,
            )
        )

        self.key_prefix = (
            key_prefix
            or os.getenv(
                "REDIS_KEY_PREFIX",
                self.KEY_PREFIX,
            )
        )

        self.client = redis.Redis.from_url(
            self.redis_url,
            decode_responses=False,
        )

        self._ensure_index()

    # ================================================================
    # Connection
    # ================================================================

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except redis.RedisError:
            return False

    # ================================================================
    # Key
    # ================================================================

    def _redis_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    # ================================================================
    # Embedding serialization
    # ================================================================

    @classmethod
    def _embedding_to_bytes(
        cls,
        embedding: List[float],
    ) -> bytes:

        if embedding is None:
            raise ValueError(
                "embedding cannot be None"
            )

        if len(embedding) != cls.VECTOR_DIM:
            raise ValueError(
                "Embedding dimension mismatch: "
                f"expected {cls.VECTOR_DIM}, "
                f"got {len(embedding)}"
            )

        return struct.pack(
            f"<{cls.VECTOR_DIM}f",
            *(
                float(value)
                for value in embedding
            ),
        )

    # ================================================================
    # Index management
    # ================================================================

    def _index_exists(self) -> bool:
        try:
            self.client.ft(
                self.index_name
            ).info()

            return True

        except Exception as exc:

            message = str(exc).lower()

            if (
                "unknown index name" in message
                or "unknown index" in message
                or "no such index" in message
            ):
                return False

            raise

    def _ensure_index(self) -> None:

        if self._index_exists():
            return

        vector_field = VectorField(
            self.VECTOR_FIELD,
            self.VECTOR_ALGORITHM,
            {
                "TYPE": "FLOAT32",
                "DIM": self.VECTOR_DIM,
                "DISTANCE_METRIC":
                    self.VECTOR_DISTANCE_METRIC,
                "M": self.HNSW_M,
                "EF_CONSTRUCTION":
                    self.HNSW_EF_CONSTRUCTION,
            },
        )

        definition = IndexDefinition(
            prefix=[
                self.key_prefix
            ],
            index_type=IndexType.HASH,
        )

        try:

            self.client.ft(
                self.index_name
            ).create_index(
                fields=[
                    vector_field
                ],
                definition=definition,
            )

        except redis.ResponseError as exc:

            message = str(exc).lower()

            if (
                "index already exists" in message
                or "index exists" in message
            ):
                return

            raise

    # ================================================================
    # Exact cache
    # ================================================================

    def get(
        self,
        key: str,
    ) -> Optional[str]:

        redis_key = self._redis_key(key)

        answer = self.client.hget(
            redis_key,
            "answer",
        )

        if answer is None:
            return None

        if isinstance(answer, bytes):
            return answer.decode(
                "utf-8"
            )

        return str(answer)

    def set(
        self,
        key: str,
        value: str,
        embedding: Optional[List[float]] = None,
    ) -> None:

        redis_key = self._redis_key(key)

        mapping: Dict[str, Any] = {
            "identifier": key,
            "answer": value,
        }

        if embedding is not None:

            mapping[
                self.VECTOR_FIELD
            ] = self._embedding_to_bytes(
                embedding
            )

        self.client.hset(
            redis_key,
            mapping=mapping,
        )

    # ================================================================
    # Semantic search
    # ================================================================

    def search(
        self,
        embedding: List[float],
    ) -> Optional[Dict[str, Any]]:
        """
        Redis HNSW KNN search.

        Redis COSINE distance:

            0.0 = identical
            1.0 = very different

        Therefore:

            similarity = 1 - distance
        """

        query_vector = (
            self._embedding_to_bytes(
                embedding
            )
        )

        query = Query(
            "*=>[KNN 1 "
            "@embedding $query_vector "
            "AS vector_distance]"
        )

        query = (
            query
            .sort_by(
                "vector_distance",
                asc=True,
            )
            .return_fields(
                "identifier",
                "answer",
                "vector_distance",
            )
            .paging(
                0,
                1,
            )
            .dialect(2)
        )

        try:

            result = self.client.ft(
                self.index_name
            ).search(
                query,
                query_params={
                    "query_vector":
                        query_vector
                },
            )

        except redis.RedisError as exc:

            raise RuntimeError(
                "Redis semantic search failed: "
                f"{exc}"
            ) from exc

        documents = getattr(
            result,
            "docs",
            None,
        )

        if not documents:
            return None

        document = documents[0]

        answer = getattr(
            document,
            "answer",
            None,
        )

        distance_raw = getattr(
            document,
            "vector_distance",
            None,
        )

        identifier = getattr(
            document,
            "identifier",
            None,
        )

        # redis-py may expose identifier as
        # bytes depending on configuration.
        if identifier is not None:
            if isinstance(identifier, bytes):
                identifier = identifier.decode(
                    "utf-8"
                )

        # Fallback to Redis document id.
        if not identifier:

            document_id = getattr(
                document,
                "id",
                None,
            )

            if isinstance(
                document_id,
                bytes,
            ):
                document_id = document_id.decode(
                    "utf-8"
                )

            if document_id:

                identifier = str(
                    document_id
                )

                if identifier.startswith(
                    self.key_prefix
                ):
                    identifier = identifier[
                        len(self.key_prefix):
                    ]

        if answer is None:
            return None

        if distance_raw is None:
            return None

        if isinstance(answer, bytes):
            answer = answer.decode(
                "utf-8"
            )

        try:

            distance = float(
                distance_raw
            )

        except (
            TypeError,
            ValueError,
        ):

            return None

        similarity = 1.0 - distance

        similarity = max(
            0.0,
            min(
                1.0,
                similarity,
            ),
        )

        return {
            "key": (
                str(identifier)
                if identifier
                else None
            ),
            "answer": str(answer),
            "similarity": similarity,
            "distance": distance,
        }

    # ================================================================
    # Utility
    # ================================================================

    def size(self) -> int:

        count = 0
        cursor = 0

        pattern = (
            f"{self.key_prefix}*"
        )

        while True:

            cursor, keys = self.client.scan(
                cursor=cursor,
                match=pattern,
                count=500,
            )

            count += len(keys)

            if cursor == 0:
                break

        return count

    def clear(self) -> None:

        cursor = 0

        pattern = (
            f"{self.key_prefix}*"
        )

        while True:

            cursor, keys = self.client.scan(
                cursor=cursor,
                match=pattern,
                count=500,
            )

            if keys:
                self.client.delete(
                    *keys
                )

            if cursor == 0:
                break

    # ================================================================
    # Diagnostics
    # ================================================================

    def info(self) -> Dict[str, Any]:

        return {
            "redis_url": self.redis_url,
            "index_name": self.index_name,
            "key_prefix": self.key_prefix,
            "vector_dim": self.VECTOR_DIM,
            "algorithm": self.VECTOR_ALGORITHM,
            "distance_metric":
                self.VECTOR_DISTANCE_METRIC,
            "size": self.size(),
            "ping": self.ping(),
        }