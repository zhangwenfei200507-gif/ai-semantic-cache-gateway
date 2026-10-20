from __future__ import annotations

from typing import Any

from app.clients.qwen_classifier_client import (
    QwenClassifierClient,
)


class QwenClassifierProvider:
    """
    Provider wrapper for the lightweight Qwen classifier.

    This provider is NOT a normal answer-generation provider.

    It only classifies request modality:

        text
        image
    """

    provider_name = "qwen_classifier"

    def __init__(
        self,
        client: QwenClassifierClient,
    ) -> None:

        self.client = client

    # ============================================================
    # Classification
    # ============================================================

    def classify(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:

        return self.client.classify(
            messages
        )

    # ============================================================
    # Compatibility helper
    # ============================================================

    def detect_modality(
        self,
        messages: list[dict[str, Any]],
    ) -> str:

        result = self.classify(
            messages
        )

        return str(
            result.get(
                "modality",
                "text",
            )
        )

    # ============================================================
    # Provider information
    # ============================================================

    @property
    def model(self) -> str:

        return self.client.model

    @property
    def provider(self) -> str:

        return self.provider_name


__all__ = [
    "QwenClassifierProvider",
]