from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMResponse:
    """Unified provider -> gateway response contract."""

    answer: str
    model: str
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    finish_reason: str | None = None
    raw: Any = None
    images: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return int(self.prompt_tokens or 0) + int(self.completion_tokens or 0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data
