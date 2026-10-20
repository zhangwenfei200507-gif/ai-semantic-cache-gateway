from __future__ import annotations

from app.routing.capability_registry import (
    CapabilityRegistry,
    capability_registry,
)
from app.routing.cost_estimator import CostEstimator
from app.routing.encoder import SemanticEncoder
from app.routing.performance import (
    PerformanceTracker,
    performance_tracker,
)
from app.routing.ranking import RankingEngine
from app.routing.modality_router import ModalityRouter
from app.routing.request_profiler import RequestProfiler
from app.routing.schemas import ModelScore, RoutingDecision


class ModelRouter:
    """
    Production automatic router.

    Pipeline:

        request
          -> profile
          -> candidate discovery
          -> capability matching
          -> quality floor
          -> cost / latency / reliability
          -> selected model
          -> fallback candidates
    """

    LOW_CONFIDENCE = 0.45
    HIGH_CONFIDENCE = 0.78

    def __init__(
        self,
        embedding_service,
        registry: CapabilityRegistry | None = None,
        performance: PerformanceTracker | None = None,
        cost_estimator: CostEstimator | None = None,
    ) -> None:

        self.embedding_service = embedding_service

        self.registry = (
            registry
            or
            capability_registry
        )

        self.encoder = SemanticEncoder(
            embedding_service
        )

        self.profiler = RequestProfiler(
            self.encoder
        )

        # First-stage modality routing. Qwen3.8-Flash only decides
        # text vs image; it never answers the user request.
        self.modality_router = ModalityRouter()

        self.performance = (
            performance
            or
            performance_tracker
        )

        self.cost_estimator = (
            cost_estimator
            or
            CostEstimator()
        )

        self.ranking = RankingEngine(
            self.encoder,
            self.performance,
            self.cost_estimator,
        )

    @classmethod
    def _confidence(
        cls,
        candidates,
        profile,
    ) -> tuple[float, str]:

        available = [
            item
            for item
            in candidates
            if item.available
        ]

        if not available:
            return 0.0, "low"

        if len(available) == 1:

            understanding = (
                profile.task_confidence * 0.50
                +
                profile.domain_confidence * 0.50
            )

            confidence = (
                0.78
                +
                understanding * 0.22
            )

            return (
                round(
                    min(
                        1.0,
                        confidence,
                    ),
                    4,
                ),
                "high",
            )

        first = float(
            available[0].final_score
        )

        second = float(
            available[1].final_score
        )

        margin = max(
            0.0,
            first - second,
        )

        separation = max(
            0.0,
            min(
                1.0,
                margin / 0.10,
            ),
        )

        understanding = (
            profile.task_confidence * 0.50
            +
            profile.domain_confidence * 0.50
        )

        confidence = (
            first * 0.30
            +
            separation * 0.45
            +
            understanding * 0.25
        )

        if confidence >= cls.HIGH_CONFIDENCE:
            level = "high"
        elif confidence >= cls.LOW_CONFIDENCE:
            level = "medium"
        else:
            level = "low"

        return (
            round(
                max(
                    0.0,
                    min(
                        1.0,
                        confidence,
                    ),
                ),
                4,
            ),
            level,
        )

    @staticmethod
    def _decision_reasons(
        profile,
        selected,
        confidence_level,
    ) -> list[str]:

        reasons = list(
            selected.reasons
        )

        if profile.domain == "china_context":
            reasons.append(
                "China-context specialization evaluated"
            )

        if profile.domain == "software_engineering":
            reasons.append(
                "software-engineering specialization evaluated"
            )

        if profile.coding_score >= 0.70:
            reasons.append(
                "strong coding demand detected"
            )

        if profile.reasoning_score >= 0.70:
            reasons.append(
                "strong reasoning demand detected"
            )

        if profile.analysis_score >= 0.70:
            reasons.append(
                "strong analysis demand detected"
            )

        if profile.complexity == "complex":
            reasons.append(
                "quality prioritized for complex request"
            )

        elif profile.complexity == "medium":
            reasons.append(
                "balanced quality-cost optimization applied"
            )

        else:
            reasons.append(
                "cost and latency optimization allowed for simple request"
            )

        if confidence_level == "high":
            reasons.append(
                "high-confidence routing decision"
            )

        elif confidence_level == "medium":
            reasons.append(
                "medium-confidence routing decision"
            )

        else:
            reasons.append(
                "low-confidence routing decision"
            )

        unique = []
        seen = set()

        for reason in reasons:

            if reason in seen:
                continue

            seen.add(
                reason
            )

            unique.append(
                reason
            )

        return unique

    def route(
        self,
        messages: list[dict],
        registry: CapabilityRegistry | None = None,
        modality_router: ModalityRouter | None = None,
    ) -> RoutingDecision:

        # --------------------------------------------------------
        # Stage 1: modality routing
        #
        # Qwen3.8-Flash determines whether the request is text or
        # image. Image requests bypass text-model ranking entirely.
        # --------------------------------------------------------
        active_modality_router = modality_router or self.modality_router
        active_registry = registry or self.registry
        modality = active_modality_router.route(
            messages
        )

        profile = self.profiler.profile(
            messages
        )

        if modality.modality == "image":
            image_model = None

            for item in active_registry.image_models():
                image_model = item
                break

            if image_model is None:
                raise RuntimeError(
                    "No configured image model available"
                )

            image_score = ModelScore(
                provider=image_model.provider,
                model=image_model.model,
                available=True,
                semantic_score=1.0,
                task_score=1.0,
                domain_score=1.0,
                language_score=profile.chinese_ratio if profile.language == "zh" else 1.0,
                complexity_score=1.0,
                cost_score=1.0,
                latency_score=1.0,
                reliability_score=1.0,
                quality_score=1.0,
                final_score=1.0,
                estimated_input_tokens=profile.estimated_input_tokens,
                estimated_output_tokens=0,
                estimated_cost=0.0,
                reasons=[
                    modality.reason or "Image-generation intent detected",
                    "image-capable model selected",
                ],
            )

            reasons = [
                "Image modality classification",
                modality.reason or "image request detected",
                f"classifier confidence: {modality.confidence:.4f}",
                "image-capable route selected",
            ]

            return RoutingDecision(
                provider=image_model.provider,
                model=image_model.model,
                score=1.0,
                confidence=modality.confidence,
                confidence_level=(
                    "high" if modality.confidence >= 0.78
                    else "medium" if modality.confidence >= 0.45
                    else "low"
                ),
                mode="auto",
                reasons=reasons,
                request_profile=profile,
                candidates=[image_score],
                fallback_candidates=[],
            )

        models = active_registry.configured()

        if not models:
            raise RuntimeError(
                "No configured models available"
            )

        candidates = (
            self.ranking.score_many(
                models,
                profile,
            )
        )

        if not candidates:
            raise RuntimeError(
                "No model candidates available"
            )

        available = [
            item
            for item
            in candidates
            if item.available
        ]

        if not available:
            raise RuntimeError(
                "No available model candidates"
            )

        selected = available[0]

        (
            confidence,
            confidence_level,
        ) = self._confidence(
            available,
            profile,
        )

        fallback = available[1:]

        return RoutingDecision(
            provider=
                selected.provider,
            model=
                selected.model,
            score=
                selected.final_score,
            confidence=
                confidence,
            confidence_level=
                confidence_level,
            mode=
                "auto",
            reasons=
                self._decision_reasons(
                    profile,
                    selected,
                    confidence_level,
                ),
            request_profile=
                profile,
            candidates=
                candidates,
            fallback_candidates=
                fallback,
        )

    def route_to_dict(
        self,
        messages: list[dict],
        registry: CapabilityRegistry | None = None,
        modality_router: ModalityRouter | None = None,
    ) -> dict:
        return self.route(
            messages,
            registry=registry,
            modality_router=modality_router,
        ).to_dict()

    def route_manual(
        self,
        requested_model: str,
        messages: list[dict],
        registry: CapabilityRegistry | None = None,
    ) -> RoutingDecision:

        normalized = (
            str(
                requested_model
                or
                ""
            )
            .strip()
            .lower()
        )

        if not normalized:
            raise ValueError(
                "requested_model cannot be empty"
            )

        profile = self.profiler.profile(
            messages
        )

        models = (registry or self.registry).configured()

        if not models:
            raise RuntimeError(
                "No configured models available"
            )

        selected_model = None

        for model in models:

            names = {
                model.model.lower(),
                model.provider.lower(),
                f"{model.provider}/{model.model}".lower(),
            }

            if normalized in names:
                selected_model = model
                break

        if selected_model is None:
            raise ValueError(
                f"Unsupported model {requested_model}"
            )

        # Image models are intentionally excluded from normal text scoring.
        # A user-selected image model must still be a valid manual route.
        if selected_model.image_capable and not selected_model.text_capable:
            image_score = ModelScore(
                provider=selected_model.provider,
                model=selected_model.model,
                available=True,
                semantic_score=1.0,
                task_score=1.0,
                domain_score=1.0,
                language_score=1.0,
                complexity_score=1.0,
                cost_score=1.0,
                latency_score=1.0,
                reliability_score=1.0,
                quality_score=1.0,
                final_score=1.0,
                estimated_input_tokens=profile.estimated_input_tokens,
                estimated_output_tokens=0,
                estimated_cost=0.0,
                reasons=[
                    "manual image model requested",
                    "image-capable model selected",
                ],
            )
            return RoutingDecision(
                provider=selected_model.provider,
                model=selected_model.model,
                score=1.0,
                confidence=1.0,
                confidence_level="high",
                mode="manual",
                reasons=image_score.reasons,
                request_profile=profile,
                candidates=[image_score],
                fallback_candidates=[],
            )

        scored = (
            self.ranking.score_many(
                models,
                profile,
            )
        )

        if not scored:
            raise RuntimeError(
                "No model candidates available"
            )

        selected = None
        fallback = []

        for candidate in scored:

            if (
                candidate.provider
                ==
                selected_model.provider
                and
                candidate.model
                ==
                selected_model.model
            ):
                selected = candidate
                continue

            if candidate.available:
                fallback.append(
                    candidate
                )

        if selected is None:
            raise RuntimeError(
                "Requested model is not available"
            )

        candidates = [
            selected,
            *fallback,
        ]

        reasons = [
            "manual model requested",
            *selected.reasons,
        ]

        return RoutingDecision(
            provider=
                selected.provider,
            model=
                selected.model,
            score=
                selected.final_score,
            confidence=
                1.0,
            confidence_level=
                "high",
            mode=
                "manual",
            reasons=
                reasons,
            request_profile=
                profile,
            candidates=
                candidates,
            fallback_candidates=
                fallback,
        )


