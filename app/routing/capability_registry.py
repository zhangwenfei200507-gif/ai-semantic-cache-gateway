from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.config.providers import custom_provider_config


@dataclass(frozen=True, slots=True)
class ModelCapability:

    provider: str
    model: str

    # ==========================================================
    # Core strengths
    # ==========================================================

    reasoning_strength: float
    coding_strength: float
    analysis_strength: float
    factual_strength: float
    creative_strength: float
    data_strength: float

    # ==========================================================
    # Language / context
    # ==========================================================

    chinese_strength: float
    multilingual_strength: float
    long_context_strength: float

    # ==========================================================
    # Request capabilities
    # ==========================================================

    text_capable: bool = True
    image_capable: bool = False

    # ==========================================================
    # Semantic descriptions
    # ==========================================================

    capability_descriptions: dict[str, str] = field(
        default_factory=dict
    )

    # ==========================================================
    # Operational metadata
    # ==========================================================

    max_output_tokens: int = 2048
    enabled: bool = True
    routing_role: str = "balanced"

    def __post_init__(self) -> None:

        if not self.provider.strip():
            raise ValueError(
                "provider cannot be empty"
            )

        if not self.model.strip():
            raise ValueError(
                "model cannot be empty"
            )

        for name in (
            "reasoning_strength",
            "coding_strength",
            "analysis_strength",
            "factual_strength",
            "creative_strength",
            "data_strength",
            "chinese_strength",
            "multilingual_strength",
            "long_context_strength",
        ):

            value = float(
                getattr(
                    self,
                    name,
                )
            )

            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if self.max_output_tokens <= 0:
            raise ValueError(
                "max_output_tokens must be positive"
            )

        if self.routing_role not in {
            "economy",
            "quality",
            "balanced",
        }:
            raise ValueError(
                "routing_role must be "
                "economy, quality or balanced"
            )

    @property
    def routing_description(self) -> str:

        parts = [
            str(value).strip()
            for value
            in self.capability_descriptions.values()
            if str(value).strip()
        ]

        if not parts:
            return (
                f"{self.provider}/{self.model}"
            )

        return "; ".join(
            parts[:4]
        )


