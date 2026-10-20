from __future__ import annotations

from app.routing.capability_registry import ModelCapability
from app.routing.schemas import RequestProfile


class CapabilityMatcher:
    """
    Pure capability utility.
    """

    @staticmethod
    def task_fit(
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

        strength = {
            "coding": model.coding_strength,
            "reasoning": model.reasoning_strength,
            "analysis": model.analysis_strength,
            "factual": model.factual_strength,
            "creative": model.creative_strength,
            "data": model.data_strength,
        }

        total = sum(
            demand.values()
        )

        if total <= 0:
            return model.factual_strength

        return sum(
            demand[name] * strength[name]
            for name in demand
        ) / total


__all__ = ["CapabilityMatcher"]
