from __future__ import annotations

import math
from typing import Any, Sequence


class SemanticEncoder:
    """
    Small adapter around the project's existing embedding service.

    Contract accepted from embedding_service:
      - encode(text) -> sequence[float]
      - optionally cosine(a, b)
      - optionally normalize_similarity(value)

    No provider-specific routing logic belongs here.
    """

    def __init__(self, embedding_service: Any):
        if embedding_service is None:
            raise ValueError("embedding_service is required")
        self.embedding_service = embedding_service

    def encode(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        value = self.embedding_service.encode(text)
        if value is None:
            raise RuntimeError("embedding service returned None")

        if hasattr(value, "tolist"):
            value = value.tolist()

        vector = [float(x) for x in value]
        if not vector:
            raise RuntimeError("embedding vector is empty")

        return vector

    @staticmethod
    def cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if len(a) != len(b):
            raise ValueError("embedding dimensions do not match")

        dot = 0.0
        aa = 0.0
        bb = 0.0

        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            aa += fx * fx
            bb += fy * fy

        denominator = math.sqrt(aa) * math.sqrt(bb)
        if denominator <= 1e-12:
            return 0.0

        return max(-1.0, min(1.0, dot / denominator))

    @staticmethod
    def normalize_similarity(value: float) -> float:
        return max(0.0, min(1.0, (float(value) + 1.0) / 2.0))
