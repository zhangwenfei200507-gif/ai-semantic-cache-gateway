from __future__ import annotations

import hashlib
import time

from typing import Any, Dict, Optional
from urllib.parse import urlparse

import numpy as np
import redis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from app.config.settings import settings



class CacheRepository:
    """
    Redis based cache repository.

    Responsibilities:

    - exact cache storage
    - semantic vector storage
    - vector similarity search
    - metadata management


    Required:

    Redis Stack
    RediSearch + Vector Similarity Search

    """


    def __init__(self) -> None:


        self.redis = redis.from_url(

            settings.redis_url,

            decode_responses=False,

            # Railway Serverless treats TCP keepalive packets as outbound
            # activity. Let idle connections go quiet and reconnect on demand.
            socket_keepalive=False,

        )


        self.index_name = (

            settings.cache_index_name

        )


        self.key_prefix = (

            settings.cache_key_prefix

        )


        self.vector_field = (

            "embedding"

        )

        self.vector_index_ready = False
        self._ensure_index()

    @staticmethod
    def _has_workspace_scope_fields(info: dict[str, Any]) -> bool:
        """Require the fields used by the tenant-safe vector query."""
        fields: set[str] = set()
        for attribute in info.get("attributes", []) or []:
            if isinstance(attribute, (list, tuple)) and len(attribute) > 1:
                value = attribute[1]
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                fields.add(str(value))
        return {"embedding", "workspace_id", "cache_scope"}.issubset(fields)

    def _ensure_index(self) -> None:
        """Create the workspace-scoped HNSW index when Redis Stack is available."""
        try:
            info = self.redis.ft(self.index_name).info()
            if self._has_workspace_scope_fields(info):
                self.vector_index_ready = True
                return

            # Older installations may have a vector-only index. Keep it and
            # move new tenant-scoped queries to a compatible index name.
            self.index_name = f"{self.index_name}_v2"
        except Exception as exc:
            message = str(exc).lower()
            if not any(item in message for item in ("unknown index", "no such index")):
                return
        try:
            self.redis.ft(self.index_name).create_index(
                fields=[
                    TagField("workspace_id"),
                    TagField("cache_scope"),
                    VectorField(
                        self.vector_field,
                        "HNSW",
                        {
                            "TYPE": "FLOAT32",
                            "DIM": int(settings.vector_dimension),
                            "DISTANCE_METRIC": str(settings.distance_metric),
                            "M": 16,
                            "EF_CONSTRUCTION": 200,
                        },
                    ),
                ],
                definition=IndexDefinition(
                    prefix=[self.key_prefix],
                    index_type=IndexType.HASH,
                ),
            )
            self.vector_index_ready = True
        except redis.ResponseError as exc:
            if "index already exists" in str(exc).lower():
                try:
                    info = self.redis.ft(self.index_name).info()
                    self.vector_index_ready = self._has_workspace_scope_fields(info)
                except Exception:
                    self.vector_index_ready = False
        except Exception:
            # Cache remains an optional acceleration layer. Exact lookup and
            # provider execution continue when Redis Search is unavailable.
            return



    # ============================================================
    # Health
    # ============================================================


    def ping(self) -> bool:


        try:

            return bool(
                self.redis.ping()
            )


        except Exception:

            return False



    # ============================================================
    # Exact cache
    # ============================================================


    def find(
        self,
        key: str,
        workspace_id: str | None = None,
        cache_scope: str | None = None,
    ) -> Optional[str]:

        if not workspace_id:
            return None


        redis_key = (

            self.key_prefix

            +

            (f"{workspace_id}:" if workspace_id else "")

            +

            key

        )


        value = self.redis.hget(

            redis_key,

            "answer",

        )


        if value is None:

            return None

        stored_scope = self.redis.hget(redis_key, "cache_scope")
        if cache_scope:
            if isinstance(stored_scope, bytes):
                stored_scope = stored_scope.decode("utf-8")
            if str(stored_scope or "") != str(cache_scope):
                return None



        if isinstance(
            value,
            bytes,
        ):

            return value.decode(
                "utf-8"
            )


        return str(value)



    # ============================================================
    # Save cache
    # ============================================================


    def save(
        self,
        key: str,
        answer: str,
        embedding: list[float] | None,
        ttl_seconds: int | None = None,
        question: str | None = None,
        workspace_id: str | None = None,
        cache_scope: str | None = None,
    ) -> None:


        redis_key = (

            self.key_prefix

            +

            (f"{workspace_id}:" if workspace_id else "")

            +

            key

        )


        mapping = {


            "key":

                key,

            "workspace_id":

                str(workspace_id or "system"),

            "cache_scope":
                str(cache_scope or "legacy"),


            "answer":

                answer,

            "created_at":

                str(int(time.time())),

            "hit_count":

                "0",

        }

        if question:
            mapping["question"] = question



        if embedding:


            vector = np.array(

                embedding,

                dtype=np.float32,

            ).tobytes()



            mapping[

                self.vector_field

            ] = vector



        self.redis.hset(

            redis_key,

            mapping=mapping,

        )

        if ttl_seconds and int(ttl_seconds) > 0:
            self.redis.expire(redis_key, int(ttl_seconds))



    # ============================================================
    # Semantic search
    # ============================================================


    def search(
        self,
        embedding:list[float],
        workspace_id: str | None = None,
        cache_scope: str | None = None,
    ) -> Optional[Dict[str,Any]]:


        if not embedding or not workspace_id:

            return None



        vector = np.array(

            embedding,

            dtype=np.float32,

        ).tobytes()



        if not self.vector_index_ready:
            self._ensure_index()
        if not self.vector_index_ready:
            return None

        try:


            query = (
                f"(@workspace_id:{{{workspace_id}}} "
                f"@cache_scope:{{{cache_scope or 'legacy'}}})=>[KNN 1 "
                f"@{self.vector_field} $vec AS score]"
            )



            result = self.redis.ft(

                self.index_name

            ).search(

                Query(query).dialect(2),

                query_params={

                    "vec":

                        vector

                },

            )


        except Exception:


            return None



        if not result.docs:

            return None



        doc = result.docs[0]

        stored_workspace = getattr(doc, "workspace_id", None)
        if workspace_id and stored_workspace != str(workspace_id):
            return None



        answer = getattr(

            doc,

            "answer",

            None,

        )


        key = getattr(

            doc,

            "key",

            None,

        )


        score = getattr(

            doc,

            "score",

            None,

        )



        if answer is None:

            return None



        distance = float(

            score

            or

            0

        )



        similarity = (

            1.0

            -

            distance

        )



        return {


            "answer":

                answer,


            "key":

                key,


            "distance":

                distance,


            "similarity":

                similarity,


        }



    # ============================================================
    # Size
    # ============================================================


    def size(self, workspace_id: str | None = None) -> int:


        try:

            pattern = self.key_prefix + (
                f"{workspace_id}:*" if workspace_id else "*"
            )
            keys = self.redis.keys(pattern)


            return len(keys)


        except Exception:

            return 0



    # ============================================================
    # Clear
    # ============================================================


    def clear(self, workspace_id: str | None = None) -> None:


        try:


            pattern = self.key_prefix + (
                f"{workspace_id}:*" if workspace_id else "*"
            )
            keys = self.redis.keys(pattern)


            if keys:

                self.redis.delete(

                    *keys

                )


        except Exception:

            pass


    def acquire_request_lock(
        self,
        workspace_id: str,
        cache_key: str,
        timeout: int = 60,
        blocking_timeout: float = 1.0,
    ):
        """Return a Redis lock scoped to one workspace and request key.

        The digest keeps arbitrary request material out of Redis key names while
        preserving a stable lock identity for concurrent equivalent requests.
        Callers own the returned lock and must release it when finished.
        """
        digest = hashlib.sha256(str(cache_key).encode("utf-8")).hexdigest()
        return self.redis.lock(
            f"ascg:lock:{workspace_id}:{digest}",
            timeout=max(1, int(timeout)),
            blocking_timeout=max(0.0, float(blocking_timeout)),
            thread_local=False,
        )



    # ============================================================
    # Info
    # ============================================================


    def info(self, workspace_id: str | None = None) -> Dict[str,Any]:


        return {


            "redis_host":

                settings.redis_host,


            "redis_port":

                settings.redis_port,


            "index_name":

                self.index_name,


            "key_prefix":

                self.key_prefix,


            "vector_dim":

                settings.vector_dimension,


            "algorithm":

                settings.vector_algorithm,


            "distance_metric":

                settings.distance_metric,


            "size":

                self.size(workspace_id=workspace_id),


            "ping":

                self.ping(),


            "vector_index_ready":

                self.vector_index_ready,

        }
