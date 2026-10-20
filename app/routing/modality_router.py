from __future__ import annotations

import re
from typing import Any

from app.clients.qwen_classifier_client import (
    QwenClassifierClient,
)
from app.config.settings import settings


class ModalityDecision:
    """
    Normalized modality decision.

    modality:
        text
        image
    """

    def __init__(
        self,
        modality: str,
        confidence: float,
        reason: str = "",
        classifier_model: str = "",
    ) -> None:

        normalized = (
            str(
                modality
            )
            .strip()
            .lower()
        )

        if normalized not in {
            "text",
            "image",
        }:

            raise ValueError(
                f"Unsupported modality: {modality}"
            )

        self.modality = normalized

        self.confidence = max(
            0.0,
            min(
                1.0,
                float(
                    confidence
                ),
            ),
        )

        self.reason = str(
            reason
            or
            ""
        ).strip()

        self.classifier_model = str(
            classifier_model
            or
            ""
        ).strip()

    def to_dict(self) -> dict[str, Any]:

        return {

            "modality":
                self.modality,

            "confidence":
                round(
                    self.confidence,
                    4,
                ),

            "reason":
                self.reason,

            "classifier_model":
                self.classifier_model,

        }


class ModalityRouter:
    """
    First-stage request modality router.

    Responsibilities:

        1. Detect text vs image.
        2. Use Qwen3.8 Flash as the lightweight classifier.
        3. Never perform document routing.
        4. Never choose DeepSeek/OpenAI.
        5. Never answer the user's request.

    Downstream routing:

        text
            -> existing ModelRouter

        image
            -> Qwen Image
    """

    TEXT = "text"
    IMAGE = "image"

    def __init__(
        self,
        classifier_client: QwenClassifierClient | None = None,
    ) -> None:

        self.classifier_client: QwenClassifierClient | None = (
            classifier_client
            or
            self._create_classifier()
        )

    # ============================================================
    # Classifier
    # ============================================================

    @staticmethod
    def _create_classifier():

        if not settings.qwen_classifier_api_key:
            return None

        return QwenClassifierClient(

            api_key=
                settings.qwen_classifier_api_key,

            base_url=
                settings.qwen_classifier_base_url,

            model=
                settings.qwen_classifier_model,

            timeout=min(
                settings.llm_timeout,
                30.0,
            ),

            max_retries=
                settings.llm_max_retries,

        )

    # ============================================================
    # Local fast detection
    # ============================================================

    @staticmethod
    def _contains_image_content(
        messages: list[dict[str, Any]],
    ) -> bool:

        for message in messages:

            if not isinstance(
                message,
                dict,
            ):
                continue

            content = message.get(
                "content"
            )

            if not isinstance(
                content,
                list,
            ):
                continue

            for item in content:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                item_type = str(
                    item.get(
                        "type",
                        "",
                    )
                ).lower()

                if item_type in {
                    "image_url",
                    "input_image",
                    "image",
                }:

                    return True

        return False

    @staticmethod
    def _looks_like_image_generation(messages: list[dict[str, Any]]) -> bool:
        # Only the latest user turn defines the new action, not prior images or system text.
        message = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        text = str(content).strip().lower()
        if re.search(r"(如何|怎么|为什么|原理|解释|代码|接口|教程|explain|how (?:do|to|can|does))", text):
            return False
        if re.search(r"(不要|别|无需|不需要).{0,6}(生成|画|绘制|制作)|(?:don't|do not).{0,12}(draw|generate|create)", text):
            return False
        return bool(re.search(
            r"(生成|创建|制作|绘制|画).{0,100}(图片|图像|插画|照片|海报|头像|壁纸|一张图)"
            r"|(?:帮我|请)?画(?:一|个|只|幅|张)"
            r"|\b(?:generate|create|make|draw|paint|render)\b.{0,100}\b(?:image|picture|photo|illustration|poster|portrait|wallpaper)\b",
            text,
        ))

    # ============================================================
    # Fallback classification
    # ============================================================

    @classmethod
    def _fallback(
        cls,
        messages: list[dict[str, Any]],
        reason: str,
    ) -> ModalityDecision:

        if cls._contains_image_content(
            messages
        ):

            return ModalityDecision(

                modality=cls.IMAGE,

                confidence=0.99,

                reason=(
                    "image content detected locally"
                ),

            )

        if cls._looks_like_image_generation(
            messages
        ):

            return ModalityDecision(

                modality=cls.IMAGE,

                confidence=0.97,

                reason=(
                    "image-generation intent detected locally"
                ),

            )

        return ModalityDecision(

            modality=cls.TEXT,

            confidence=0.55,

            reason=reason,

        )

    # ============================================================
    # Public API
    # ============================================================

    def route(
        self,
        messages: list[dict[str, Any]],
    ) -> ModalityDecision:

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

        # --------------------------------------------------------
        # Deterministic local image detection.
        #
        # This avoids spending classifier tokens when the request
        # already contains an obvious image.
        # --------------------------------------------------------

        if self._contains_image_content(
            messages
        ):

            return ModalityDecision(

                modality=self.IMAGE,

                confidence=0.99,

                reason=(
                    "image content detected locally"
                ),

            )

        # Explicit image-generation language is deterministic enough to
        # bypass the classifier and avoid an unnecessary routing token call.
        if self._looks_like_image_generation(messages):
            return ModalityDecision(
                modality=self.IMAGE,
                confidence=0.97,
                reason="explicit image-generation intent detected locally",
            )

        # --------------------------------------------------------
        # Ambiguous textual requests use Qwen3.8-Flash for modality
        # requests. Those requests must be classified by Qwen3.8-Flash
        # so the lightweight router is actually exercised and metered.
        # The local detector remains the safety fallback if the
        # classifier is unavailable.
        # --------------------------------------------------------

        # --------------------------------------------------------
        # Qwen lightweight classifier.
        # --------------------------------------------------------

        if self.classifier_client is None:
            return self._fallback(
                messages,
                reason="classifier not configured; local fallback used",
            )

        try:

            result = (
                self.classifier_client.classify(
                    messages
                )
            )

            return ModalityDecision(

                modality=
                    result.get(
                        "modality",
                        self.TEXT,
                    ),

                confidence=
                    result.get(
                        "confidence",
                        0.0,
                    ),

                reason=
                    result.get(
                        "reason",
                        "",
                    ),

                classifier_model=
                    result.get(
                        "model",
                        "",
                    ),

            )

        except Exception as exc:

            # Classifier failure must not make ordinary text
            # requests completely unavailable.

            return self._fallback(

                messages,

                reason=(
                    "classifier unavailable; "
                    "safe text fallback: "
                    f"{exc}"
                ),

            )

    def route_to_dict(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:

        return self.route(
            messages
        ).to_dict()


modality_router = ModalityRouter()


__all__ = [
    "ModalityDecision",
    "ModalityRouter",
    "modality_router",
]
