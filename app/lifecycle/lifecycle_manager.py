from __future__ import annotations

from threading import RLock
from typing import Any

from app.context.request_context import RequestContext


class LifecycleManager:
    """Process-local request lifecycle registry.

    It tracks only lightweight request metadata. Completed requests are not
    retained, so the registry cannot grow without bound during normal use.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._active: dict[str, RequestContext] = {}
        self._completed_total = 0
        self._failed_total = 0

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def completed_total(self) -> int:
        with self._lock:
            return self._completed_total

    @property
    def failed_total(self) -> int:
        with self._lock:
            return self._failed_total

    def start(self, context: RequestContext) -> RequestContext:
        context.start()
        with self._lock:
            self._active[context.request_id] = context
        return context

    def complete(self, context: RequestContext) -> RequestContext:
        context.complete()
        with self._lock:
            self._active.pop(context.request_id, None)
            self._completed_total += 1
        return context

    def fail(
        self,
        context: RequestContext,
        error: str | BaseException,
    ) -> RequestContext:
        context.fail(error)
        with self._lock:
            self._active.pop(context.request_id, None)
            self._failed_total += 1
        return context

    def get(self, request_id: str) -> RequestContext | None:
        with self._lock:
            return self._active.get(request_id)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_count": len(self._active),
                "completed_total": self._completed_total,
                "failed_total": self._failed_total,
                "active_requests": [
                    {
                        "request_id": ctx.request_id,
                        "user_id": ctx.user_id,
                        "provider": ctx.provider,
                        "model": ctx.model,
                        "status": ctx.status,
                        "started_at": ctx.started_at,
                    }
                    for ctx in self._active.values()
                ],
            }

    def reset(self) -> None:
        with self._lock:
            self._active.clear()
            self._completed_total = 0
            self._failed_total = 0
