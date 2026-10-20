from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.llm_response import (
    LLMResponse,
)


@dataclass(slots=True)
class GatewayResponse:

    llm: LLMResponse

    cache_hit: bool = False

    cache_type: str | None = None

    similarity: float | None = None

    threshold: float | None = None

    context: Any = None

    routing: dict[str, Any] | None = None


    @property
    def answer(self) -> str:

        return self.llm.answer


    @property
    def model(self) -> str:

        return self.llm.model


    @property
    def provider(self) -> str:

        return self.llm.provider


    @property
    def tokens(self) -> int:

        return self.llm.total_tokens


    @property
    def usage(
        self,
    ) -> dict[str, int]:

        return {

            "prompt_tokens":
                self.llm.prompt_tokens,

            "completion_tokens":
                self.llm.completion_tokens,

            "total_tokens":
                self.llm.total_tokens,

        }


    @property
    def cost(self) -> float:

        return float(
            self.llm.cost or 0.0
        )


    @property
    def latency_ms(self) -> float:

        return float(
            self.llm.latency_ms or 0.0
        )


    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {

            "llm":
                self.llm.to_dict(),

            "cache_hit":
                self.cache_hit,

            "cache_type":
                self.cache_type,

            "similarity":
                self.similarity,

            "threshold":
                self.threshold,

            "routing":
                self.routing,

            "context":
                (
                    self.context.to_dict()
                    if hasattr(
                        self.context,
                        "to_dict",
                    )
                    else self.context
                ),

        }


    def __getitem__(
        self,
        key: str,
    ) -> Any:

        mapping = {

            "answer":
                self.answer,

            "model":
                self.model,

            "provider":
                self.provider,

            "tokens":
                self.tokens,

            "cache":
                self.cache_hit,

            "cache_hit":
                self.cache_hit,

            "cache_type":
                self.cache_type,

            "similarity":
                self.similarity,

            "threshold":
                self.threshold,

            "usage":
                self.usage,

            "cost":
                self.cost,

            "latency_ms":
                self.latency_ms,

            "routing":
                self.routing,

            "context":
                (
                    self.context.to_dict()
                    if hasattr(
                        self.context,
                        "to_dict",
                    )
                    else self.context
                ),

        }


        if key not in mapping:

            raise KeyError(key)


        return mapping[key]