from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.llm_response import LLMResponse



class LLMClient(ABC):
    """
    Unified low level LLM client contract.

    Provider
        |
    Client
        |
    External LLM API
        |
    LLMResponse
    """


    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout: int = 60,
        max_retries: int = 2,
        provider_name: str = "",
    ) -> None:


        self.api_key = api_key


        self.base_url = (
            base_url.rstrip("/")
        )


        self.model = model


        self.timeout = timeout


        self.max_retries = max_retries


        self.provider_name = provider_name



    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
    ) -> LLMResponse:

        raise NotImplementedError