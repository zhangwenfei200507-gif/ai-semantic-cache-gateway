from __future__ import annotations

import time

import httpx

from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)

from app.clients.llm_client import LLMClient
from app.schemas.llm_response import LLMResponse


class OpenAICompatibleClient(
    LLMClient
):
    """
    OpenAI-compatible client.

    Supports:

    - OpenAI
    - DeepSeek
    - other compatible APIs
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

        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            provider_name=provider_name,
        )

        if not api_key:

            raise ValueError(
                "LLM API key is required"
            )

        self.http_client = httpx.Client(
            timeout=timeout
        )

        self.client = OpenAI(

            api_key=api_key,

            base_url=base_url,

            timeout=timeout,

            max_retries=max_retries,

            http_client=self.http_client,

        )


    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:

        start = time.perf_counter()


        target_model = (
            model
            or self.model
        )


        try:

            response = (

                self.client

                .chat

                .completions

                .create(
                    model=target_model,
                    messages=messages,
                    **self._request_options(
                        timeout=timeout,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                )

            )

            if not response.choices:

                raise RuntimeError(
                    "LLM response has no choices"
                )


            choice = (
                response.choices[0]
            )


            answer = (
                choice.message.content
                or
                ""
            )


            usage = (
                response.usage
            )


            prompt_tokens = 0

            completion_tokens = 0


            if usage:

                prompt_tokens = (
                    usage.prompt_tokens
                    or
                    0
                )

                completion_tokens = (
                    usage.completion_tokens
                    or
                    0
                )


            latency_ms = (

                time.perf_counter()
                -
                start

            ) * 1000


            return LLMResponse(

                answer=answer,

                model=(

                    getattr(

                        response,

                        "model",

                        None,

                    )
                    or
                    target_model

                ),

                provider=
                    self.provider_name,

                prompt_tokens=
                    prompt_tokens,

                completion_tokens=
                    completion_tokens,

                latency_ms=
                    round(
                        latency_ms,
                        2,
                    ),

                finish_reason=(
                    choice.finish_reason
                ),

                raw=response,

            )


        except APITimeoutError as exc:

            raise RuntimeError(

                "LLM timeout"

            ) from exc


        except APIConnectionError as exc:

            raise RuntimeError(

                "LLM connection error"

            ) from exc


        except APIStatusError as exc:

            raise RuntimeError(

                f"LLM API error "
                f"{exc.status_code}"

            ) from exc


        except Exception as exc:

            raise RuntimeError(

                f"LLM request failed: "
                f"{exc}"

            ) from exc


    def _request_options(
        self,
        timeout: float | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        options = {}
        if timeout is not None:
            options["timeout"] = timeout
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            key = "max_completion_tokens" if self.provider_name == "openai" else "max_tokens"
            options[key] = max_tokens
        return options


    def close(
        self,
    ) -> None:

        try:

            self.http_client.close()

        except Exception:

            pass
