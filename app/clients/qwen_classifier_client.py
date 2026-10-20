from __future__ import annotations

import json
import time
from typing import Any

import requests


class QwenClassifierClient:
    """
    Lightweight Qwen classifier client.

    Purpose:
        Only determine whether an incoming request is:

            text
            image

    It does NOT answer the user's request.

    It uses DashScope's OpenAI-compatible API.
    """

    DEFAULT_MODEL = "qwen3.8-flash"

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:

        if not api_key:
            raise ValueError(
                "Qwen classifier API key is not configured"
            )

        if not base_url:
            raise ValueError(
                "Qwen classifier base URL is not configured"
            )

        self.api_key = api_key

        self.base_url = base_url.rstrip("/")

        self.model = (
            model
            or self.DEFAULT_MODEL
        )

        self.timeout = timeout

        self.max_retries = max_retries

        # Use a direct requests session instead of the OpenAI SDK here.
        # The router must not inherit HTTP(S)_PROXY because that proxy can
        # interrupt the TLS handshake to DashScope.
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ============================================================
    # Message preparation
    # ============================================================

    @staticmethod
    def _messages_text(
        messages: list[dict[str, Any]],
    ) -> str:

        parts: list[str] = []

        for message in messages:

            if not isinstance(
                message,
                dict,
            ):
                continue

            role = str(
                message.get(
                    "role",
                    "user",
                )
            )

            content = message.get(
                "content",
                "",
            )

            if isinstance(
                content,
                str,
            ):

                text = content

            elif isinstance(
                content,
                list,
            ):

                text_parts: list[str] = []

                for item in content:

                    if not isinstance(
                        item,
                        dict,
                    ):
                        continue

                    item_type = item.get(
                        "type"
                    )

                    if item_type == "text":

                        text_parts.append(
                            str(
                                item.get(
                                    "text",
                                    "",
                                )
                            )
                        )

                    elif item_type in {
                        "image_url",
                        "input_image",
                    }:

                        text_parts.append(
                            "[IMAGE]"
                        )

                text = " ".join(
                    text_parts
                )

            else:

                text = str(
                    content
                )

            if text.strip():

                parts.append(
                    f"{role}: {text}"
                )

        return "\n".join(
            parts
        )

    # ============================================================
    # Classification prompt
    # ============================================================

    @staticmethod
    def _system_prompt() -> str:

        return """
You are a request modality classifier.

Your ONLY task is to determine whether the user's request requires:

1. text
2. image

Return JSON only.

Required schema:

{
  "modality": "text" | "image",
  "confidence": 0.0,
  "reason": "short explanation"
}

Rules:

- If the request can be answered entirely with normal text reasoning,
  return "text".
- If the user asks to generate, create, draw, render, edit,
  transform, modify, or produce an image, return "image".
- If the user explicitly provides an image and asks to analyze,
  understand, describe, inspect, compare, or extract information
  from that image, return "image".
- If an image is merely mentioned but the task itself is ordinary
  text reasoning, return "text".
- Do not answer the user's actual question.
- Do not output markdown.
- Do not output anything outside the JSON object.
""".strip()

    # ============================================================
    # Response extraction
    # ============================================================

    @staticmethod
    def _extract_content(
        response: Any,
    ) -> str:

        try:

            content = (
                response
                .choices[0]
                .message
                .content
            )

        except Exception as exc:

            raise RuntimeError(
                "Qwen classifier returned an invalid response"
            ) from exc

        if content is None:

            raise RuntimeError(
                "Qwen classifier returned empty content"
            )

        return str(
            content
        ).strip()

    # ============================================================
    # JSON parsing
    # ============================================================

    @staticmethod
    def _parse(
        content: str,
    ) -> dict[str, Any]:

        cleaned = (
            content
            .strip()
            .replace(
                "```json",
                "",
            )
            .replace(
                "```",
                "",
            )
            .strip()
        )

        try:

            data = json.loads(
                cleaned
            )

        except Exception as exc:

            raise RuntimeError(
                "Qwen classifier returned invalid JSON: "
                + cleaned
            ) from exc

        if not isinstance(
            data,
            dict,
        ):

            raise RuntimeError(
                "Qwen classifier JSON must be an object"
            )

        modality = str(
            data.get(
                "modality",
                "",
            )
        ).strip().lower()

        if modality not in {
            "text",
            "image",
        }:

            raise RuntimeError(
                "Qwen classifier returned unsupported modality: "
                + modality
            )

        try:

            confidence = float(
                data.get(
                    "confidence",
                    0.0,
                )
            )

        except Exception:

            confidence = 0.0

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        reason = str(
            data.get(
                "reason",
                "",
            )
        ).strip()

        return {
            "modality": modality,
            "confidence": round(
                confidence,
                4,
            ),
            "reason": reason,
        }

    # ============================================================
    # Public classification API
    # ============================================================

    def classify(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:

        if not isinstance(
            messages,
            list,
        ):

            raise ValueError(
                "messages must be a list"
            )

        if not messages:

            raise ValueError(
                "messages cannot be empty"
            )

        user_text = (
            self._messages_text(
                messages
            )
        )

        if not user_text.strip():

            return {
                "modality": "text",
                "confidence": 1.0,
                "reason": "empty textual request defaults to text",
            }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
            "temperature": 0,
            "max_tokens": 120,
        }

        response = self.session.post(
            self.base_url + "/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(
                "Qwen classifier returned invalid JSON response"
            ) from exc

        if not response.ok:
            raise RuntimeError(
                "Qwen classifier API request failed "
                f"({response.status_code}): {data}"
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(
                "Qwen classifier returned an invalid response"
            ) from exc

        if content is None:
            raise RuntimeError(
                "Qwen classifier returned empty content"
            )

        content = str(content).strip()

        result = (
            self._parse(
                content
            )
        )

        result["model"] = self.model

        return result