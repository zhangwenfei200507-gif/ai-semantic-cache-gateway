from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class RequestProfile:
    text: str

    language: str
    chinese_ratio: float

    task: str
    task_confidence: float

    domain: str
    domain_confidence: float

    complexity: str
    complexity_score: float

    coding_score: float
    reasoning_score: float
    analysis_score: float
    factual_score: float
    creative_score: float
    data_score: float

    estimated_input_tokens: int

    message_count: int
    text_length: int
    code_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelScore:
    provider: str
    model: str

    available: bool

    semantic_score: float
    task_score: float
    domain_score: float
    language_score: float
    complexity_score: float

    cost_score: float
    latency_score: float
    reliability_score: float

    quality_score: float
    final_score: float

    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float

    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RoutingDecision:
    provider: str
    model: str

    score: float

    confidence: float
    confidence_level: str

    mode: str

    reasons: list[str]

    request_profile: RequestProfile

    candidates: list[ModelScore]

    fallback_candidates: list[ModelScore]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "score": self.score,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "mode": self.mode,
            "reasons": self.reasons,
            "request_profile": self.request_profile.to_dict(),
            "candidates": [
                item.to_dict() for item in self.candidates
            ],
            "fallback_candidates": [
                item.to_dict() for item in self.fallback_candidates
            ],
        }
