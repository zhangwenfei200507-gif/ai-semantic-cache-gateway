from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from prometheus_client import REGISTRY

from app.config.settings import settings
from app.gateway import get_gateway
from app.auth.dependencies import get_current_user
from app.history.repository import history_repository


router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)


def _metric_value(name: str) -> float:
    """
    Read a label-free Prometheus counter/gauge value.

    Returns 0 when the metric does not exist yet.
    """
    try:
        for metric in REGISTRY.collect():
            if metric.name != name:
                continue

            for sample in metric.samples:
                if sample.name == name:
                    return float(sample.value)

    except Exception:
        pass

    return 0.0


def _metric_value_with_suffix(name: str) -> float:
    """
    Prometheus client normally exposes counters internally with
    a `_total` suffix.

    This helper accepts either the logical name or the exported name.
    """
    value = _metric_value(name)

    if value != 0:
        return value

    if name.endswith("_total"):
        return _metric_value(name[:-6])

    return value


def _safe_percentage(value: float, total: float) -> float:
    if total <= 0:
        return 0.0

    return round(
        max(0.0, min(100.0, value / total * 100.0)),
        2,
    )


def _redis_info(repository: Any) -> dict[str, Any]:
    try:
        info = repository.info()

        if not isinstance(info, dict):
            return {}

        return {
            "entries": info.get("entries"),
            "index": info.get("index"),
            "index_name": info.get("index_name"),
            "dimension": info.get("dimension"),
            "threshold": info.get("threshold"),
        }

    except Exception:
        return {}


