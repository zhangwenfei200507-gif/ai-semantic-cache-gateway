from __future__ import annotations

import math
from typing import Any

from app.routing.capability_registry import ModelCapability
from app.routing.cost_estimator import CostEstimator
from app.routing.encoder import SemanticEncoder
from app.routing.performance import PerformanceTracker
from app.routing.schemas import ModelScore, RequestProfile


class RankingEngine:
    """
    Quality-first model ranking engine.

    Routing principles:

    1. Quality is the primary routing factor.
    2. Cost only optimizes between models with sufficiently
       similar quality.
    3. A materially weaker model cannot win only because it is cheaper.
    4. Complex coding/reasoning/analysis requests strongly prefer quality.
    5. Simple text requests can favor economical models.
    6. Image models must not be used as normal text models.
    7. No document model is supported.
    """

    # A model must be within this quality gap from the best model
    # before cost is allowed to materially influence ranking.
    QUALITY_FLOOR_GAP = 0.035

    def __init__(
        self,
        encoder: SemanticEncoder,
        performance: PerformanceTracker,
        cost_estimator: CostEstimator,
    ) -> None:

        self.encoder = encoder
        self.performance = performance
        self.cost_estimator = cost_estimator

        self._capability_embeddings: dict[
            tuple[str, str],
            dict[str, list[float]],
        ] = {}

    # ============================================================
    # Semantic capability embeddings
    # ============================================================

    def _capability_embeddings_for(
        self,
        model: ModelCapability,
    ) -> dict[str, list[float]]:

        key = (
            model.provider,
            model.model,
        )

        cached = self._capability_embeddings.get(key)

        if cached is not None:
            return cached

        cached = {
            name: self.encoder.encode(description)
            for name, description
            in model.capability_descriptions.items()
        }

        self._capability_embeddings[key] = cached

        return cached

    def _semantic_capability_scores(
        self,
        model: ModelCapability,
        query_embedding: list[float],
    ) -> dict[str, float]:

        embeddings = self._capability_embeddings_for(model)

        result: dict[str, float] = {}

        for capability, vector in embeddings.items():

            similarity = self.encoder.cosine(
                query_embedding,
                vector,
            )

            result[capability] = (
                self.encoder.normalize_similarity(
                    similarity
                )
            )

        return result

    # ============================================================
    # Task score
    # ============================================================

    @staticmethod
    def _task_score(
        model: ModelCapability,
        profile: RequestProfile,
    ) -> float:

        demand = {
            "coding": profile.coding_score,
            "reasoning": profile.reasoning_score,
            "analysis": profile.analysis_score,
            "factual": profile.factual_score,
            "creative": profile.creative_score,
            "data": profile.data_score,
        }

        capability = {
            "coding": model.coding_strength,
            "reasoning": model.reasoning_strength,
            "analysis": model.analysis_strength,
            "factual": model.factual_strength,
            "creative": model.creative_strength,
            "data": model.data_strength,
        }

        total = sum(demand.values())

        if total <= 0.0:
            return model.factual_strength

        score = (
            sum(
                demand[name] * capability[name]
                for name in demand
            )
            / total
        )

        return max(
            0.0,
            min(
                1.0,
                score,
            ),
        )

    # ============================================================
    # Domain score
    # ============================================================

    @staticmethod
    def _domain_score(
        model: ModelCapability,
        profile: RequestProfile,
        semantic: dict[str, float],
    ) -> float:

        if profile.domain == "china_context":

            return max(
                0.0,
                min(
                    1.0,
                    semantic.get(
                        "chinese_context",
                        0.50,
                    ) * 0.55
                    + model.chinese_strength * 0.45,
                ),
            )

        if profile.domain == "software_engineering":

            engineering = max(
                model.coding_strength,
                model.reasoning_strength,
                model.long_context_strength,
            )

            return max(
                0.0,
                min(
                    1.0,
                    semantic.get(
                        "software_engineering",
                        0.50,
                    ) * 0.55
                    + engineering * 0.45,
                ),
            )

        if profile.domain == "business_market":

            return max(
                0.0,
                min(
                    1.0,
                    semantic.get(
                        "analysis",
                        0.50,
                    ) * 0.60
                    + model.analysis_strength * 0.40,
                ),
            )

        if profile.domain == "finance":

            return max(
                0.0,
                min(
                    1.0,
                    model.analysis_strength * 0.55
                    + model.data_strength * 0.45,
                ),
            )

        if profile.domain == "data_analytics":

            return max(
                0.0,
                min(
                    1.0,
                    model.data_strength * 0.65
                    + model.analysis_strength * 0.35,
                ),
            )

        if profile.domain == "science_math":

            return max(
                0.0,
                min(
                    1.0,
                    model.reasoning_strength * 0.65
                    + model.data_strength * 0.35,
                ),
            )

        return max(
            0.0,
            min(
                1.0,
                model.multilingual_strength * 0.65
                + model.factual_strength * 0.35,
            ),
        )

    # ============================================================
    # Language score
    # ============================================================

    @staticmethod
    def _language_score(
        model: ModelCapability,
        profile: RequestProfile,
    ) -> float:

        if profile.language == "zh":
            return model.chinese_strength

        return model.multilingual_strength

    # ============================================================
    # Complexity score
    # ============================================================

    @staticmethod
    def _complexity_score(
        model: ModelCapability,
        profile: RequestProfile,
    ) -> float:

        if profile.complexity == "complex":

            return max(
                0.0,
                min(
                    1.0,
                    model.reasoning_strength * 0.30
                    + model.coding_strength * 0.25
                    + model.analysis_strength * 0.20
                    + model.long_context_strength * 0.15
                    + model.data_strength * 0.10,
                ),
            )

        if profile.complexity == "medium":

            return max(
                0.0,
                min(
                    1.0,
                    model.reasoning_strength * 0.25
                    + model.analysis_strength * 0.23
                    + model.coding_strength * 0.15
                    + model.factual_strength * 0.15
                    + model.long_context_strength * 0.12
                    + model.multilingual_strength * 0.10,
                ),
            )

        return max(
            0.0,
            min(
                1.0,
                model.factual_strength * 0.40
                + model.multilingual_strength * 0.30
                + model.reasoning_strength * 0.10
                + model.analysis_strength * 0.10
                + model.chinese_strength * 0.10,
            ),
        )

    # ============================================================
    # Semantic score
    # ============================================================

    @staticmethod
    def _semantic_score(
        profile: RequestProfile,
        semantic: dict[str, float],
    ) -> float:

        values: list[float] = []

        if profile.domain == "china_context":

            values.append(
                semantic.get(
                    "chinese_context",
                    0.50,
                )
            )

        if profile.domain == "software_engineering":

            values.append(
                semantic.get(
                    "software_engineering",
                    0.50,
                )
            )

        if profile.analysis_score >= 0.50:

            values.append(
                semantic.get(
                    "analysis",
                    0.50,
                )
            )

        if profile.reasoning_score >= 0.50:

            values.append(
                semantic.get(
                    "reasoning",
                    0.50,
                )
            )

        if not values:

            values.append(
                semantic.get(
                    "general",
                    0.50,
                )
            )

        values.sort(reverse=True)

        if len(values) == 1:
            return values[0]

        return (
            values[0] * 0.65
            + values[1] * 0.35
        )

    # ============================================================
    # Quality score
    # ============================================================

    @staticmethod
    def _quality_score(
        profile: RequestProfile,
        semantic_score: float,
        task_score: float,
        domain_score: float,
        language_score: float,
        complexity_score: float,
    ) -> float:

        if (
            profile.complexity == "complex"
            or profile.coding_score >= 0.65
            or profile.reasoning_score >= 0.70
        ):

            value = (
                task_score * 0.37
                + domain_score * 0.29
                + complexity_score * 0.19
                + semantic_score * 0.12
                + language_score * 0.03
            )

        elif (
            profile.analysis_score >= 0.55
            or profile.domain != "general"
        ):

            value = (
                domain_score * 0.35
                + task_score * 0.30
                + semantic_score * 0.20
                + complexity_score * 0.10
                + language_score * 0.05
            )

        else:

            value = (
                task_score * 0.30
                + semantic_score * 0.28
                + domain_score * 0.18
                + language_score * 0.12
                + complexity_score * 0.12
            )

        return max(
            0.0,
            min(
                1.0,
                value,
            ),
        )

    # ============================================================
    # Dynamic weights
    # ============================================================

    @staticmethod
    def _weights(
        profile: RequestProfile,
    ) -> dict[str, float]:

        if profile.complexity == "complex":

            weights = {
                "quality": 0.79,
                "semantic": 0.08,
                "language": 0.03,
                "cost": 0.025,
                "latency": 0.025,
                "reliability": 0.055,
            }

        elif profile.complexity == "medium":

            weights = {
                "quality": 0.70,
                "semantic": 0.08,
                "language": 0.05,
                "cost": 0.07,
                "latency": 0.04,
                "reliability": 0.06,
            }

        else:

            weights = {
                "quality": 0.57,
                "semantic": 0.07,
                "language": 0.07,
                "cost": 0.15,
                "latency": 0.08,
                "reliability": 0.06,
            }

        if profile.coding_score >= 0.70:

            weights["quality"] += 0.07
            weights["cost"] -= 0.025
            weights["latency"] -= 0.015

        if profile.reasoning_score >= 0.70:

            weights["quality"] += 0.07
            weights["cost"] -= 0.025
            weights["latency"] -= 0.015

        if profile.analysis_score >= 0.70:

            weights["quality"] += 0.05
            weights["semantic"] += 0.015
            weights["cost"] -= 0.025

        if profile.domain == "china_context":

            weights["quality"] += 0.04
            weights["language"] += 0.01
            weights["cost"] -= 0.02

        weights = {
            key: max(
                0.0,
                value,
            )
            for key, value in weights.items()
        }

        total = sum(weights.values())

        if total <= 0.0:

            return {
                key: 1.0 / len(weights)
                for key in weights
            }

        return {
            key: value / total
            for key, value in weights.items()
        }

    # ============================================================
    # Latency score
    # ============================================================

    @staticmethod
    def _latency_score(
        latency_ms: float,
    ) -> float:

        if latency_ms <= 0:
            return 0.70

        return max(
            0.0,
            min(
                1.0,
                1.0
                / (
                    1.0
                    + latency_ms / 1500.0
                ),
            ),
        )

    # ============================================================
    # Cost score
    # ============================================================

    @staticmethod
    def _cost_scores(
        rows: list[dict[str, Any]],
    ) -> dict[tuple[str, str], float]:

        costs: dict[
            tuple[str, str],
            float,
        ] = {}

        for row in rows:

            key = (
                row["provider"],
                row["model"],
            )

            costs[key] = float(
                row.get(
                    "estimated_cost",
                    0.0,
                )
                or 0.0
            )

        known = [
            value
            for value in costs.values()
            if value > 0.0
        ]

        if not known:

            return {
                key: 0.50
                for key in costs
            }

        minimum = min(known)
        maximum = max(known)

        if maximum <= minimum:

            return {
                key: 1.0
                for key in costs
            }

        denominator = max(
            1e-12,
            math.log1p(
                maximum / minimum
            ),
        )

        result: dict[
            tuple[str, str],
            float,
        ] = {}

        for key, cost in costs.items():

            if cost <= 0.0:

                result[key] = 0.50
                continue

            relative = (
                math.log1p(
                    maximum / cost
                )
                / denominator
            )

            result[key] = max(
                0.0,
                min(
                    1.0,
                    relative,
                ),
            )

        return result

    # ============================================================
    # Quality requirement
    # ============================================================

    @staticmethod
    def _quality_required(
        profile: RequestProfile,
    ) -> bool:

        if profile.complexity == "complex":
            return True

        if (
            profile.coding_score >= 0.70
            or profile.reasoning_score >= 0.68
        ):
            return True

        if (
            profile.analysis_score >= 0.62
            and profile.domain != "china_context"
        ):
            return True

        if (
            profile.domain
            in {
                "software_engineering",
                "science_math",
                "data_analytics",
                "finance",
            }
            and profile.complexity == "medium"
            and (
                profile.reasoning_score >= 0.50
                or profile.analysis_score >= 0.50
                or profile.coding_score >= 0.50
            )
        ):
            return True

        return False

    # ============================================================
    # Economy permission
    # ============================================================

    @staticmethod
    def _economy_allowed(
        profile: RequestProfile,
    ) -> bool:

        if RankingEngine._quality_required(profile):
            return False

        if profile.complexity == "simple":
            return True

        if (
            profile.language == "zh"
            and profile.domain == "china_context"
            and profile.coding_score < 0.55
            and profile.reasoning_score < 0.65
        ):
            return True

        return False

    # ============================================================
    # Role adjustment
    # ============================================================

    @staticmethod
    def _role_adjustment(
        model: ModelCapability,
        profile: RequestProfile,
    ) -> float:

        role = getattr(
            model,
            "routing_role",
            "balanced",
        )

        if role == "balanced":
            return 0.0

        quality_required = (
            RankingEngine._quality_required(
                profile
            )
        )

        economy_allowed = (
            RankingEngine._economy_allowed(
                profile
            )
        )

        adjustment = 0.0

        if role == "economy":

            if economy_allowed:
                adjustment += 0.12

            if (
                profile.language == "zh"
                and profile.domain == "china_context"
            ):
                adjustment += 0.05

            if quality_required:
                adjustment -= 0.04

        elif role == "quality":

            if quality_required:
                adjustment += 0.09

            if economy_allowed:
                adjustment -= 0.04

            if (
                profile.language == "zh"
                and profile.domain == "china_context"
                and not quality_required
            ):
                adjustment -= 0.03

        return max(
            -0.10,
            min(
                0.18,
                adjustment,
            ),
        )

    # ============================================================
    # Score models
    # ============================================================

    def score_many(
        self,
        models: list[ModelCapability],
        profile: RequestProfile,
    ) -> list[ModelScore]:

        if not models:
            return []

        # Only text-capable models participate in normal text ranking.
        # Image routing is handled by RequestRouter/Qwen Image.
        models = [
            model
            for model in models
            if model.enabled
            and model.text_capable
        ]

        if not models:
            return []

        query_embedding = self.encoder.encode(
            profile.text
        )

        weights = self._weights(profile)

        rows: list[dict[str, Any]] = []

        for model in models:

            semantic = (
                self._semantic_capability_scores(
                    model,
                    query_embedding,
                )
            )

            semantic_score = (
                self._semantic_score(
                    profile,
                    semantic,
                )
            )

            task_score = (
                self._task_score(
                    model,
                    profile,
                )
            )

            domain_score = (
                self._domain_score(
                    model,
                    profile,
                    semantic,
                )
            )

            language_score = (
                self._language_score(
                    model,
                    profile,
                )
            )

            complexity_score = (
                self._complexity_score(
                    model,
                    profile,
                )
            )

            quality_score = (
                self._quality_score(
                    profile,
                    semantic_score,
                    task_score,
                    domain_score,
                    language_score,
                    complexity_score,
                )
            )

            estimate = (
                self.cost_estimator.estimate(
                    model=model.model,
                    input_tokens=(
                        profile.estimated_input_tokens
                    ),
                    complexity=profile.complexity,
                    task=profile.task,
                )
            )

            latency = (
                self.performance.latency_ms(
                    model.provider,
                    model.model,
                )
            )

            latency_score = (
                self._latency_score(
                    latency
                )
            )

            reliability_score = (
                self.performance.reliability(
                    model.provider,
                    model.model,
                )
            )

            rows.append(
                {
                    "capability": model,
                    "provider": model.provider,
                    "model": model.model,
                    "semantic_score": semantic_score,
                    "task_score": task_score,
                    "domain_score": domain_score,
                    "language_score": language_score,
                    "complexity_score": complexity_score,
                    "quality_score": quality_score,
                    "latency_score": latency_score,
                    "reliability_score": reliability_score,
                    "estimated_input_tokens": estimate[
                        "input_tokens"
                    ],
                    "estimated_output_tokens": estimate[
                        "output_tokens"
                    ],
                    "estimated_cost": estimate[
                        "estimated_cost"
                    ],
                }
            )

        if not rows:
            return []

        cost_scores = self._cost_scores(rows)

        best_quality = max(
            row["quality_score"]
            for row in rows
        )

        results: list[ModelScore] = []

        for row in rows:

            model = row["capability"]

            key = (
                row["provider"],
                row["model"],
            )

            quality_gap = (
                best_quality
                - row["quality_score"]
            )

            if quality_gap <= self.QUALITY_FLOOR_GAP:

                effective_cost = (
                    cost_scores.get(
                        key,
                        0.50,
                    )
                )

            else:

                # Do not let a materially weaker model
                # win because of price.
                effective_cost = 0.50

            final_score = (
                row["quality_score"]
                * weights["quality"]
                + row["semantic_score"]
                * weights["semantic"]
                + row["language_score"]
                * weights["language"]
                + effective_cost
                * weights["cost"]
                + row["latency_score"]
                * weights["latency"]
                + row["reliability_score"]
                * weights["reliability"]
            )

            role_adjustment = (
                self._role_adjustment(
                    model=model,
                    profile=profile,
                )
            )

            final_score = max(
                0.0,
                min(
                    1.0,
                    final_score
                    + role_adjustment,
                ),
            )

            reasons: list[str] = []

            if row["semantic_score"] >= 0.78:

                reasons.append(
                    "strong semantic capability match"
                )

            elif row["semantic_score"] >= 0.68:

                reasons.append(
                    "good semantic capability match"
                )

            if row["task_score"] >= 0.82:

                reasons.append(
                    "strong task capability fit"
                )

            if row["domain_score"] >= 0.82:

                reasons.append(
                    "strong domain specialization fit"
                )

            if profile.coding_score >= 0.70:

                reasons.append(
                    "strong coding demand"
                )

            if profile.reasoning_score >= 0.70:

                reasons.append(
                    "strong reasoning demand"
                )

            if profile.analysis_score >= 0.70:

                reasons.append(
                    "strong analysis demand"
                )

            if (
                profile.domain == "china_context"
                and row["domain_score"] >= 0.80
            ):

                reasons.append(
                    "strong Chinese/China-context fit"
                )

            if (
                profile.domain == "software_engineering"
                and row["domain_score"] >= 0.80
            ):

                reasons.append(
                    "strong software-engineering fit"
                )

            if (
                profile.complexity == "complex"
                and row["complexity_score"] >= 0.80
            ):

                reasons.append(
                    "strong complex-task fit"
                )

            if (
                quality_gap <= self.QUALITY_FLOOR_GAP
                and effective_cost >= 0.80
            ):

                reasons.append(
                    "cost optimization active among quality peers"
                )

            if row["reliability_score"] >= 0.98:

                reasons.append(
                    "strong reliability profile"
                )

            if row["latency_score"] >= 0.80:

                reasons.append(
                    "good latency profile"
                )

            role = getattr(
                model,
                "routing_role",
                "balanced",
            )

            if (
                role == "economy"
                and role_adjustment > 0.0
            ):

                reasons.append(
                    "economy route matched request complexity"
                )

            if (
                role == "quality"
                and role_adjustment > 0.0
            ):

                reasons.append(
                    "quality route matched request complexity"
                )

            if not reasons:

                reasons.append(
                    "overall utility fit"
                )

            results.append(
                ModelScore(
                    provider=row["provider"],
                    model=row["model"],
                    available=True,
                    semantic_score=round(
                        row["semantic_score"],
                        6,
                    ),
                    task_score=round(
                        row["task_score"],
                        6,
                    ),
                    domain_score=round(
                        row["domain_score"],
                        6,
                    ),
                    language_score=round(
                        row["language_score"],
                        6,
                    ),
                    complexity_score=round(
                        row["complexity_score"],
                        6,
                    ),
                    cost_score=round(
                        cost_scores.get(
                            key,
                            0.50,
                        ),
                        6,
                    ),
                    latency_score=round(
                        row["latency_score"],
                        6,
                    ),
                    reliability_score=round(
                        row["reliability_score"],
                        6,
                    ),
                    quality_score=round(
                        row["quality_score"],
                        6,
                    ),
                    final_score=round(
                        final_score,
                        6,
                    ),
                    estimated_input_tokens=row[
                        "estimated_input_tokens"
                    ],
                    estimated_output_tokens=row[
                        "estimated_output_tokens"
                    ],
                    estimated_cost=round(
                        row["estimated_cost"],
                        10,
                    ),
                    reasons=reasons,
                )
            )

        results.sort(
            key=lambda item: (
                item.final_score,
                item.quality_score,
                item.reliability_score,
                -item.estimated_cost,
            ),
            reverse=True,
        )

        return results

    # ============================================================
    # Single model
    # ============================================================

    def score(
        self,
        model: ModelCapability,
        profile: RequestProfile,
    ) -> ModelScore:

        results = self.score_many(
            [model],
            profile,
        )

        if not results:
            raise RuntimeError(
                "Unable to score model"
            )

        return results[0]


__all__ = [
    "RankingEngine",
]