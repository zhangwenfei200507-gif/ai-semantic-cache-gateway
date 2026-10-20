from __future__ import annotations

import time
import uuid
from typing import Any


class RequestContext:
    """Per-request execution context.

    This object is deliberately independent from FastAPI so the gateway can
    be used directly from tests, scripts, workers, or HTTP handlers.
    """

    TERMINAL_STATUSES = {"completed", "failed"}

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.request_id = request_id or str(uuid.uuid4())
        self.provider = provider
        self.model = model
        self.user_id = user_id

        self.status = "created"
        self.started_at = time.time()
        self.ended_at: float | None = None

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.cost = 0.0

        self.cache_hit = False
        self.cache_type: str | None = None
        self.error: str | None = None
        self.metadata: dict[str, Any] = {}

    def start(self) -> None:
        self.status = "running"
        self.started_at = time.time()
        self.ended_at = None
        self.error = None

    def add_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float | None = None,
    ) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens or 0))
        self.completion_tokens += max(0, int(completion_tokens or 0))
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        if cost is not None:
            self.cost = float(cost)

    def set_cache(self, hit: bool, cache_type: str | None = None) -> None:
        self.cache_hit = bool(hit)
        self.cache_type = cache_type

    def complete(self) -> None:
        self.status = "completed"
        self.ended_at = time.time()

    def fail(self, error: str | BaseException) -> None:
        self.status = "failed"
        self.ended_at = time.time()
        self.error = str(error)

    @property
    def latency_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return round(max(0.0, end - self.started_at) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "user_id": self.user_id,
            "status": self.status,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
            "cost": self.cost,
            "cache": {
                "hit": self.cache_hit,
                "type": self.cache_type,
            },
            "latency_ms": self.latency_ms,
            "error": self.error,
            "metadata": self.metadata,
        }
