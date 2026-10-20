from __future__ import annotations

from app.cost.cost_registry import (
    cost_registry,
)


class CostCalculator:
    """
    Calculate actual LLM request cost.

    Token models:
        USD / 1M tokens

    Image models:
        USD / image
    """

    def calculate(
        self,
        model: str,
        usage: dict,
    ) -> dict:

        price = cost_registry.get(
            model
        )

        prompt_tokens = max(
            0,
            int(
                usage.get(
                    "prompt_tokens",
                    0,
                )
                or 0
            ),
        )

        completion_tokens = max(
            0,
            int(
                usage.get(
                    "completion_tokens",
                    0,
                )
                or 0
            ),
        )

        image_inputs = max(
            0,
            int(
                usage.get(
                    "image_inputs",
                    0,
                )
                or 0
            ),
        )

        image_outputs = max(
            0,
            int(
                usage.get(
                    "image_outputs",
                    0,
                )
                or 0
            ),
        )

        billing_type = getattr(price, "billing_type", "tokens")

        if billing_type == "images":

            input_cost = (
                image_inputs
                *
                getattr(price, "image_input_price", 0.0)
            )

            output_cost = (
                image_outputs
                *
                getattr(price, "image_output_price", 0.0)
            )

        else:

            input_cost = (
                prompt_tokens
                /
                1_000_000.0
                *
                price.input_price_per_1m
            )

            output_cost = (
                completion_tokens
                /
                1_000_000.0
                *
                price.output_price_per_1m
            )

        total_cost = (
            input_cost
            +
            output_cost
        )

        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "image_inputs": image_inputs,
            "image_outputs": image_outputs,
            "input_cost": round(
                input_cost,
                10,
            ),
            "output_cost": round(
                output_cost,
                10,
            ),
            "total_cost": round(
                total_cost,
                10,
            ),
            "billing_type":
                billing_type,
        }


cost_calculator = CostCalculator()


__all__ = [
    "CostCalculator",
    "cost_calculator",
]
