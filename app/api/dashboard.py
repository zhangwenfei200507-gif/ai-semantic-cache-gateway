from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from prometheus_client import REGISTRY

from app.config.settings import settings
from app.gateway import get_gateway
from app.auth.dependencies import get_current_admin, get_current_user
from app.history.repository import history_repository
from app.providers.workspace_store import WorkspaceProviderStore
from app.config.settings import load_workspace_settings
from app.api.management import SettingsUpdate as FullSettingsUpdate
from app.storage.service import ImageAssetRepository
from app.security.guards import public_error
from app.security.rate_limit import enforce_rate_limit, workspace_concurrency


router = APIRouter(
    prefix="/api",
    tags=["management"],
    dependencies=[Depends(get_current_user)],
)


def _metric_value(sample_name: str) -> float:
    try:
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == sample_name:
                    return float(sample.value)
    except Exception:
        return 0.0

    return 0.0


def _counter(name: str) -> int:
    return int(_metric_value(name))


def _percentage(value: float, total: float) -> float:
    if total <= 0:
        return 0.0

    return round(
        max(
            0.0,
            min(
                100.0,
                value / total * 100.0,
            ),
        ),
        2,
    )


def _safe_cache_info(gateway, workspace_id: str | None = None) -> dict[str, Any]:
    try:
        return gateway.cache.repository.info(workspace_id=workspace_id)
    except Exception as exc:
        return {
            "error": public_error(exc, "Cache metadata unavailable"),
        }


def _prometheus_summary() -> dict[str, Any]:
    request_total = _counter(
        "gateway_requests_total"
    )

    error_total = _counter(
        "gateway_errors_total"
    )

    cache_hits = _counter(
        "gateway_cache_hits_total"
    )

    cache_misses = _counter(
        "gateway_cache_misses_total"
    )

    exact_hits = _counter(
        "gateway_cache_exact_hits_total"
    )

    semantic_hits = _counter(
        "gateway_cache_semantic_hits_total"
    )

    provider_requests = _counter(
        "gateway_provider_requests_total"
    )

    provider_errors = _counter(
        "gateway_provider_errors_total"
    )

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
            * 1000.0,
            2,
        )

    average_provider_latency_ms = 0.0

    if provider_latency_count > 0:
        average_provider_latency_ms = round(
            (
                provider_latency_sum
                / provider_latency_count
            )
            * 1000.0,
            2,
        )

    cache_total = (
        cache_hits
        + cache_misses
    )

    return {
        "requests": {
            "total": request_total,
            "errors": error_total,
            "successful": max(
                0,
                request_total - error_total,
            ),
            "error_rate": _percentage(
                error_total,
                request_total,
            ),
            "average_latency_ms": (
                average_request_latency_ms
            ),
        },
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
            "exact_hits": exact_hits,
            "semantic_hits": semantic_hits,
            "hit_rate": _percentage(
                cache_hits,
                cache_total,
            ),
            "exact_rate": _percentage(
                exact_hits,
                cache_hits,
            ),
            "semantic_rate": _percentage(
                semantic_hits,
                cache_hits,
            ),
        },
        "provider": {
            "requests": provider_requests,
            "errors": provider_errors,
            "error_rate": _percentage(
                provider_errors,
                provider_requests,
            ),
            "average_latency_ms": (
                average_provider_latency_ms
            ),
        },
    }


def _provider_status(
    name: str,
    configured: bool,
    model: str,
    active: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "configured": configured,
        "model": model,
        "active": active,
        "status": (
            "active"
            if active
            else (
                "configured"
                if configured
                else "not_configured"
            )
        ),
    }


class SettingsUpdate(FullSettingsUpdate):
    pass


class PlaygroundRequest(BaseModel):
    model: str = "auto"
    messages: list[dict[str, Any]] = Field(
        min_length=1
    )
    user: str | None = None


