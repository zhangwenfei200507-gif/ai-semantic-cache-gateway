from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.gateway import get_gateway
from app.auth.dependencies import get_current_admin, get_current_user
from app.config.settings import settings
from app.security.guards import public_error


router = APIRouter()


@router.get("/health")
def health():
    # Liveness must stay independent of Redis, PostgreSQL, S3 and the
    # embedding model so Railway does not restart a live process during a
    # transient dependency outage. Those checks belong to /ready.
    return {
        "status": "ok",
        "process": "alive",
    }


@router.get("/ready")
def ready():
    if settings.production_mode:
        try:
            settings.require_production_configuration()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    gateway = get_gateway()
    try:
        gateway.cache.embedding_service.ensure_ready()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Embedding model is not ready"),
        ) from exc

    result = gateway.health()
    if not result["redis"]:
        raise HTTPException(
            status_code=503,
            detail=result,
        )
    return {
        "ready": True,
        "embedding": {
            "ready": gateway.cache.embedding_service.is_ready,
            "model": settings.embedding_model,
        },
        **result,
    }


@router.get("/cache/stats")
def cache_stats(user: dict = Depends(get_current_user)):
    gateway = get_gateway()
    try:
        return {
            "size": gateway.cache.size(workspace_id=str(user["workspace"]["id"])),
            "redis": gateway.cache.ping(),
            "info": gateway.cache.repository.info(
                workspace_id=str(user["workspace"]["id"]),
            ),
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


@router.get("/lifecycle")
def lifecycle(_: dict = Depends(get_current_admin)):
    return get_gateway().lifecycle_manager.snapshot()
