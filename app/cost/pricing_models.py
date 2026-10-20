from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """
    Compatibility pricing model.

    Token pricing:
        USD / 1M tokens

    Image pricing:
        USD / image
    """

    model: str

    input_price_per_1m: float = 0.0

    output_price_per_1m: float = 0.0

    image_input_price: float = 0.0

    image_output_price: float = 0.0

    billing_type: str = "tokens"

    @property
    def input_price(self) -> float:
        """
        Backward-compatible alias.
        """
        return self.input_price_per_1m

    @property
    def output_price(self) -> float:
        """
        Backward-compatible alias.
        """
        return self.output_price_per_1m

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "input_price_per_1m":
                self.input_price_per_1m,
            "output_price_per_1m":
                self.output_price_per_1m,
            "image_input_price":
                self.image_input_price,
            "image_output_price":
                self.image_output_price,
            "billing_type":
                self.billing_type,
        }


__all__ = [
    "ModelPrice",
]