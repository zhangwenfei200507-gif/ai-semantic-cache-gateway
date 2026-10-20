from __future__ import annotations

from app.providers.base import BaseProvider
from app.schemas.llm_response import LLMResponse


class GenericOpenAICompatibleProvider(BaseProvider):
    """Provider adapter for arbitrary OpenAI-compatible text APIs."""

    def __init__(self, client, provider_name: str) -> None:
        super().__init__(client)
        self.name = provider_name

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        response = self.client.chat(messages=messages, model=model, **kwargs)

        if not isinstance(response, LLMResponse):
            raise TypeError("Client must return LLMResponse")

        response.provider = response.provider or self.name
        return response


__all__ = ["GenericOpenAICompatibleProvider"]
