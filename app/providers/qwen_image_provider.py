from __future__ import annotations

from typing import Any

from app.clients.qwen_image_client import (
    QwenImageClient,
)
from app.schemas.llm_response import LLMResponse


class QwenImageProvider:
    """
    Qwen Image provider.

    Handles image-generation requests only.
    """

    provider_name = "qwen_image"

    def __init__(
        self,
        client: QwenImageClient,
    ) -> None:

        self.client = client

    # ============================================================
    # Image generation
    # ============================================================

    def generate(
        self,
        messages: list[dict[str, Any]],
        size: str | None = None,
        n: int = 1,
        timeout: float | None = None,
    ) -> dict[str, Any]:

        return self.client.generate(

            messages=messages,

            size=size,

            n=n,

            timeout=max(
                self.client.timeout,
                float(timeout or 0.0),
            ),

        )

    # ============================================================
    # Compatibility API
    # ============================================================

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ):

        result = self.generate(
            messages=messages,
            size=kwargs.get(
                "size"
            ),
            n=kwargs.get(
                "n",
                1,
            ),
            timeout=kwargs.get("timeout"),
        )

        images = result.get("images", [])
        answer = "\n".join(
            str(url) for url in images if url
        )

        return LLMResponse(
            answer=answer,
            model=result.get("model", self.model),
            provider=result.get("provider", self.provider),
            prompt_tokens=0,
            completion_tokens=0,
            cost=0.0,
            latency_ms=float(result.get("latency_ms", 0.0) or 0.0),
            finish_reason="stop",
            raw=result,
            images=images,
        )

    # ============================================================
    # Properties
    # ============================================================

    @property
    def model(self) -> str:

        return self.client.model

    @property
    def provider(self) -> str:

        return self.provider_name


__all__ = [
    "QwenImageProvider",
]