@router.get("")
def dashboard(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Dashboard aggregate endpoint.

    This endpoint is intentionally read-only.

    Existing gateway/cache/provider behaviour is not modified.
    """

    gateway = get_gateway()

    try:
        redis_ok = bool(gateway.cache.ping())
    except Exception:
        redis_ok = False

    try:
        cache_size = int(gateway.cache.size(workspace_id=str(user["id"])))
    except Exception:
        cache_size = 0

    try:
        cache_info = _redis_info(gateway.cache.repository)
    except Exception:
        cache_info = {}

    # ---------------------------------------------------------------
    # Gateway request metrics
    # ---------------------------------------------------------------

    request_total = _metric_value_with_suffix(
        "gateway_requests_total"
    )

    error_total = _metric_value_with_suffix(
        "gateway_errors_total"
    )

    cache_hit_total = _metric_value_with_suffix(
        "gateway_cache_hits_total"
    )

    cache_miss_total = _metric_value_with_suffix(
        "gateway_cache_misses_total"
    )

    exact_hit_total = _metric_value_with_suffix(
        "gateway_cache_exact_hits_total"
    )

    semantic_hit_total = _metric_value_with_suffix(
        "gateway_cache_semantic_hits_total"
    )

    provider_request_total = _metric_value_with_suffix(
        "gateway_provider_requests_total"
    )

    provider_error_total = _metric_value_with_suffix(
        "gateway_provider_errors_total"
    )

    # ---------------------------------------------------------------
    # Latency
    # ---------------------------------------------------------------

    request_latency_sum = _metric_value(
        "gateway_request_latency_seconds_sum"
    )

    request_latency_count = _metric_value(
        "gateway_request_latency_seconds_count"
    )

    provider_latency_sum = _metric_value(
        "gateway_provider_latency_seconds_sum"
    )

    provider_latency_count = _metric_value(
        "gateway_provider_latency_seconds_count"
    )

    average_request_latency_ms = 0.0

    if request_latency_count > 0:
        average_request_latency_ms = round(
            (
                request_latency_sum
                / request_latency_count
            )
            * 1000,
            2,
        )

    average_provider_latency_ms = 0.0

    if provider_latency_count > 0:
        average_provider_latency_ms = round(
            (
                provider_latency_sum
                / provider_latency_count
            )
            * 1000,
            2,
        )

    # ---------------------------------------------------------------
    # Cache
    # ---------------------------------------------------------------

    cache_total = (
        cache_hit_total
        + cache_miss_total
    )

    hit_rate = _safe_percentage(
        cache_hit_total,
        cache_total,
    )

    exact_rate = _safe_percentage(
        exact_hit_total,
        cache_hit_total,
    )

    semantic_rate = _safe_percentage(
        semantic_hit_total,
        cache_hit_total,
    )

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    try:
        lifecycle = gateway.lifecycle_manager.snapshot()
    except Exception:
        lifecycle = {
            "active_count": 0,
            "completed_total": 0,
            "failed_total": 0,
            "active_requests": [],
        }

    # ---------------------------------------------------------------
    # Runtime LLM metrics
    # ---------------------------------------------------------------

    llm_metrics_data: dict[str, Any] = {}

    try:
        from app.metrics.llm_metrics import llm_metrics

        llm_metrics_data = llm_metrics.snapshot()

    except Exception:
        llm_metrics_data = {
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "average_latency_ms": 0.0,
        }

    # ---------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------

    provider = getattr(
        settings,
        "default_provider",
        "deepseek",
    )

    model = getattr(
        settings,
        "default_model",
        "deepseek-chat",
    )

    threshold = getattr(
        settings,
        "cache_threshold",
        0.75,
    )

    # Persisted history is the source of truth for a workspace dashboard.
    # Prometheus counters are process-local and reset after a restart.
    records = history_repository.list(
        100000,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )
    if records:
        request_total = len(records)
        error_total = sum(
            1 for item in records
            if str(item.get("status", "")).lower() == "error" or item.get("error")
        )
        cache_hit_total = sum(1 for item in records if item.get("cache_hit"))
        exact_hit_total = sum(1 for item in records if item.get("cache_type") == "exact")
        semantic_hit_total = sum(1 for item in records if item.get("cache_type") == "semantic")
        cache_miss_total = max(0, request_total - cache_hit_total)
        provider_request_total = sum(
            1 for item in records if not item.get("cache_hit") and not item.get("error")
        )
        provider_error_total = error_total
        latencies = [float(item.get("latency_ms") or 0) for item in records]
        latencies = [value for value in latencies if value > 0]
        average_request_latency_ms = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        average_provider_latency_ms = round(
            sum(float(item.get("provider_latency_ms") or 0) for item in records if float(item.get("provider_latency_ms") or 0) > 0)
            / max(1, sum(1 for item in records if float(item.get("provider_latency_ms") or 0) > 0)),
            2,
        )
        llm_metrics_data = {
            "total_requests": request_total,
            "success_requests": request_total - error_total,
            "failed_requests": error_total,
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in records),
            "total_cost": sum(float(item.get("cost") or 0) for item in records),
            "average_latency_ms": average_request_latency_ms,
        }
        hit_rate = _safe_percentage(cache_hit_total, request_total)
        exact_rate = _safe_percentage(exact_hit_total, cache_hit_total)
        semantic_rate = _safe_percentage(semantic_hit_total, cache_hit_total)

    # ---------------------------------------------------------------
    # Response
    # ---------------------------------------------------------------

    return {
        "workspace": user.get("workspace"),
        "gateway": {
            "name": getattr(
                settings,
                "app_name",
                "AI Semantic Cache Gateway",
            ),
            "version": getattr(
                settings,
                "app_version",
                "2.0.0",
            ),
            "status": (
                "healthy"
                if redis_ok
                else "degraded"
            ),
        },

        "redis": {
            "connected": redis_ok,
        },

        "cache": {
            "entries": cache_size,
            "hits": int(cache_hit_total),
            "misses": int(cache_miss_total),
            "hit_rate": hit_rate,
            "exact_hits": int(exact_hit_total),
            "semantic_hits": int(
                semantic_hit_total
            ),
            "exact_rate": exact_rate,
            "semantic_rate": semantic_rate,
            "threshold": threshold,
            "info": cache_info,
        },

        "requests": {
            "total": int(request_total),
            "errors": int(error_total),
            "successful": max(
                0,
                int(request_total - error_total),
            ),
            "error_rate": _safe_percentage(
                error_total,
                request_total,
            ),
            "average_latency_ms": (
                average_request_latency_ms
            ),
        },

        "provider": {
            "default": provider,
            "model": model,
            "requests": int(
                provider_request_total
            ),
            "errors": int(
                provider_error_total
            ),
            "average_latency_ms": (
                average_provider_latency_ms
            ),
            "error_rate": _safe_percentage(
                provider_error_total,
                provider_request_total,
            ),
        },

        "usage": {
            "total_requests": int(
                llm_metrics_data.get(
                    "total_requests",
                    0,
                )
            ),
            "success_requests": int(
                llm_metrics_data.get(
                    "success_requests",
                    0,
                )
            ),
            "failed_requests": int(
                llm_metrics_data.get(
                    "failed_requests",
                    0,
                )
            ),
            "total_tokens": int(
                llm_metrics_data.get(
                    "total_tokens",
                    0,
                )
            ),
            "total_cost": float(
                llm_metrics_data.get(
                    "total_cost",
                    0.0,
                )
            ),
            "average_latency_ms": float(
                llm_metrics_data.get(
                    "average_latency_ms",
                    0.0,
                )
            ),
        },

        "lifecycle": lifecycle,

        "system": {
            "redis": redis_ok,
            "provider": provider,
            "model": model,
            "cache_threshold": threshold,
        },
    }
