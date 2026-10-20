from __future__ import annotations

from app.clients.deepseek_client import (
    DeepSeekClient,
)

from app.clients.openai_client import (
    OpenAIClient,
)

from app.clients.qwen_classifier_client import (
    QwenClassifierClient,
)

from app.clients.qwen_image_client import (
    QwenImageClient,
)

from app.config.settings import settings
from app.config.providers import custom_provider_config

from app.clients.generic_openai_compatible_client import (
    GenericOpenAICompatibleClient,
)
from app.providers.generic_provider import (
    GenericOpenAICompatibleProvider,
)

from app.providers.deepseek_provider import (
    DeepSeekProvider,
)

from app.providers.openai_provider import (
    OpenAIProvider,
)

from app.providers.qwen_classifier_provider import (
    QwenClassifierProvider,
)

from app.providers.qwen_image_provider import (
    QwenImageProvider,
)


class ProviderFactory:
    """
    Central provider factory.

    Text:
        deepseek
        openai

    Image:
        qwen_image

    Optional classifier:
        qwen_classifier

    Deliberately unsupported:
        qwen_document
    """

    DEFAULT_TIMEOUT = 30.0

    DEFAULT_MAX_RETRIES = 0

    @staticmethod
    def _runtime_values(
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
    ):
        """Build one request-scoped provider from already resolved secrets."""
        if provider == "deepseek":
            return DeepSeekProvider(DeepSeekClient(
                api_key=api_key, base_url=base_url, model=model,
                timeout=timeout, max_retries=max_retries,
            ))
        if provider == "openai":
            return OpenAIProvider(OpenAIClient(
                api_key=api_key, base_url=base_url, model=model,
                timeout=timeout, max_retries=max_retries,
            ))
        if provider == "qwen_classifier":
            return QwenClassifierProvider(QwenClassifierClient(
                api_key=api_key, base_url=base_url, model=model,
                timeout=min(timeout, 30.0), max_retries=max_retries,
            ))
        if provider == "qwen_image":
            return QwenImageProvider(QwenImageClient(
                api_key=api_key, base_url=base_url, model=model,
                timeout=max(timeout, 180.0),
            ))
        return GenericOpenAICompatibleProvider(
            GenericOpenAICompatibleClient(
                provider_name=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_retries=max_retries,
            ),
            provider_name=provider,
        )

    @staticmethod
    def _runtime_limits() -> tuple[float, int]:
        return (
            float(getattr(settings, "llm_timeout", ProviderFactory.DEFAULT_TIMEOUT)),
            int(getattr(settings, "llm_max_retries", ProviderFactory.DEFAULT_MAX_RETRIES)),
        )

    @staticmethod
    def create_for_workspace(provider: str, model: str, workspace_id: int | str):
        """Resolve a credential inside one workspace and create a fresh client."""
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip()
        if not normalized_provider or not normalized_model:
            raise ValueError("provider and model are required")

        from app.providers.workspace_store import WorkspaceProviderStore

        store = WorkspaceProviderStore(workspace_id)
        spec = store.model_spec(normalized_provider, normalized_model)
        if spec is None:
            if settings.byok_required or not settings.global_provider_fallback_allowed:
                raise RuntimeError(
                    f"Model '{normalized_model}' is not configured for this workspace"
                )
            return ProviderFactory.create(normalized_provider, normalized_model)

        timeout, max_retries = ProviderFactory._runtime_limits()
        return ProviderFactory._runtime_values(
            provider=str(spec["runtime_provider"]),
            model=str(spec["model"]),
            api_key=str(spec["api_key"]),
            base_url=str(spec["base_url"]),
            timeout=timeout,
            max_retries=max_retries,
        )

    @staticmethod
    def create_classifier_for_workspace(workspace_id: int | str):
        from app.providers.workspace_store import WorkspaceProviderStore

        spec = WorkspaceProviderStore(workspace_id).classifier_spec()
        if spec is None:
            if settings.byok_required or not settings.global_provider_fallback_allowed:
                return None
            if not settings.is_qwen_classifier_configured():
                return None
            return ProviderFactory.create(
                "qwen_classifier",
                settings.qwen_classifier_model,
            )
        timeout, max_retries = ProviderFactory._runtime_limits()
        return ProviderFactory._runtime_values(
            "qwen_classifier",
            str(spec["model"]),
            str(spec["api_key"]),
            str(spec["base_url"]),
            timeout,
            max_retries,
        )

    @staticmethod
    def create(
        provider: str,
        model: str,
    ):

        normalized_provider = (
            str(provider or "")
            .strip()
            .lower()
        )

        normalized_model = (
            str(model or "")
            .strip()
        )

        if not normalized_provider:
            raise ValueError(
                "provider cannot be empty"
            )

        if not normalized_model:
            raise ValueError(
                "model cannot be empty"
            )

        timeout = float(
            getattr(
                settings,
                "llm_timeout",
                ProviderFactory.DEFAULT_TIMEOUT,
            )
        )

        max_retries = int(
            getattr(
                settings,
                "llm_max_retries",
                ProviderFactory.DEFAULT_MAX_RETRIES,
            )
        )

        # ======================================================
        # DeepSeek
        # ======================================================

        if normalized_provider == "deepseek":

            if not settings.is_deepseek_configured():
                raise RuntimeError(
                    "DeepSeek is not configured"
                )

            client = DeepSeekClient(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=normalized_model,
                timeout=timeout,
                max_retries=max_retries,
            )

            return DeepSeekProvider(
                client
            )

        # ======================================================
        # OpenAI
        # ======================================================

        if normalized_provider == "openai":

            if not settings.is_openai_configured():
                raise RuntimeError(
                    "OpenAI is not configured"
                )

            client = OpenAIClient(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=normalized_model,
                timeout=timeout,
                max_retries=max_retries,
            )

            return OpenAIProvider(
                client
            )

        # ======================================================
        # Qwen Classifier
        # ======================================================

        if normalized_provider == "qwen_classifier":

            if not settings.is_qwen_classifier_configured():
                raise RuntimeError(
                    "Qwen Classifier is not configured"
                )

            client = QwenClassifierClient(
                api_key=(
                    settings.qwen_classifier_api_key
                ),
                base_url=(
                    settings.qwen_classifier_base_url
                ),
                model=normalized_model,
                timeout=timeout,
                max_retries=max_retries,
            )

            return QwenClassifierProvider(
                client
            )

        # ======================================================
        # Qwen Image
        # ======================================================

        if normalized_provider == "qwen_image":

            if not settings.is_qwen_image_configured():
                raise RuntimeError(
                    "Qwen Image is not configured"
                )

            client = QwenImageClient(
                api_key=settings.qwen_image_api_key,
                base_url=settings.qwen_image_base_url,
                model=normalized_model,
                timeout=max(
                    timeout,
                    180.0,
                ),
            )

            return QwenImageProvider(
                client
            )

        # ======================================================
        # User-defined OpenAI-compatible provider
        # ======================================================

        custom = custom_provider_config.get(
            normalized_provider
        )

        if custom is not None:
            if not custom.get("enabled", True):
                raise RuntimeError(
                    f"Provider '{normalized_provider}' is disabled"
                )

            model_config = custom_provider_config.get_model(
                normalized_provider,
                normalized_model,
            )

            if model_config is None:
                raise ValueError(
                    f"Model '{normalized_model}' is not configured for "
                    f"provider '{normalized_provider}'"
                )

            api_key_env = str(
                custom.get("api_key_env", "")
            ).strip()

            import os
            api_key = os.getenv(api_key_env)

            if not api_key:
                raise RuntimeError(
                    f"Provider '{normalized_provider}' is not configured: "
                    f"environment variable {api_key_env} is missing"
                )

            client = GenericOpenAICompatibleClient(
                provider_name=normalized_provider,
                api_key=api_key,
                base_url=str(custom["base_url"]),
                model=normalized_model,
                timeout=timeout,
                max_retries=max_retries,
            )

            return GenericOpenAICompatibleProvider(
                client,
                provider_name=normalized_provider,
            )

        # ======================================================
        # Explicit document rejection
        # ======================================================

        if normalized_provider == "qwen_document":

            raise ValueError(
                "qwen_document is intentionally "
                "unsupported. This project does not "
                "use a dedicated document model/provider."
            )

        # ======================================================
        # Unsupported
        # ======================================================

        raise ValueError(
            f"Unsupported provider: "
            f"{normalized_provider}"
        )


__all__ = [
    "ProviderFactory",
]