class _LazyModelRouter:
    """
    Existing compatibility API:

        from app.routing.model_router import model_router

    Reuses the Gateway-owned router and therefore does not construct
    a duplicate embedding service.
    """

    def route(
        self,
        messages: list[dict],
    ) -> RoutingDecision:

        from app.gateway import get_gateway

        gateway = get_gateway()

        router = getattr(
            gateway,
            "model_router",
            None,
        )

        if router is None:
            raise RuntimeError(
                "Gateway does not expose model_router"
            )

        return router.route(
            messages
        )

    def route_to_dict(
        self,
        messages: list[dict],
    ) -> dict:
        return self.route(
            messages
        ).to_dict()

    def __getattr__(
        self,
        name: str,
    ):
        from app.gateway import get_gateway

        gateway = get_gateway()

        router = getattr(
            gateway,
            "model_router",
            None,
        )

        if router is None:
            raise AttributeError(
                f"Gateway does not expose model_router.{name}"
            )

        return getattr(
            router,
            name,
        )


model_router = _LazyModelRouter()


def create_model_router(
    embedding_service,
    registry: CapabilityRegistry | None = None,
    performance: PerformanceTracker | None = None,
    cost_estimator: CostEstimator | None = None,
) -> ModelRouter:

    return ModelRouter(
        embedding_service=
            embedding_service,
        registry=
            registry,
        performance=
            performance,
        cost_estimator=
            cost_estimator,
    )


__all__ = [
    "ModelRouter",
    "model_router",
    "create_model_router",
]