@router.get("/dashboard")
def dashboard(user: dict = Depends(get_current_user)):
    gateway = get_gateway()

    try:
        redis_ok = bool(
            gateway.cache.ping()
        )
    except Exception:
        redis_ok = False

    try:
        cache_size = int(
            gateway.cache.size(workspace_id=str(user["workspace"]["id"]))
        )
    except Exception:
        cache_size = 0

    metrics = _prometheus_summary()
    user_history = history_repository.list(
        100000,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )
    if user_history:
        errors = sum(1 for item in user_history if str(item.get("status", "")).lower() == "error" or item.get("error"))
        hits = sum(1 for item in user_history if item.get("cache_hit"))
        total = len(user_history)
        latencies = sorted(float(item.get("latency_ms") or 0) for item in user_history if float(item.get("latency_ms") or 0) > 0)
        metrics["requests"] = {
            "total": total,
            "errors": errors,
            "successful": max(0, total - errors),
            "error_rate": _percentage(errors, total),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        }
        metrics["cache"]["hits"] = hits
        metrics["cache"]["misses"] = max(0, total - hits)
        metrics["cache"]["hit_rate"] = _percentage(hits, total)
        metrics["cache"]["exact_hits"] = sum(1 for item in user_history if item.get("cache_type") == "exact")
        metrics["cache"]["semantic_hits"] = sum(1 for item in user_history if item.get("cache_type") == "semantic")
        metrics["provider"]["requests"] = sum(1 for item in user_history if not item.get("cache_hit") and not item.get("error"))
        metrics["provider"]["errors"] = errors

    try:
        lifecycle = (
            gateway.lifecycle_manager.snapshot()
        )
    except Exception:
        lifecycle = {
            "active_count": 0,
            "completed_total": 0,
            "failed_total": 0,
            "active_requests": [],
        }

    try:
        llm_usage = __import__(
            "app.metrics.llm_metrics",
            fromlist=["llm_metrics"],
        ).llm_metrics.snapshot()
    except Exception:
        llm_usage = {
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "average_latency_ms": 0.0,
        }

    if settings.database_url:
        total_tokens = sum(int(item.get("total_tokens") or 0) for item in user_history)
        latencies = [float(item.get("latency_ms") or 0) for item in user_history if float(item.get("latency_ms") or 0) > 0]
        llm_usage = {
            "total_requests": len(user_history),
            "success_requests": sum(1 for item in user_history if str(item.get("status")) != "failed"),
            "failed_requests": sum(1 for item in user_history if str(item.get("status")) == "failed"),
            "total_tokens": total_tokens,
            "total_cost": sum(float(item.get("cost") or 0) for item in user_history),
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        }

    return {
        "workspace": user.get("workspace"),
        "gateway": {
            "name": settings.app_name,
            "version": settings.app_version,
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
            "threshold": (
                gateway.cache.similarity_threshold
            ),
            "info": _safe_cache_info(gateway, str(user["workspace"]["id"])),
            **metrics["cache"],
        },
        "requests": metrics["requests"],
        "provider": {
            "name": gateway.provider_name,
            "model": gateway.model_name,
            **metrics["provider"],
        },
        "usage": llm_usage,
        "lifecycle": {
            **lifecycle,
            "active_requests": [
                item
                for item in lifecycle.get("active_requests", [])
                if str(item.get("user_id")) == str(user["id"])
            ],
        },
    }


