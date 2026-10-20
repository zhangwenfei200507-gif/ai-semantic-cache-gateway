from __future__ import annotations

from dataclasses import dataclass

from app.config.providers import custom_provider_config


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """
    Model pricing.

    All prices are USD per 1,000,000 tokens.

    These explicit *_per_1m fields are intentionally used by
    CostEstimator so there is no ambiguity between:

        USD / 1K tokens
        USD / 1M tokens
    """

    model: str

    input_price_per_1m: float

    output_price_per_1m: float


class CostRegistry:
    """
    Central pricing registry.

    The registry stores pricing in USD per 1M tokens.

    CostEstimator already knows how to consume the explicit
    input_price_per_1m / output_price_per_1m fields.
    """

    def __init__(self) -> None:

        self._prices: dict[
            str,
            ModelPrice,
        ] = {}

        self._register_defaults()

    # ==========================================================
    # Default pricing
    # ==========================================================

    def _register_defaults(
        self,
    ) -> None:

        # ------------------------------------------------------
        # DeepSeek
        #
        # Project model:
        #   deepseek-chat
        #
        # Current project-side model maps to the DeepSeek V4
        # Flash family.
        #
        # Baseline non-peak pricing:
        #
        # input  : $0.22 / 1M
        # output : $0.66 / 1M
        # ------------------------------------------------------

        self.register(
            ModelPrice(
                model="deepseek-chat",
                input_price_per_1m=0.22,
                output_price_per_1m=0.66,
            )
        )

        self.register(
            ModelPrice(
                model="deepseek-v4-flash",
                input_price_per_1m=0.22,
                output_price_per_1m=0.66,
            )
        )

        self.register(
            ModelPrice(
                model="deepseek-flash",
                input_price_per_1m=0.22,
                output_price_per_1m=0.66,
            )
        )

        # ------------------------------------------------------
        # OpenAI
        #
        # Project model:
        #   gpt-5-nano
        #
        # Baseline pricing:
        #
        # input  : $0.05 / 1M
        # output : $0.40 / 1M
        # ------------------------------------------------------

        self.register(
            ModelPrice(
                model="gpt-5-nano",
                input_price_per_1m=0.05,
                output_price_per_1m=0.40,
            )
        )

        self.register(
            ModelPrice(
                model="gpt-5-nano-2025-08-07",
                input_price_per_1m=0.05,
                output_price_per_1m=0.40,
            )
        )

        # ------------------------------------------------------
        # Existing commonly-used model compatibility.
        # ------------------------------------------------------

        self.register(
            ModelPrice(
                model="gpt-4o-mini",
                input_price_per_1m=0.15,
                output_price_per_1m=0.60,
            )
        )

        # ------------------------------------------------------
        # User-defined OpenAI-compatible models.
        # Pricing is optional. Unknown pricing remains neutral in
        # RankingEngine instead of being treated as free.
        # ------------------------------------------------------

        for provider in custom_provider_config.all():
            for model in provider.get("models", []):
                model_name = str(model.get("name", "")).strip()
                if not model_name:
                    continue

                try:
                    input_price = float(model.get("input_price_per_1m", 0.0) or 0.0)
                    output_price = float(model.get("output_price_per_1m", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue

                if input_price < 0.0 or output_price < 0.0:
                    continue

                self.register(
                    ModelPrice(
                        model=model_name,
                        input_price_per_1m=input_price,
                        output_price_per_1m=output_price,
                    )
                )

    # ==========================================================
    # Registration
    # ==========================================================

    def register(
        self,
        price: ModelPrice,
    ) -> None:

        if not isinstance(
            price,
            ModelPrice,
        ):
            raise TypeError(
                "price must be ModelPrice"
            )

        model = (
            price.model
            .strip()
        )

        if not model:
            raise ValueError(
                "model cannot be empty"
            )

        if (
            price.input_price_per_1m
            < 0.0
        ):
            raise ValueError(
                "input_price_per_1m cannot be negative"
            )

        if (
            price.output_price_per_1m
            < 0.0
        ):
            raise ValueError(
                "output_price_per_1m cannot be negative"
            )

        self._prices[
            model
        ] = price

    # ==========================================================
    # Lookup
    # ==========================================================

    def get(
        self,
        model: str,
    ) -> ModelPrice:

        normalized = str(
            model or ""
        ).strip()

        price = self._prices.get(
            normalized
        )

        if price is not None:
            return price

        lowered = normalized.lower()
        if lowered.startswith("deepseek-"):
            return self._prices["deepseek-chat"]
        if lowered.startswith("gpt-5-nano"):
            return self._prices["gpt-5-nano"]

        # Unknown pricing is represented explicitly as zero
        # here. RankingEngine MUST treat this as unknown/neutral;
        # it must never interpret unknown pricing as "free".

        return ModelPrice(
            model=normalized,
            input_price_per_1m=0.0,
            output_price_per_1m=0.0,
        )

    # ==========================================================
    # Management helpers
    # ==========================================================

    def exists(
        self,
        model: str,
    ) -> bool:

        normalized = str(
            model or ""
        ).strip()

        return (
            normalized in self._prices
        )

    def remove(
        self,
        model: str,
    ) -> bool:

        normalized = str(
            model or ""
        ).strip()

        if normalized not in self._prices:
            return False

        del self._prices[
            normalized
        ]

        return True

    def list_models(
        self,
    ) -> list[str]:

        return sorted(
            self._prices.keys()
        )

    def all(
        self,
    ) -> list[ModelPrice]:

        return list(
            self._prices.values()
        )


# ==============================================================
# Global registry
# ==============================================================

cost_registry = CostRegistry()


__all__ = [
    "ModelPrice",
    "CostRegistry",
    "cost_registry",
]
