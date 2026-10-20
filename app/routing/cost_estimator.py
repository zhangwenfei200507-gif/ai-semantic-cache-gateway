from __future__ import annotations

from typing import Any


class CostEstimator:
    """
    Token/cost estimator.

    Pricing contract:
      provider/model pricing objects expose either

        input_price_per_1m / output_price_per_1m

      or the legacy

        input_price / output_price

    Legacy prices are interpreted as USD per 1K tokens.

    Unknown pricing is never treated as free.
    """

    DEFAULT_OUTPUT_TOKENS = {
        "simple": 192,
        "medium": 504,
        "complex": 1125,
    }

    def __init__(
        self,
        registry: Any | None = None,
    ) -> None:
        self.registry = registry

        if self.registry is None:
            try:
                from app.cost.cost_registry import cost_registry
                self.registry = cost_registry
            except Exception:
                self.registry = None

    def _price(self, model: str) -> tuple[float, float]:
        if self.registry is None:
            return 0.0, 0.0

        price = self.registry.get(model)

        if price is None:
            return 0.0, 0.0

        input_per_1m = getattr(
            price,
            "input_price_per_1m",
            None,
        )

        output_per_1m = getattr(
            price,
            "output_price_per_1m",
            None,
        )

        if (
            input_per_1m is not None
            and output_per_1m is not None
        ):
            return (
                float(input_per_1m),
                float(output_per_1m),
            )

        input_1k = float(
            getattr(
                price,
                "input_price",
                0.0,
            )
            or 0.0
        )

        output_1k = float(
            getattr(
                price,
                "output_price",
                0.0,
            )
            or 0.0
        )

        return (
            input_1k * 1000.0,
            output_1k * 1000.0,
        )

    def estimate(
        self,
        model: str,
        input_tokens: int,
        complexity: str = "medium",
        task: str = "general",
    ) -> dict[str, Any]:

        input_tokens = max(
            1,
            int(input_tokens),
        )

        output_tokens = self._estimate_output(
            complexity,
            task,
        )

        input_price_per_1m, output_price_per_1m = (
            self._price(model)
        )

        cost = (

            input_tokens
            *
            input_price_per_1m
            /
            1_000_000.0

            +

            output_tokens
            *
            output_price_per_1m
            /
            1_000_000.0

        )

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": round(
                cost,
                10,
            ),
        }

    def _estimate_output(
        self,
        complexity: str,
        task: str,
    ) -> int:

        base = int(
            self.DEFAULT_OUTPUT_TOKENS.get(
                complexity,
                self.DEFAULT_OUTPUT_TOKENS["medium"],
            )
        )

        if task in {
            "reasoning",
            "coding",
            "analysis",
            "data",
        }:
            base = int(
                base * 1.15
            )

        return max(
            64,
            base,
        )


__all__ = ["CostEstimator"]
