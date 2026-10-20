from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import settings


@dataclass(frozen=True)
class CachePolicy:
    """
    Central cache strategy configuration.
    """


    similarity_threshold: float = 0.75


    ttl_seconds: int = 86400


    semantic_enabled: bool = True


    exact_enabled: bool = True


    max_answer_length: int = 20000



    @classmethod
    def default(
        cls,
    ) -> "CachePolicy":


        return cls(

            similarity_threshold=float(
                getattr(
                    settings,
                    "cache_threshold",
                    0.75,
                )
            ),

            ttl_seconds=int(
                getattr(
                    settings,
                    "cache_ttl",
                    86400,
                )
            ),

            semantic_enabled=bool(
                getattr(
                    settings,
                    "semantic_cache_enabled",
                    True,
                )
            ),

            exact_enabled=bool(
                getattr(
                    settings,
                    "exact_cache_enabled",
                    True,
                )
            ),

            max_answer_length=int(
                getattr(
                    settings,
                    "cache_max_answer_length",
                    20000,
                )
            ),
        )
