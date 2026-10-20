from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional


from app.cache.cache_repository import CacheRepository
from app.cache.cache_policy import CachePolicy
from app.cache.cache_metrics import CacheMetrics

from app.embedding.embedding_service import EmbeddingService
from app.similarity.scorer import SimilarityScorer

from app.utils.hash import hash_messages



class CacheService:
    """
    Production semantic cache service.


    Flow:

        request
           |
        exact lookup
           |
        semantic lookup
           |
        embedding
           |
        redis vector search
           |
        similarity threshold
           |
        hit / miss

    """


    def __init__(
        self,
        repository: Optional[CacheRepository] = None,
        embedding_service: Optional[EmbeddingService] = None,
        scorer: Optional[SimilarityScorer] = None,
        similarity_threshold: float | None = None,
        policy: CachePolicy | None = None,
        metrics: CacheMetrics | None = None,
    ) -> None:



        self.policy = (
            policy
            if policy is not None
            else CachePolicy.default()
        )


        self.metrics = (
            metrics
            if metrics is not None
            else CacheMetrics()
        )


        self.repository = (
            repository
            if repository is not None
            else CacheRepository()
        )


        self.embedding_service = (
            embedding_service
            if embedding_service is not None
            else EmbeddingService()
        )



        if similarity_threshold is None:

            similarity_threshold = (
                self.policy.similarity_threshold
            )


        self.similarity_threshold = float(
            similarity_threshold
        )


        if not (
            0.0
            <=
            self.similarity_threshold
            <=
            1.0
        ):

            raise ValueError(
                "similarity_threshold must be between 0 and 1"
            )



        self.scorer = (
            scorer
            if scorer is not None
            else SimilarityScorer(
                threshold=self.similarity_threshold
            )
        )



    # ==========================================================
    # Text normalize
    # ==========================================================


    @staticmethod
    def _content_to_text(
        content: Any,
    ) -> str:


        if content is None:

            return ""


        if isinstance(
            content,
            str,
        ):

            return content.strip()



        if isinstance(
            content,
            list,
        ):

            result = []

            for item in content:

                if not isinstance(
                    item,
                    dict,
                ):

                    continue


                if item.get(
                    "type"
                ) == "text":

                    text = item.get(
                        "text",
                        "",
                    )

                    if text:

                        result.append(
                            str(text)
                        )


            return " ".join(
                result
            ).strip()



        return str(
            content
        ).strip()



    @classmethod
    def _messages_to_text(
        cls,
        messages,
    ) -> str:


        if not isinstance(
            messages,
            list,
        ):

            raise TypeError(
                "messages must be list"
            )


        parts = []


        for message in messages:


            if not isinstance(
                message,
                dict,
            ):

                continue



            text = cls._content_to_text(
                message.get(
                    "content",
                    "",
                )
            )


            if text:

                parts.append(
                    text
                )


        return "\n".join(
            parts
        ).strip()



    # ==========================================================
    # Exact
    # ==========================================================


    def get_exact(
        self,
        messages,
        workspace_id: str | None = None,
        cache_context: dict[str, Any] | None = None,
    ) -> Optional[str]:
        key = self._cache_key(messages, cache_context)


        return self.repository.find(
            key,
            workspace_id=workspace_id,
            cache_scope=self._cache_scope(cache_context),
        )



    # ==========================================================
    # Semantic
    # ==========================================================


    def get_semantic(
        self,
        messages,
        workspace_id: str | None = None,
        cache_context: dict[str, Any] | None = None,
    ) -> Optional[Dict[str, Any]]:


        if not self.policy.semantic_enabled:

            return None



        text = self._messages_to_text(
            messages
        )


        if not text:

            return None



        embedding = (
            self.embedding_service.encode(
                text
            )
        )


        if not embedding:

            return None



        candidate = self.repository.search(
            embedding,
            workspace_id=workspace_id,
            cache_scope=self._cache_scope(cache_context),
        )


        if candidate is None:

            return None



        similarity = float(
            candidate.get(
                "similarity",
                0.0,
            )
        )



        score = self.scorer.score(
            similarity
        )



        if not score["matched"]:

            return None



        return {


            "answer":
                candidate["answer"],


            "key":
                candidate.get(
                    "key"
                ),


            "similarity":
                score["similarity"],


            "distance":
                candidate.get(
                    "distance"
                ),


            "threshold":
                score["threshold"],


            "matched":
                True,

        }



    # ==========================================================
    # Lookup
    # ==========================================================


    def lookup(
        self,
        messages,
        workspace_id: str | None = None,
        cache_context: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:


        self.metrics.record_request()



        # exact

        if self.policy.exact_enabled:


            exact = self.get_exact(
                messages,
                workspace_id=workspace_id,
                cache_context=cache_context,
            )


            if exact is not None:


                self.metrics.record_exact_hit()


                return {


                    "hit":
                        True,


                    "type":
                        "exact",


                    "answer":
                        exact,


                    "similarity":
                        1.0,

                }



        # semantic
        semantic = self.get_semantic(
            messages,
            workspace_id=workspace_id,
            cache_context=cache_context,
        )



        if semantic is not None:


            self.metrics.record_semantic_hit(
                semantic["similarity"]
            )


            return {


                "hit":
                    True,


                "type":
                    "semantic",


                "answer":
                    semantic["answer"],


                "similarity":
                    semantic["similarity"],


                "distance":
                    semantic.get(
                        "distance"
                    ),

            }



        self.metrics.record_miss()



        return {


            "hit":
                False,


            "type":
                None,


            "answer":
                None,


            "similarity":
                None,

        }



    # ==========================================================
    # Gateway compatibility
    # ==========================================================


    def get(
        self,
        messages,
    ) -> Optional[str]:


        result = self.lookup(
            messages
        )


        if not result["hit"]:

            return None


        return result["answer"]



    # ==========================================================
    # Store
    # ==========================================================


    def set(
        self,
        messages,
        answer: str,
        workspace_id: str | None = None,
        cache_context: dict[str, Any] | None = None,
    ) -> None:



        if not isinstance(
            answer,
            str,
        ):

            answer = str(
                answer
            )



        if len(answer) > self.policy.max_answer_length:

            return



        key = self._cache_key(messages, cache_context)


        text = self._messages_to_text(
            messages
        )


        embedding = None


        if text:

            embedding = (
                self.embedding_service.encode(
                    text
                )
            )



        self.repository.save(
            key,
            answer,
            embedding,
            ttl_seconds=self.policy.ttl_seconds,
            question=text,
            workspace_id=workspace_id,
            cache_scope=self._cache_scope(cache_context),
        )

    @staticmethod
    def _cache_scope(context: dict[str, Any] | None) -> str:
        payload = json.dumps(context or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _cache_key(cls, messages, context: dict[str, Any] | None) -> str:
        payload = json.dumps(
            {"messages": messages, "scope": cls._cache_scope(context)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hash_messages([{"role": "user", "content": payload}])



    # ==========================================================
    # Utility
    # ==========================================================


    def ping(
        self,
    ) -> bool:

        return self.repository.ping()



    def size(
        self,
        workspace_id: str | None = None,
    ) -> int:

        return self.repository.size(workspace_id=workspace_id)



    def clear(
        self,
        workspace_id: str | None = None,
    ) -> None:

        self.repository.clear(workspace_id=workspace_id)



    def info(
        self,
        workspace_id: str | None = None,
    ) -> Dict[str, Any]:

        return {


            **self.repository.info(workspace_id=workspace_id),


            "similarity_threshold":
                self.similarity_threshold,


            "policy":
                {

                    "semantic_enabled":
                        self.policy.semantic_enabled,


                    "exact_enabled":
                        self.policy.exact_enabled,


                    "ttl_seconds":
                        self.policy.ttl_seconds,

                }

        }



    def metrics_info(
        self,
    ):

        return self.metrics.snapshot()
