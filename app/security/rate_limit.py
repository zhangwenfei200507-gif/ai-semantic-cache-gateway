from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

import redis
from fastapi import HTTPException, Request, status

from app.config.settings import settings


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass
class ConcurrencyLease:
    _release_callback: object
    _released: bool = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._release_callback()


class GatewayRateLimiter:
    """Redis-backed fixed-window limiter with a bounded local development fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local: dict[str, tuple[int, float]] = {}
        self._redis = None

    def _client(self):
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_keepalive=False,
            )
        return self._redis

    @staticmethod
    def _safe_key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    def check(self, scope: str, identity: str, limit: int, window_seconds: int = 60) -> None:
        if not settings.rate_limit_enabled:
            return
        key = f"ascg:rate:{scope}:{self._safe_key(identity)}"
        try:
            client = self._client()
            with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.ttl(key)
                count, ttl = pipe.execute()
                if int(count) == 1:
                    client.expire(key, int(window_seconds))
            if int(count) > int(limit):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(max(1, int(ttl) if int(ttl) > 0 else window_seconds))},
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            if settings.production_mode and settings.rate_limit_fail_closed:
                raise RateLimitUnavailable("Rate limiting service unavailable") from exc

        now = time.monotonic()
        with self._lock:
            count, started = self._local.get(key, (0, now))
            if now - started >= window_seconds:
                count, started = 0, now
            count += 1
            self._local[key] = (count, started)
            if len(self._local) > 10000:
                self._local = {
                    item_key: value
                    for item_key, value in self._local.items()
                    if now - value[1] < window_seconds
                }
        if count > int(limit):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(window_seconds)},
            )


class WorkspaceConcurrency:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global = threading.BoundedSemaphore(max(1, settings.global_max_concurrent_requests))
        self._workspaces: dict[str, threading.BoundedSemaphore] = {}

    def acquire(self, workspace_id: str) -> ConcurrencyLease:
        if not self._global.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Gateway concurrency limit reached")
        with self._lock:
            semaphore = self._workspaces.setdefault(
                str(workspace_id),
                threading.BoundedSemaphore(max(1, settings.workspace_max_concurrent_requests)),
            )
        if not semaphore.acquire(blocking=False):
            self._global.release()
            raise HTTPException(status_code=429, detail="Workspace concurrency limit reached")

        def release() -> None:
            semaphore.release()
            self._global.release()

        return ConcurrencyLease(release)


rate_limiter = GatewayRateLimiter()
workspace_concurrency = WorkspaceConcurrency()


def enforce_rate_limit(request: Request, scope: str, limit: int, identity: str | None = None) -> None:
    client_ip = request.client.host if request.client else "unknown"
    try:
        rate_limiter.check(scope, identity or client_ip, limit)
    except RateLimitUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting service unavailable",
        ) from exc


__all__ = [
    "ConcurrencyLease",
    "GatewayRateLimiter",
    "RateLimitUnavailable",
    "enforce_rate_limit",
    "rate_limiter",
    "workspace_concurrency",
]
