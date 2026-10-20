from __future__ import annotations

from dataclasses import dataclass
from typing import Any



@dataclass(slots=True)
class RequestHistory:

    request_id: str

    user_id: str | None

    provider: str

    model: str

    question: str

    answer: str

    cache_hit: bool = False

    cache_type: str | None = None

    similarity: float | None = None

    threshold: float | None = None

    latency_ms: float = 0.0

    provider_latency_ms: float = 0.0

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    cost: float = 0.0

    status: str = "completed"

    error: str | None = None



    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {

            "request_id":
                self.request_id,

            "user_id":
                self.user_id,

            "provider":
                self.provider,

            "model":
                self.model,

            "question":
                self.question,

            "answer":
                self.answer,

            "cache_hit":
                self.cache_hit,

            "cache_type":
                self.cache_type,

            "similarity":
                self.similarity,

            "threshold":
                self.threshold,

            "latency_ms":
                self.latency_ms,

            "provider_latency_ms":
                self.provider_latency_ms,

            "usage":
                {
                    "prompt_tokens":
                        self.prompt_tokens,

                    "completion_tokens":
                        self.completion_tokens,

                    "total_tokens":
                        self.total_tokens,
                },

            "cost":
                self.cost,

            "status":
                self.status,

            "error":
                self.error,

        }