@router.get("/cache")
def cache_data(user: dict = Depends(get_current_user)):
    gateway = get_gateway()

    try:
        size = gateway.cache.size(workspace_id=str(user["workspace"]["id"]))
        ping = gateway.cache.ping()
        info = gateway.cache.repository.info(
            workspace_id=str(user["workspace"]["id"]),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc

    return {
        "connected": ping,
        "size": size,
        "threshold": (
            gateway.cache.similarity_threshold
        ),
        "info": info,
        "entries": cache_entries(user=user).get("entries", []),
    }


@router.get("/cache/entries")
def cache_entries(
    limit: int = 100,
    user: dict = Depends(get_current_user),
):
    gateway = get_gateway()

    try:
        redis_client = (
            gateway.cache.repository.redis
        )

        prefix = (
            gateway.cache.repository.key_prefix
        )

        keys = []

        cursor = 0

        while True:
            cursor, batch = (
                redis_client.scan(
                    cursor=cursor,
                    match=f"{prefix}{user['workspace']['id']}:*",
                    count=500,
                )
            )

            keys.extend(batch)

            if cursor == 0:
                break

        entries = []

        for raw_key in keys[:limit]:
            key = (
                raw_key.decode("utf-8")
                if isinstance(raw_key, bytes)
                else str(raw_key)
            )

            data = redis_client.hgetall(
                raw_key
            )

            def decode(value):
                if isinstance(value, bytes):
                    return value.decode(
                        "utf-8",
                        errors="replace",
                    )
                return value

            decoded = {
                (
                    key.decode("utf-8")
                    if isinstance(key, bytes)
                    else str(key)
                ): decode(value)
                for key, value in data.items()
            }

            if decoded.get("workspace_id") != str(user["workspace"]["id"]):
                continue

            identifier = (
                decoded.get("identifier")
                or decoded.get("key")
            )

            answer = decoded.get(
                "answer",
                "",
            )

            embedding = decoded.get(
                "embedding"
            )

            entries.append(
                {
                    "redis_key": key,
                    "key": identifier,
                    "answer": answer,
                    "embedding_bytes": (
                        len(embedding)
                        if isinstance(
                            embedding,
                            str,
                        )
                        else 0
                    ),
                    "fields": list(
                        decoded.keys()
                    ),
                }
            )

        return {
            "entries": entries,
            "count": len(entries),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc


@router.delete("/cache")
def clear_cache(user: dict = Depends(get_current_user)):
    gateway = get_gateway()

    try:
        gateway.cache.clear(workspace_id=str(user["workspace"]["id"]))

        return {
            "status": "ok",
            "size": gateway.cache.size(workspace_id=str(user["workspace"]["id"])),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc


@router.delete("/cache/entries/{entry_key}")
def delete_cache_entry(entry_key: str, user: dict = Depends(get_current_user)):
    gateway = get_gateway()

    prefix = (
        gateway.cache.repository.key_prefix
    )

    if entry_key.startswith(prefix):
        redis_key = entry_key
    else:
        redis_key = prefix + str(user["workspace"]["id"]) + ":" + entry_key

    try:
        owner = gateway.cache.repository.redis.hget(redis_key, "workspace_id")
        owner = owner.decode("utf-8") if isinstance(owner, bytes) else str(owner or "")
        if owner != str(user["workspace"]["id"]):
            raise HTTPException(status_code=404, detail="Cache entry not found")
        deleted = (
            gateway.cache.repository.redis.delete(
                redis_key
            )
        )

        return {
            "status": "ok",
            "deleted": bool(deleted),
            "redis_key": redis_key,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc


@router.get("/providers")
def providers(user: dict = Depends(get_current_user)):
    gateway = get_gateway()

    if settings.database_url:
        workspace_settings = load_workspace_settings(user["workspace"]["id"])
        rows = WorkspaceProviderStore(user["workspace"]["id"]).list()
        return {
            "active": {
                "name": workspace_settings.get("default_provider", ""),
                "model": workspace_settings.get("default_model", ""),
            },
            "providers": [
                {
                    **row,
                    "model": row["model_names"][0] if row["model_names"] else "",
                    "models": row["model_names"],
                    "active": row["name"] == workspace_settings.get("default_provider"),
                    "selectable": row["enabled"],
                    "capabilities": [row["role"]],
                }
                for row in rows
            ],
        }

    deepseek_key = bool(
        settings.deepseek_api_key
    )

    openai_key = bool(
        settings.openai_api_key
    )

    return {
        "active": {
            "name": gateway.provider_name,
            "model": gateway.model_name,
        },
        "providers": [
            _provider_status(
                "deepseek",
                deepseek_key,
                settings.deepseek_model,
                gateway.provider_name
                == "deepseek",
            ),
            _provider_status(
                "openai",
                openai_key,
                settings.openai_model,
                gateway.provider_name
                == "openai",
            ),
        ],
    }


@router.get("/requests")
def requests(
    limit: int = 100,
    keyword: str | None = None,
    cache_type: str | None = None,
    status: str | None = None,
    user: dict = Depends(get_current_user),
):
    gateway = get_gateway()

    try:
        lifecycle = (
            gateway.lifecycle_manager.snapshot()
        )
    except Exception:
        lifecycle = {
            "active_count": 0,
            "completed_total": 0,
            "failed_total": 0,
            "active_requests": [],
        }

    metrics = _prometheus_summary()

    records = history_repository.search(
        keyword=keyword,
        cache_type=cache_type,
        status=status,
        limit=limit,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )
    return {
        "items": records,
        "count": len(records),
        "stats": history_repository.stats(
            user_id=str(user["id"]),
            workspace_id=user["workspace"]["id"],
        ),
        "active": lifecycle.get(
            "active_requests",
            [],
        ),
        "active_count": lifecycle.get(
            "active_count",
            0,
        ),
        "completed_total": lifecycle.get(
            "completed_total",
            0,
        ),
        "failed_total": lifecycle.get(
            "failed_total",
            0,
        ),
        "metrics": metrics["requests"],
    }


@router.get("/requests/{request_id}")
def request_detail(
    request_id: str,
    user: dict = Depends(get_current_user),
):
    record = history_repository.get(
        request_id,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Request not found")
    assets = ImageAssetRepository().by_request(request_id, user["workspace"]["id"])
    record["images"] = [
        {
            "id": asset["id"],
            "url": f"/api/images/{asset['id']}",
            "download_url": f"/api/images/{asset['id']}/download",
            "mime_type": asset["mime_type"],
            "width": asset.get("width"),
            "height": asset.get("height"),
        }
        for asset in assets
    ]
    return record


@router.get("/metrics")
def metrics(user: dict = Depends(get_current_user)):
    summary = _prometheus_summary()

    gateway = get_gateway()

    try:
        usage = __import__(
            "app.metrics.llm_metrics",
            fromlist=["llm_metrics"],
        ).llm_metrics.snapshot()
    except Exception:
        usage = {}

    if settings.database_url:
        records = history_repository.list(
            100000,
            user_id=str(user["id"]),
            workspace_id=user["workspace"]["id"],
        )
        total = len(records)
        errors = sum(1 for item in records if str(item.get("status", "")).lower() == "failed" or item.get("error"))
        hits = sum(1 for item in records if item.get("cache_hit"))
        summary["requests"] = {
            "total": total,
            "errors": errors,
            "successful": max(0, total - errors),
            "error_rate": _percentage(errors, total),
            "average_latency_ms": round(
                sum(float(item.get("latency_ms") or 0) for item in records) / total,
                2,
            ) if total else 0.0,
        }
        summary["cache"].update({
            "hits": hits,
            "misses": max(0, total - hits),
            "hit_rate": _percentage(hits, total),
            "exact_hits": sum(1 for item in records if item.get("cache_type") == "exact"),
            "semantic_hits": sum(1 for item in records if item.get("cache_type") == "semantic"),
        })

    return {
        **summary,
        "usage": usage,
    }


@router.get("/system")
def system(_: dict = Depends(get_current_admin)):
    gateway = get_gateway()

    try:
        redis_ok = bool(
            gateway.cache.ping()
        )
    except Exception:
        redis_ok = False

    info = _safe_cache_info(gateway)

    return {
        "application": {
            "name": settings.app_name,
            "version": settings.app_version,
        },
        "redis": {
            "connected": redis_ok,
            "host": settings.redis_host,
            "port": settings.redis_port,
            "index": info.get(
                "index_name",
                "cache_idx",
            ),
            "vector_dimension": info.get(
                "vector_dim",
                None,
            ),
            "algorithm": info.get(
                "algorithm",
                "HNSW",
            ),
            "distance_metric": info.get(
                "distance_metric",
                "COSINE",
            ),
        },
        "embedding": {
            "model": settings.embedding_model,
        },
        "cache": {
            "threshold": (
                gateway.cache.similarity_threshold
            ),
        },
        "runtime": {
            "python": __import__(
                "platform"
            ).python_version(),
            "platform": __import__(
                "platform"
            ).platform(),
        },
    }


@router.get("/settings")
def get_settings(user: dict = Depends(get_current_user)):
    from app.api.management import _settings_view
    return _settings_view(user)


@router.patch("/settings")
def update_settings(
    payload: SettingsUpdate,
    user: dict = Depends(get_current_user),
):
    from app.api.management import update_settings as update_management_settings
    return update_management_settings(payload, user)


@router.post("/playground")
def playground(
    payload: PlaygroundRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    gateway = get_gateway()
    workspace_id = str(user["workspace"]["id"])
    enforce_rate_limit(
        request,
        "workspace-request",
        settings.workspace_request_rate_limit_per_minute,
        identity=f"workspace:{workspace_id}",
    )
    lease = workspace_concurrency.acquire(workspace_id)

    try:
        result = gateway.chat(
            messages=payload.messages,
            model=payload.model,
            user_id=str(user["id"]),
            workspace_id=str(user["workspace"]["id"]),
        )

        return {
            "ok": True,
            "response": result.to_dict(),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=public_error(exc, "Invalid playground request"),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=public_error(exc, "Upstream gateway request failed"),
        ) from exc
    finally:
        lease.release()
