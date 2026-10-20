from __future__ import annotations

from app.routing.schemas import ModelScore


class UtilityRanker:
    """
    Final deterministic ordering helper.
    """

    @staticmethod
    def sort(
        candidates: list[ModelScore],
    ) -> list[ModelScore]:

        return sorted(
            candidates,
            key=lambda item: (
                item.final_score,
                item.quality_score,
                item.reliability_score,
                -item.estimated_cost,
            ),
            reverse=True,
        )


__all__ = ["UtilityRanker"]