class CapabilityRegistry:
    """
    Model capability knowledge base.

    Final-answer models:

        DeepSeek
            Text generation.

        OpenAI
            Text generation / quality fallback.

        Qwen Image
            Image generation / image-related processing.

    Request classifier:

        Qwen Classifier
            Used only by the classification layer.
            It is intentionally NOT registered as a final-answer
            routing candidate.

    Intentionally NOT supported:

        qwen_document

    There is no dedicated document model/provider in this project.
    """

    def __init__(
        self,
        settings: Any | None = None,
        models: list[ModelCapability] | None = None,
    ) -> None:

        self.settings = settings

        self._models = list(models) if models is not None else self._build_models()

    # ==========================================================
    # Configuration detection
    # ==========================================================

    def _configured(
        self,
        provider: str,
    ) -> bool:

        if self.settings is None:
            return True

        method = getattr(
            self.settings,
            f"is_{provider}_configured",
            None,
        )

        if callable(method):

            try:
                return bool(
                    method()
                )

            except Exception:
                pass

        key = getattr(
            self.settings,
            f"{provider}_api_key",
            None,
        )

        if key is not None:
            return bool(
                str(key).strip()
            )

        return True

    # ==========================================================
    # Model name
    # ==========================================================

    def _model_name(
        self,
        provider: str,
        default: str,
    ) -> str:

        if self.settings is None:
            return default

        value = getattr(
            self.settings,
            f"{provider}_model",
            None,
        )

        if value:
            return str(value)

        return default

    # ==========================================================
    # Build final-answer model knowledge
    # ==========================================================

    def _build_models(
        self,
    ) -> list[ModelCapability]:

        models: list[
            ModelCapability
        ] = []

        # ======================================================
        # DeepSeek
        #
        # Economy text model.
        # ======================================================

        if self._configured(
            "deepseek"
        ):

            models.append(
                ModelCapability(

                    provider="deepseek",

                    model=self._model_name(
                        "deepseek",
                        "deepseek-chat",
                    ),

                    reasoning_strength=0.84,

                    coding_strength=0.86,

                    analysis_strength=0.87,

                    factual_strength=0.89,

                    creative_strength=0.76,

                    data_strength=0.81,

                    chinese_strength=0.98,

                    multilingual_strength=0.91,

                    long_context_strength=0.88,

                    text_capable=True,

                    image_capable=False,

                    max_output_tokens=8192,

                    routing_role="economy",

                    capability_descriptions={

                        "general":
                            "general assistance, everyday questions "
                            "and broad user support",

                        "factual":
                            "direct factual questions, explanations "
                            "and knowledge-oriented requests",

                        "analysis":
                            "business analysis, trends, markets, "
                            "strategic evaluation and causal assessment",

                        "reasoning":
                            "logical reasoning, multi-step reasoning, "
                            "deduction and difficult problem solving",

                        "coding":
                            "programming, software engineering, "
                            "databases, backend systems, APIs, "
                            "debugging and architecture",

                        "chinese_context":
                            "Chinese language, China-related context, "
                            "Chinese business and technology",

                        "data":
                            "data analysis, statistics, metrics and "
                            "quantitative reasoning",
                    },
                )
            )

        # ======================================================
        # OpenAI
        #
        # Quality text fallback.
        # ======================================================

        if self._configured(
            "openai"
        ):

            models.append(
                ModelCapability(

                    provider="openai",

                    model=self._model_name(
                        "openai",
                        "gpt-5-nano",
                    ),

                    reasoning_strength=0.96,

                    coding_strength=0.96,

                    analysis_strength=0.96,

                    factual_strength=0.95,

                    creative_strength=0.88,

                    data_strength=0.93,

                    chinese_strength=0.88,

                    multilingual_strength=0.97,

                    long_context_strength=0.95,

                    text_capable=True,

                    image_capable=False,

                    max_output_tokens=8192,

                    routing_role="quality",

                    capability_descriptions={

                        "general":
                            "general assistance, factual knowledge "
                            "and broad user support",

                        "factual":
                            "high-quality factual explanations "
                            "and knowledge tasks",

                        "analysis":
                            "complex analysis, strategic evaluation, "
                            "comparison and decision support",

                        "reasoning":
                            "deep logical reasoning, multi-step deduction, "
                            "complex problem solving and inference",

                        "coding":
                            "advanced programming, software engineering, "
                            "debugging, architecture, concurrency and APIs",

                        "multilingual":
                            "Chinese language and multilingual understanding",

                        "data":
                            "advanced data analysis, statistics, "
                            "metrics and quantitative reasoning",
                    },
                )
            )

        # ======================================================
        # Qwen Image
        #
        # Image model.
        #
        # IMPORTANT:
        # It remains in the final-answer registry because the
        # gateway/router can explicitly select image-capable
        # models.
        #
        # It must NOT be treated as a normal text model.
        # ======================================================

        if self._configured(
            "qwen_image"
        ):

            models.append(
                ModelCapability(

                    provider="qwen_image",

                    model=self._model_name(
                        "qwen_image",
                        "qwen-image-3.0",
                    ),

                    reasoning_strength=0.20,

                    coding_strength=0.05,

                    analysis_strength=0.15,

                    factual_strength=0.20,

                    creative_strength=0.99,

                    data_strength=0.05,

                    chinese_strength=0.90,

                    multilingual_strength=0.80,

                    long_context_strength=0.50,

                    text_capable=False,

                    image_capable=True,

                    max_output_tokens=4096,

                    routing_role="quality",

                    capability_descriptions={

                        "image":
                            "image generation and image-related processing",

                        "creative":
                            "visual creativity, image composition and "
                            "creative visual generation",

                        "chinese":
                            "Chinese visual prompt understanding",
                    },
                )
            )

        # ======================================================
        # User-defined OpenAI-compatible text providers
        # ======================================================

        for provider in custom_provider_config.all():
            if not provider.get("enabled", True):
                continue

            for model in provider.get("models", []):
                model_name = str(model.get("name", "")).strip()
                if not model_name:
                    continue

                def strength(name: str, default: float = 0.80) -> float:
                    try:
                        return max(0.0, min(1.0, float(model.get(name, default))))
                    except (TypeError, ValueError):
                        return default

                descriptions: dict[str, str] = {}
                capability_names = model.get("capabilities", [])
                description_map = {
                    "general": "general assistance and everyday questions",
                    "factual": "factual questions and explanations",
                    "analysis": "analysis, comparison, evaluation and strategy",
                    "reasoning": "logical reasoning and multi-step problem solving",
                    "coding": "programming, software engineering, debugging and APIs",
                    "creative": "creative writing, brainstorming and imaginative content",
                    "data": "data analysis, statistics and quantitative reasoning",
                    "chinese_context": "Chinese language and China-related context",
                    "software_engineering": "software engineering, programming, backend systems and architecture",
                    "finance": "finance, investment and financial analysis",
                    "data_analytics": "data analytics, statistics, datasets and metrics",
                }
                if isinstance(capability_names, list):
                    for capability in capability_names:
                        key = str(capability).strip().lower()
                        if key in description_map:
                            descriptions[key] = description_map[key]

                if not descriptions:
                    descriptions = {
                        "general": "general assistance and everyday questions",
                        "factual": "factual questions and explanations",
                        "reasoning": "logical reasoning and multi-step problem solving",
                        "coding": "programming, software engineering and APIs",
                        "analysis": "analysis, comparison, evaluation and strategy",
                    }

                models.append(
                    ModelCapability(
                        provider=str(provider["name"]),
                        model=model_name,
                        reasoning_strength=strength("reasoning_strength"),
                        coding_strength=strength("coding_strength"),
                        analysis_strength=strength("analysis_strength"),
                        factual_strength=strength("factual_strength"),
                        creative_strength=strength("creative_strength"),
                        data_strength=strength("data_strength"),
                        chinese_strength=strength("chinese_strength"),
                        multilingual_strength=strength("multilingual_strength", 0.90),
                        long_context_strength=strength("long_context_strength"),
                        text_capable=bool(model.get("text_capable", True)),
                        image_capable=False,
                        capability_descriptions=descriptions,
                        max_output_tokens=max(1, int(model.get("max_output_tokens", 8192))),
                        enabled=True,
                        routing_role=str(model.get("routing_role", "balanced")).lower(),
                    )
                )

        # Built-in providers share one endpoint and credentials, so every
        # configured model name is routable without duplicating capability data.
        for provider in ("deepseek", "openai", "qwen_image"):
            names = getattr(self.settings, "model_names", lambda _name: [])(provider)
            primary = next((item for item in models if item.provider == provider), None)
            if primary is None:
                continue
            for model_name in names:
                if model_name != primary.model and not any(
                    item.provider == provider and item.model == model_name
                    for item in models
                ):
                    models.append(replace(primary, model=model_name))

        return models

    # ==========================================================
    # Public API
    # ==========================================================

    def configured(
        self,
    ) -> list[ModelCapability]:
        """
        Return all enabled final-answer models.

        This includes text and image models.

        It intentionally does NOT include:

            qwen_classifier
            qwen_document
        """

        return [
            model
            for model
            in self._models
            if model.enabled
        ]

    def text_models(
        self,
    ) -> list[ModelCapability]:
        """
        Return only models capable of text generation.
        """

        return [
            model
            for model
            in self.configured()
            if model.text_capable
        ]

    def image_models(
        self,
    ) -> list[ModelCapability]:
        """
        Return only image-capable models.
        """

        return [
            model
            for model
            in self.configured()
            if model.image_capable
        ]

    def get(
        self,
        provider: str,
        model: str,
    ) -> ModelCapability | None:
        """
        Find an exact provider/model combination.
        """

        normalized_provider = (
            str(provider or "")
            .strip()
            .lower()
        )

        normalized_model = (
            str(model or "")
            .strip()
            .lower()
        )

        for item in self._models:

            if (
                item.provider.lower()
                ==
                normalized_provider
                and
                item.model.lower()
                ==
                normalized_model
            ):
                return item

        return None

    def refresh(self) -> None:
        """
        Rebuild the registry from current settings.
        """

        self._models = (
            self._build_models()
        )


# ==============================================================
# Global registry
# ==============================================================

try:

    from app.config.settings import (
        settings as _settings,
    )

except Exception:

    _settings = None


capability_registry = (
    CapabilityRegistry(
        _settings
    )
)


__all__ = [
    "ModelCapability",
    "CapabilityRegistry",
    "capability_registry",
]
