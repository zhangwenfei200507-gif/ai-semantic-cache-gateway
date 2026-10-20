from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.config.providers import custom_provider_config


class ProviderRegistry:
    """
    Provider registry for admin UI.

    Exposes only providers that belong to the
    current application architecture.

    Supported:
        deepseek
        openai
        qwen_classifier
        qwen_image

    Not supported:
        qwen_document
    """

    def __init__(self) -> None:

        self.providers = (
            self._load()
        )

    def _load(
        self,
    ) -> list[dict[str, Any]]:

        providers: list[
            dict[str, Any]
        ] = []

        # ======================================================
        # DeepSeek
        # ======================================================

        deepseek_configured = (
            settings.is_deepseek_configured()
        )

        providers.append({

            "name":
                "deepseek",

            "status":
                (
                    "configured"
                    if deepseek_configured
                    else "not_configured"
                ),

            "models":
                (
                    settings.model_names("deepseek")
                    if deepseek_configured
                    else []
                ),

            "capabilities": [
                "text",
                "reasoning",
                "coding",
                "analysis",
                "chinese",
            ],
        })

        # ======================================================
        # OpenAI
        # ======================================================

        openai_configured = (
            settings.is_openai_configured()
        )

        providers.append({

            "name":
                "openai",

            "status":
                (
                    "configured"
                    if openai_configured
                    else "not_configured"
                ),

            "models":
                (
                    settings.model_names("openai")
                    if openai_configured
                    else []
                ),

            "capabilities": [
                "text",
                "reasoning",
                "coding",
                "analysis",
                "multilingual",
            ],
        })

        # ======================================================
        # Qwen Classifier
        # ======================================================

        classifier_configured = (
            settings.is_qwen_classifier_configured()
        )

        providers.append({

            "name":
                "qwen_classifier",

            "status":
                (
                    "configured"
                    if classifier_configured
                    else "not_configured"
                ),

            "models":
                (
                    [
                        settings.qwen_classifier_model
                        or "qwen3.6-flash-2026-04-16"
                    ]
                    if classifier_configured
                    else []
                ),

            "capabilities": [
                "classification",
            ],
        })

        # ======================================================
        # Qwen Image
        # ======================================================

        image_configured = (
            settings.is_qwen_image_configured()
        )

        providers.append({

            "name":
                "qwen_image",

            "status":
                (
                    "configured"
                    if image_configured
                    else "not_configured"
                ),

            "models":
                (
                    settings.model_names("qwen_image")
                    if image_configured
                    else []
                ),

            "capabilities": [
                "image",
                "image_generation",
            ],
        })

        # ======================================================
        # User-defined OpenAI-compatible providers
        # ======================================================

        for custom in custom_provider_config.all():
            name = str(custom.get("name", "")).strip().lower()
            if not name:
                continue

            import os
            api_key_env = str(custom.get("api_key_env", "")).strip()
            configured = bool(api_key_env and os.getenv(api_key_env))

            providers.append({
                "name": name,
                "status": "configured" if configured else "not_configured",
                "models": (
                    [str(item.get("name")) for item in custom.get("models", [])]
                    if configured and custom.get("enabled", True)
                    else []
                ),
                "capabilities": ["text", "openai_compatible"],
            })

        return providers

    def list(
        self,
    ) -> list[dict[str, Any]]:

        return self.providers

    def configured(
        self,
    ) -> list[dict[str, Any]]:

        return [

            provider

            for provider
            in self.providers

            if provider["status"]
            == "configured"

        ]

    def models(
        self,
    ) -> list[dict[str, str]]:

        result: list[
            dict[str, str]
        ] = []

        for provider in self.configured():

            for model in provider["models"]:

                result.append({

                    "provider":
                        provider["name"],

                    "model":
                        model,

                })

        return result

    def refresh(self) -> None:
        self.providers = self._load()


provider_registry = (
    ProviderRegistry()
)


__all__ = [
    "ProviderRegistry",
    "provider_registry",
]
