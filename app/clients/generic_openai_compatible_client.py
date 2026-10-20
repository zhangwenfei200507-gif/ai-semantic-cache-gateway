from __future__ import annotations

from app.clients.openai_compatible_client import OpenAICompatibleClient


class GenericOpenAICompatibleClient(OpenAICompatibleClient):
    """OpenAI-compatible client for user-configured providers."""

    def __init__(self, provider_name: str, **kwargs) -> None:
        super().__init__(provider_name=provider_name, **kwargs)


__all__ = ["GenericOpenAICompatibleClient"]
