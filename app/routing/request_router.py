from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.routing.modality_router import (
    ModalityDecision,
    ModalityRouter,
)
from app.routing.model_router import (
    ModelRouter,
)
from app.providers.qwen_image_provider import (
    QwenImageProvider,
)


@dataclass(frozen=True)
class RequestRoutingDecision:
    modality: ModalityDecision
    downstream: Any

    def to_dict(self) -> dict[str, Any]:

        if hasattr(
            self.downstream,
            "to_dict",
        ):
            downstream = (
                self.downstream.to_dict()
            )
        else:
            downstream = self.downstream

        return {
            "modality": (
                self.modality.to_dict()
            ),
            "downstream": downstream,
        }


class RequestRouter:
    """
    Top-level routing layer.

    Flow:

        request
          |
          v
        Qwen classifier
          |
        +-------+
        |       |
      TEXT    IMAGE
        |       |
        v       v
    ModelRouter QwenImageProvider
        |
      +---+
      |   |
    DS   OpenAI
    """

    def __init__(
        self,
        modality_router: ModalityRouter,
        model_router: ModelRouter,
        qwen_image_provider: QwenImageProvider,
    ) -> None:

        self.modality_router = (
            modality_router
        )

        self.model_router = (
            model_router
        )

        self.qwen_image_provider = (
            qwen_image_provider
        )

    def route(
        self,
        messages: list[dict[str, Any]],
    ) -> RequestRoutingDecision:

        modality = (
            self.modality_router.route(
                messages
            )
        )

        if modality.is_image:

            return RequestRoutingDecision(
                modality=modality,
                downstream={
                    "provider": "qwen_image",
                    "model": (
                        self.qwen_image_provider.model
                    ),
                    "mode": "image",
                },
            )

        decision = (
            self.model_router.route(
                messages
            )
        )

        return RequestRoutingDecision(
            modality=modality,
            downstream=decision,
        )

    def generate_image(
        self,
        prompt: str,
        images: list[str] | None = None,
    ) -> dict[str, Any]:

        return self.qwen_image_provider.generate(
            prompt=prompt,
            images=images,
        )


__all__ = [
    "RequestRoutingDecision",
    "RequestRouter",
]