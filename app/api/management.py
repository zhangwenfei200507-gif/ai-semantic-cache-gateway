from __future__ import annotations

import platform
import time
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config.providers import custom_provider_config
from app.config.settings import load_workspace_settings, save_runtime_settings, settings
from app.gateway import get_gateway
from app.history.repository import history_repository
from app.providers.factory import ProviderFactory
from app.providers.registry import provider_registry
from app.providers.workspace_store import WorkspaceProviderStore
from app.routing.capability_registry import capability_registry
from app.clients.generic_openai_compatible_client import (
    GenericOpenAICompatibleClient,
)
from app.auth.dependencies import get_current_admin, get_current_user
from app.security.guards import public_error, validate_provider_base_url
from app.security.rate_limit import enforce_rate_limit, workspace_concurrency


router = APIRouter(
    prefix="/api",
    tags=["management"],
    dependencies=[Depends(get_current_user)],
)


class SettingsUpdate(BaseModel):
    app_name: str | None = Field(default=None, min_length=1, max_length=120)
    default_provider: str | None = Field(default=None, min_length=1, max_length=80)
    default_model: str | None = Field(default=None, min_length=1, max_length=160)
    llm_timeout: float | None = Field(default=None, ge=1, le=600)
    llm_max_retries: int | None = Field(default=None, ge=0, le=5)
    cache_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    cache_ttl: int | None = Field(default=None, ge=60, le=604800)
    semantic_cache_enabled: bool | None = None
    exact_cache_enabled: bool | None = None
    cache_max_answer_length: int | None = Field(default=None, ge=256, le=200000)
    log_level: str | None = Field(default=None, min_length=1, max_length=20)
    log_to_file: bool | None = None
    log_file: str | None = Field(default=None, max_length=260)
    auth_token_expiration_hours: int | None = Field(default=None, ge=1, le=720)
    notifications_enabled: bool | None = None


class ProviderConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=400)
    api_key_env: str = Field(default="PROVIDER_API_KEY", min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    display_name: str | None = Field(default=None, max_length=120)
    role: str = Field(default="answer", max_length=40)
    model: str | None = Field(default=None, max_length=160)
    models: list[str] | None = None
    capabilities: list[str] = Field(default_factory=lambda: ["general", "reasoning", "coding"])
    enabled: bool = True
    model_configs: list[dict[str, Any]] | None = None


class ProviderModelsUpdate(BaseModel):
    models: list[str] = Field(min_length=1, max_length=32)
    api_key: str | None = Field(default=None, max_length=500)
    model_configs: list[dict[str, Any]] | None = None


class ProviderTestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None


class ProviderCredentialRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    model: str | None = Field(default=None, max_length=160)


class PlaygroundRequest(BaseModel):
    model: str = "auto"
    messages: list[dict[str, Any]] = Field(
        min_length=1
    )
    user: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=8192)


def _rough_tokens(
    text: str | None,
) -> int:
    if not text:
        return 0

    value = str(text)

    chinese = sum(
        1
        for char in value
        if "\u4e00" <= char <= "\u9fff"
    )

    latin = sum(
        1
        for char in value
        if char.isascii() and char.isalpha()
    )

    return max(
        1,
        int(
            chinese * 1.05
            + latin / 4.0
        ),
    )


def _with_savings(
    item: dict[str, Any],
) -> dict[str, Any]:
    record = dict(item)

    consumed_tokens = int(
        record.get("total_tokens")
        or 0
    )

    cache_hit = bool(
        record.get("cache_hit")
    )

    saved_tokens = 0

    if cache_hit:
        saved_tokens = _rough_tokens(
            record.get("question")
        ) + _rough_tokens(
            record.get("answer")
        )

    record["consumed_tokens"] = consumed_tokens
    record["saved_tokens"] = saved_tokens
    record["net_tokens"] = consumed_tokens

    return record


def _history(
    *,
    limit: int = 100,
    keyword: str | None = None,
    cache_type: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    workspace_id: int | str | None = None,
) -> list[dict[str, Any]]:
    return [
        _with_savings(item)
        for item
        in history_repository.search(
        keyword=keyword,
        cache_type=cache_type,
        status=status,
        limit=limit,
        user_id=user_id,
        workspace_id=workspace_id,
        )
    ]


def _provider_rows(gateway, user: dict | None = None) -> list[dict[str, Any]]:
    if settings.database_url and user is not None:
        store = WorkspaceProviderStore(user["workspace"]["id"])
        workspace_settings = load_workspace_settings(user["workspace"]["id"])
        rows = []
        for item in store.list():
            model_names = item["model_names"]
            rows.append({
                **item,
                "name": item["name"],
                "model": model_names[0] if model_names else "",
                "models": model_names,
                "active": (
                    item["name"] == str(workspace_settings.get("default_provider", "")).lower()
                ),
                "selectable": bool(item["enabled"]),
                "capabilities": [item["role"]],
                "custom": item["name"] not in {"deepseek", "openai", "qwen"},
            })
        return rows
    deepseek_models = settings.model_names("deepseek")
    openai_models = settings.model_names("openai")
    rows = [
        {
            "name": "deepseek",
            "model": deepseek_models[0] if deepseek_models else "",
            "models": deepseek_models,
            "base_url": settings.deepseek_base_url,
            "configured": settings.is_deepseek_configured(),
            "active": gateway.provider_name == "deepseek",
            "status": "configured" if settings.is_deepseek_configured() else "not_configured",
            "capabilities": ["text", "reasoning", "coding", "analysis", "chinese"],
            "role": "answer",
            "selectable": True,
        },
        {
            "name": "openai",
            "model": openai_models[0] if openai_models else "",
            "models": openai_models,
            "base_url": settings.openai_base_url,
            "configured": settings.is_openai_configured(),
            "active": gateway.provider_name == "openai",
            "status": "configured" if settings.is_openai_configured() else "not_configured",
            "capabilities": ["text", "reasoning", "coding", "analysis", "multilingual"],
            "role": "answer",
            "selectable": True,
        },
        {
            "name": "qwen_classifier",
            "display_name": "Qwen",
            "model": settings.qwen_classifier_model,
            "models": [settings.qwen_classifier_model],
            "base_url": settings.qwen_classifier_base_url,
            "configured": settings.is_qwen_classifier_configured(),
            "active": False,
            "status": "configured" if settings.is_qwen_classifier_configured() else "not_configured",
            "capabilities": ["classification", "routing"],
            "role": "router",
            "selectable": False,
            "system": True,
        },
        {
            "name": "qwen_image",
            "display_name": "Qwen",
            "model": settings.qwen_image_model,
            "models": settings.model_names("qwen_image"),
            "base_url": settings.qwen_image_base_url,
            "configured": settings.is_qwen_image_configured(),
            "active": False,
            "status": "configured" if settings.is_qwen_image_configured() else "not_configured",
            "capabilities": ["image", "image_generation"],
            "role": "image",
            "selectable": False,
            "system": True,
        },
    ]

    for custom in custom_provider_config.all():
        name = str(custom.get("name", "")).strip().lower()
        key_env = str(custom.get("api_key_env", "")).strip()
        configured = bool(key_env and os.getenv(key_env))
        models = [str(item.get("name", "")) for item in custom.get("models", [])]
        rows.append(
            {
                "name": name,
                "model": models[0] if models else "",
                "models": models,
                "base_url": custom.get("base_url", ""),
                "api_key_env": key_env,
                "configured": configured,
                "active": gateway.provider_name == name,
                "status": (
                    "active" if gateway.provider_name == name and configured
                    else "configured" if configured
                    else "not_configured"
                ),
                "enabled": bool(custom.get("enabled", True)),
                "capabilities": custom.get("capabilities", []),
                "custom": True,
                "role": "answer",
                "selectable": True,
            }
        )

    return rows


def _settings_view(user: dict | None = None) -> dict[str, Any]:
    gateway = get_gateway()
    workspace_values = (
        load_workspace_settings(user["workspace"]["id"])
        if settings.database_url and user is not None
        else {}
    )
    value = lambda key, default=None: workspace_values.get(key, default)
    try:
        redis_ok = bool(gateway.cache.ping())
    except Exception:
        redis_ok = False

    return {
        "application": {
            "name": settings.app_name,
            "version": settings.app_version,
            "host": settings.host,
            "port": settings.port,
        },
        "general": {
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": os.getenv("APP_ENV", "development"),
        },
        "gateway": {
            "provider": value("default_provider", gateway.provider_name),
            "model": value("default_model", gateway.model_name),
            "configured_model": value("default_model", gateway.configured_model_name),
        },
        "ai_configuration": {
            "default_provider": value("default_provider", settings.default_provider),
            "default_model": value("default_model", settings.default_model),
            "timeout": value("llm_timeout", settings.llm_timeout),
            "max_retries": value("llm_max_retries", settings.llm_max_retries),
            "cost_tracking": settings.enable_cost_tracking,
        },
        "cache": {
            "semantic_enabled": bool(value("semantic_cache_enabled", gateway.cache.policy.semantic_enabled)),
            "exact_enabled": bool(value("exact_cache_enabled", gateway.cache.policy.exact_enabled)),
            "threshold": value("cache_threshold", gateway.cache.similarity_threshold),
            "ttl": value("cache_ttl", settings.cache_ttl),
            "max_answer_length": value("cache_max_answer_length", settings.cache_max_answer_length),
            "index_name": settings.cache_index_name,
            "key_prefix": settings.cache_key_prefix,
            "vector_dimension": settings.vector_dimension,
            "distance_metric": settings.distance_metric,
            "algorithm": settings.vector_algorithm,
        },
        "providers": _provider_rows(gateway, user),
        "embedding": {
            "model": settings.embedding_model,
            "dimension": settings.vector_dimension,
        },
        "redis": {
            "host": settings.redis_host,
            "port": settings.redis_port,
            "connected": redis_ok,
            "configured": bool(str(settings.redis_url or "").strip()),
        },
        "database": {
            "type": "PostgreSQL" if settings.database_url else "SQLite",
            "path": None if settings.database_url else str(Path("data/gateway.db").resolve()),
            "status": "connected" if history_repository.count() >= 0 else "unavailable",
        },
        "logging": {
            "level": settings.log_level,
            "to_file": settings.log_to_file,
            "file": settings.log_file,
        },
        "security": {
            "auth_enabled": settings.is_auth_configured(),
            "token_expiration_hours": settings.auth_token_expiration_hours,
            "secret_configured": settings.is_auth_configured(),
        },
        "notifications": {
            "enabled": settings.notifications_enabled,
            "smtp_configured": settings.smtp_configured,
            "from_email": settings.smtp_from_email or "",
        },
        "about": {
            "name": settings.app_name,
            "version": settings.app_version,
            "features": [
                "Exact Cache",
                "Redis Semantic Cache",
                "Automatic Provider Routing",
                "Request History",
                "Cost and Token Tracking",
            ],
        },
        "llm": {
            "timeout": settings.llm_timeout,
            "max_retries": settings.llm_max_retries,
        },
    }


def _configure_logging() -> None:
    level = str(settings.log_level or "INFO").upper()
    numeric = getattr(logging, level, logging.INFO)
    logging.getLogger().setLevel(numeric)
    if not settings.log_to_file:
        return
    path = Path(settings.log_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if not any(getattr(handler, "baseFilename", "") == str(path) for handler in root.handlers):
        root.addHandler(logging.FileHandler(path, encoding="utf-8"))


@router.get("/cache")
def cache_data(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    gateway = get_gateway()
    workspace_id = str(user["workspace"]["id"])

    try:
        repository = gateway.cache.repository
        info = repository.info(workspace_id=workspace_id)
        entries = []
        redis_client = repository.redis
        prefix = repository.key_prefix
        cursor = 0

        while True:
            cursor, batch = redis_client.scan(
                cursor=cursor,
                match=f"{prefix}{workspace_id}:*",
                count=500,
            )

            for raw_key in batch:
                redis_key = (
                    raw_key.decode("utf-8")
                    if isinstance(raw_key, bytes)
                    else str(raw_key)
                )

                raw_data = redis_client.hgetall(raw_key)

                decoded = {}
                embedding_bytes = 0
                for key, value in raw_data.items():
                    field = (
                        key.decode("utf-8")
                        if isinstance(key, bytes)
                        else str(key)
                    )

                    if field == repository.vector_field:
                        embedding_bytes = len(value)
                        decoded[field] = f"{len(value)} bytes"
                        continue

                    decoded[field] = (
                        value.decode("utf-8", errors="replace")
                        if isinstance(value, bytes)
                        else value
                    )

                cache_key = decoded.get("key") or redis_key.removeprefix(
                    prefix
                )

                try:
                    ttl_seconds = int(redis_client.ttl(raw_key))
                except Exception:
                    ttl_seconds = None

                try:
                    hit_count = int(decoded.get("hit_count") or 0)
                except (TypeError, ValueError):
                    hit_count = 0

                entries.append(
                    {
                        "id": cache_key,
                        "redis_key": redis_key,
                        "key": cache_key,
                        "answer": decoded.get("answer", ""),
                        "question": decoded.get(
                            "question",
                            decoded.get("key", cache_key),
                        ),
                        "cache_type": "semantic" if repository.vector_field in decoded else "exact",
                        "similarity": None,
                        "hit_count": hit_count,
                        "ttl_seconds": ttl_seconds,
                        "created_at": decoded.get("created_at"),
                        "embedding_bytes": embedding_bytes,
                        "fields": decoded,
                    }
                )

            if cursor == 0:
                break

        return {
            "connected": repository.ping(),
            "size": gateway.cache.size(workspace_id=workspace_id),
            "threshold": gateway.cache.similarity_threshold,
            "ttl_seconds": gateway.cache.policy.ttl_seconds,
            "semantic_enabled": gateway.cache.policy.semantic_enabled,
            "exact_enabled": gateway.cache.policy.exact_enabled,
            "info": info,
            "entries": entries,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc


@router.delete("/cache")
def clear_cache(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    gateway = get_gateway()
    workspace_id = str(user["workspace"]["id"])

    try:
        gateway.cache.clear(workspace_id=workspace_id)

        return {
            "status": "ok",
            "size": gateway.cache.size(workspace_id=workspace_id),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Cache service unavailable"),
        ) from exc


@router.delete("/cache/entries/{entry_key:path}")
def delete_cache_entry(
    entry_key: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    gateway = get_gateway()
    repository = gateway.cache.repository
    prefix = repository.key_prefix

    workspace_id = str(user["workspace"]["id"])
    redis_key = entry_key if entry_key.startswith(prefix) else prefix + workspace_id + ":" + entry_key

    try:
        owner = repository.redis.hget(redis_key, "workspace_id")
        owner = owner.decode("utf-8") if isinstance(owner, bytes) else str(owner or "")
        if owner != workspace_id:
            raise HTTPException(status_code=404, detail="Cache entry not found")
        deleted = repository.redis.delete(redis_key)

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
def providers(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    gateway = get_gateway()
    workspace_settings = load_workspace_settings(user["workspace"]["id"])
    active_provider = workspace_settings.get("default_provider", gateway.provider_name)
    active_model = workspace_settings.get("default_model", gateway.model_name)

    return {
        "active": {
            "provider": active_provider,
            "model": active_model,
        },
        "providers": _provider_rows(gateway, user),
    }


@router.get("/onboarding")
def onboarding(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return Workspace-backed onboarding progress for the current user."""
    rows = _provider_rows(get_gateway(), user)
    configured = [item for item in rows if item.get("configured")]
    verified = [
        item for item in configured
        if item.get("verified", item.get("configured", False))
    ]
    history = history_repository.list(
        1,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )
    has_first_request = bool(history)

    if not configured:
        state = "no_provider"
        primary = {
            "label": "Add Your First Provider",
            "href": "/pages/providers.html?add=1",
        }
    elif not verified:
        state = "needs_verification"
        primary = {
            "label": "Verify Provider Connection",
            "href": "/pages/providers.html",
        }
    elif not has_first_request:
        state = "ready_for_playground"
        primary = {
            "label": "Open Playground",
            "href": "/pages/playground.html",
        }
    else:
        state = "completed"
        primary = {
            "label": "Open Analytics",
            "href": "/pages/metrics.html",
        }

    return {
        "state": state,
        "show_getting_started": state != "completed",
        "workspace_id": user["workspace"]["id"],
        "provider_count": len(rows),
        "configured_provider_count": len(configured),
        "verified_provider_count": len(verified),
        "has_first_request": has_first_request,
        "primary_action": primary,
        "learn_href": "/pages/playground.html?tab=routing",
        "steps": [
            {
                "id": "connect",
                "title": "Connect Provider",
                "description": "Add your Provider and verify the connection.",
                "status": "completed" if verified else "current",
                "href": "/pages/providers.html?add=1" if not verified else "/pages/providers.html",
                "action": "Add Provider" if not configured else "Verify Connection",
            },
            {
                "id": "playground",
                "title": "Test in Playground",
                "description": "Send your first request with your own key.",
                "status": "completed" if has_first_request else "current" if verified else "locked",
                "href": "/pages/playground.html",
                "action": "Open Playground",
            },
            {
                "id": "analytics",
                "title": "Explore Analytics",
                "description": "Review usage, latency and cache performance.",
                "status": "current" if has_first_request else "locked",
                "href": "/pages/metrics.html",
                "action": "View Analytics",
            },
        ],
    }


@router.post("/providers")
def add_provider(payload: ProviderConfigRequest, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    name = payload.name.strip().lower()
    models = [item.strip() for item in (payload.models or []) if item.strip()]
    if payload.model and payload.model.strip():
        models.insert(0, payload.model.strip())
    models = list(dict.fromkeys(models))
    if not models:
        raise HTTPException(status_code=422, detail="At least one model is required")

    try:
        if settings.database_url:
            model_configs = payload.model_configs or [
                {"model_id": model, "capabilities": payload.capabilities}
                for model in models
            ]
            WorkspaceProviderStore(user["workspace"]["id"]).upsert(
                name=name,
                display_name=payload.display_name,
                base_url=payload.base_url.strip().rstrip("/"),
                models=model_configs,
                api_key=payload.api_key,
                role=payload.role,
                enabled=payload.enabled,
            )
            return providers(user)
        custom_provider_config.upsert(
            {
                "name": name,
                "base_url": validate_provider_base_url(payload.base_url),
                "api_key_env": payload.api_key_env.strip(),
                "models": [
                    {
                        "name": model,
                        "capabilities": payload.capabilities,
                    }
                    for model in models
                ],
                "capabilities": payload.capabilities,
                "enabled": payload.enabled,
            }
        )
        provider_registry.refresh()
        capability_registry.refresh()
        gateway = get_gateway()
        gateway.model_router.registry.refresh()
        return providers(user)
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail=public_error(exc, "Invalid provider configuration"),
        ) from exc


@router.delete("/providers/{provider_name}")
def delete_provider(provider_name: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if settings.database_url:
        if not WorkspaceProviderStore(user["workspace"]["id"]).delete(provider_name):
            raise HTTPException(status_code=404, detail="Provider not found")
        return providers(user)
    if provider_name.strip().lower() in {"deepseek", "openai", "qwen_classifier", "qwen_image"}:
        raise HTTPException(status_code=400, detail="Built-in providers are managed by environment settings")
    if not custom_provider_config.remove(provider_name):
        raise HTTPException(status_code=404, detail="Provider not found")
    provider_registry.refresh()
    capability_registry.refresh()
    get_gateway().model_router.registry.refresh()
    return providers(user)


@router.patch("/providers/{provider_name}/models")
def update_provider_models(provider_name: str, payload: ProviderModelsUpdate, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    name = provider_name.strip().lower()
    models = list(dict.fromkeys(item.strip() for item in payload.models if item.strip()))
    if not models:
        raise HTTPException(status_code=422, detail="At least one model is required")
    if settings.database_url:
        model_configs = payload.model_configs or [
            {"model_id": model}
            for model in models
        ]
        try:
            store = WorkspaceProviderStore(user["workspace"]["id"])
            current = store.update_models(name, model_configs)
            if payload.api_key:
                store.upsert(
                    name=name,
                    display_name=current.get("display_name"),
                    base_url=current.get("base_url", ""),
                    models=model_configs,
                    api_key=payload.api_key,
                    role=current.get("role", "answer"),
                    enabled=current.get("enabled", True),
                )
            return providers(user)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=public_error(exc, "Provider not found"),
            ) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=public_error(exc, "Invalid provider model configuration"),
            ) from exc
    if name not in {"deepseek", "openai", "qwen_classifier", "qwen_image"}:
        custom = custom_provider_config.get(name)
        if custom is None:
            raise HTTPException(status_code=400, detail="This provider does not support runtime model lists")
        custom_provider_config.upsert({**custom, "models": models})
        provider_registry.refresh()
        capability_registry.refresh()
        get_gateway().model_router.registry.refresh()
        return providers(user)
    field = f"{name}_models"
    setattr(settings, field, ",".join(models))
    save_runtime_settings({field: getattr(settings, field)}, workspace_id=user["workspace"]["id"])
    provider_registry.refresh()
    capability_registry.refresh()
    get_gateway().model_router.registry.refresh()
    return providers(user)


@router.post("/providers/test")
def test_provider(
    payload: ProviderTestRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    enforce_rate_limit(
        request,
        "provider-test",
        settings.provider_test_rate_limit_per_minute,
        identity=f"user:{user['id']}",
    )
    provider_name = payload.name.strip().lower()
    try:
        if payload.api_key and payload.base_url:
            base_url = validate_provider_base_url(payload.base_url)
            client = GenericOpenAICompatibleClient(
                provider_name=provider_name,
                api_key=payload.api_key,
                base_url=base_url,
                model=payload.model.strip(),
                timeout=min(float(settings.llm_timeout), 20.0),
                max_retries=0,
            )
            response = client.chat(
                messages=[{"role": "user", "content": "Reply with OK only."}],
                model=payload.model.strip(),
                timeout=min(float(settings.llm_timeout), 20.0),
                max_tokens=8,
                temperature=0,
            )
        elif settings.database_url:
            provider = ProviderFactory.create_for_workspace(
                provider_name,
                payload.model.strip(),
                user["workspace"]["id"],
            )
            response = provider.chat(
                messages=[{"role": "user", "content": "Reply with OK only."}],
                model=payload.model.strip(),
                timeout=min(float(settings.llm_timeout), 20.0),
                max_tokens=8,
                temperature=0,
            )
            WorkspaceProviderStore(user["workspace"]["id"]).mark_verified(
                provider_name,
                payload.model.strip(),
            )
        else:
            response = ProviderFactory.create(provider_name, payload.model.strip()).chat(
                messages=[{"role": "user", "content": "Reply with OK only."}],
                model=payload.model.strip(),
                timeout=min(float(settings.llm_timeout), 20.0),
                max_tokens=8,
                temperature=0,
            )
        return {
            "ok": True,
            "provider": response.provider or provider_name,
            "model": response.model or payload.model,
            "latency_ms": response.latency_ms,
            "answer": response.answer,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=public_error(exc, "Provider connection test failed"),
        ) from exc


@router.delete("/providers/{provider_name}/credentials")
def delete_provider_credential(
    provider_name: str,
    model: str | None = None,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not settings.database_url:
        raise HTTPException(status_code=400, detail="Workspace credentials require PostgreSQL")
    deleted = WorkspaceProviderStore(user["workspace"]["id"]).delete_credential(
        provider_name,
        model=model,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider credential not found")
    return {"status": "ok", "provider": provider_name, "model": model}


@router.patch("/providers/{provider_name}/credentials")
def update_provider_credential(
    provider_name: str,
    payload: ProviderCredentialRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not settings.database_url:
        raise HTTPException(status_code=400, detail="Workspace credentials require PostgreSQL")
    store = WorkspaceProviderStore(user["workspace"]["id"])
    current = next((item for item in store.list() if item["name"] == provider_name.strip().lower()), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    model_configs = [
        {
            "model_id": item,
            "api_key": payload.api_key if payload.model == item else None,
        }
        for item in current["model_names"]
    ]
    if payload.model:
        if payload.model not in current["model_names"]:
            raise HTTPException(status_code=404, detail="Model not found")
        store.update_models(provider_name, model_configs)
    else:
        store.upsert(
            name=provider_name,
            display_name=current["display_name"],
            base_url=current["base_url"],
            models=current["model_names"],
            api_key=payload.api_key,
            role=current["role"],
            enabled=current["enabled"],
        )
    return {"status": "ok", "provider": provider_name, "model": payload.model, "configured": True}


@router.get("/models")
def models(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if settings.database_url:
        items = WorkspaceProviderStore(user["workspace"]["id"]).capabilities().configured()
        return {"models": [
            {
                "provider": item.provider,
                "model": item.model,
                "configured": True,
                "enabled": item.enabled,
                "description": item.routing_description,
            }
            for item in items
        ]}
    return {
        "models": [
            {
                "provider": item.provider,
                "model": item.model,
                "configured": True,
                "enabled": item.enabled,
                "description": item.routing_description,
            }
            for item in capability_registry.configured()
        ],
    }


@router.get("/requests")
def requests(
    limit: int = Query(default=100, ge=1, le=500),
    keyword: str | None = None,
    cache_type: str | None = None,
    status: str | None = None,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    items = _history(
        limit=limit,
        keyword=keyword,
        cache_type=cache_type,
        status=status,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )

    return {
        "items": items,
        "count": len(items),
        "stats": history_repository.stats(
            user_id=str(user["id"]),
            workspace_id=user["workspace"]["id"],
        ),
    }


@router.get("/requests/{request_id}")
def request_detail(
    request_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    item = history_repository.get(
        request_id,
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Request not found",
        )

    return _with_savings(
        item
    )


@router.delete("/requests")
def clear_requests(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    history_repository.clear(
        user_id=str(user["id"]),
        workspace_id=user["workspace"]["id"],
    )

    return {
        "status": "ok",
        "count": 0,
    }


@router.get("/metrics/data")
def metrics_data(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        if settings.database_url:
            records = history_repository.list(
                100000,
                user_id=str(user["id"]),
                workspace_id=user["workspace"]["id"],
            )
            latencies = [float(item.get("latency_ms") or 0) for item in records if float(item.get("latency_ms") or 0) > 0]
            return {
                "total_requests": len(records),
                "success_requests": sum(1 for item in records if str(item.get("status")) != "failed"),
                "failed_requests": sum(1 for item in records if str(item.get("status")) == "failed"),
                "total_tokens": sum(int(item.get("total_tokens") or 0) for item in records),
                "total_cost": sum(float(item.get("cost") or 0) for item in records),
                "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            }
        from app.metrics.llm_metrics import llm_metrics

        return llm_metrics.snapshot()

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=public_error(exc, "Metrics service unavailable"),
        ) from exc


@router.get("/cost")
def cost(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if settings.database_url:
        records = history_repository.list(
            100000,
            user_id=str(user["id"]),
            workspace_id=user["workspace"]["id"],
        )
        return {
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in records),
            "total_cost": sum(float(item.get("cost") or 0) for item in records),
            "currency": "USD",
        }
    try:
        from app.metrics.llm_metrics import llm_metrics

        metrics = llm_metrics.snapshot()

    except Exception:
        metrics = {}

    return {
        "total_tokens": metrics.get(
            "total_tokens",
            0,
        ),
        "total_cost": metrics.get(
            "total_cost",
            0.0,
        ),
        "currency": "USD",
    }


@router.get("/system")
def system(_: dict = Depends(get_current_admin)) -> dict[str, Any]:
    gateway = get_gateway()
    health = gateway.health()
    cache_info = health.get("cache") or {}

    return {
        "gateway": {
            "name": settings.app_name,
            "version": settings.app_version,
            "status": health.get("status"),
            "provider": health.get("provider"),
            "model": health.get("model"),
        },
        "redis": {
            "connected": health.get("redis"),
            "host": settings.redis_host,
            "port": settings.redis_port,
            "index_name": cache_info.get("index_name"),
            "algorithm": cache_info.get("algorithm"),
            "distance_metric": cache_info.get(
                "distance_metric"
            ),
            "vector_dim": cache_info.get("vector_dim"),
            "size": health.get("cache_size"),
            "ping": cache_info.get("ping"),
        },
        "embedding": {
            "model": settings.embedding_model,
            "dimension": settings.vector_dimension,
        },
        "runtime": {
            "time": time.time(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "lifecycle": health.get("lifecycle"),
    }


@router.get("/settings")
def get_settings(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return _settings_view(user)


@router.get("/workspace")
def workspace(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "workspace": user.get("workspace"),
        "owner": {"id": user["id"], "email": user["email"]},
        "scope": "personal",
        "isolation": {
            "providers": "workspace",
            "cache": "workspace",
            "requests": "workspace",
            "usage": "workspace",
        },
    }


@router.patch("/settings")
def update_settings(
    payload: SettingsUpdate,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    gateway = get_gateway()
    changed = payload.model_dump(exclude_none=True)
    if "log_level" in changed:
        changed["log_level"] = str(changed["log_level"]).upper()
        if changed["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise HTTPException(status_code=422, detail="Unsupported log level")

    if settings.database_url:
        current = load_workspace_settings(user["workspace"]["id"])
        requested_provider = str(
            changed.get("default_provider", current.get("default_provider", settings.default_provider))
        ).strip().lower()
        requested_model = str(
            changed.get("default_model", current.get("default_model", settings.default_model))
        ).strip()
        if "default_provider" in changed or "default_model" in changed:
            available = any(
                item.provider.lower() == requested_provider
                and item.model == requested_model
                and item.enabled
                for item in WorkspaceProviderStore(user["workspace"]["id"]).capabilities().configured()
            )
            if not available:
                raise HTTPException(
                    status_code=400,
                    detail=f"Provider/model is not configured: {requested_provider}/{requested_model}",
                )
            changed["default_provider"] = requested_provider
            changed["default_model"] = requested_model
        save_runtime_settings(changed, workspace_id=user["workspace"]["id"])
        return _settings_view(user)

    requested_provider = str(changed.get("default_provider", settings.default_provider)).strip().lower()
    requested_model = str(changed.get("default_model", settings.default_model)).strip()
    if "default_provider" in changed or "default_model" in changed:
        capability_registry.refresh()
        available = any(
            item.provider.lower() == requested_provider
            and item.model == requested_model
            and item.enabled
            for item in capability_registry.configured()
        )
        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"Provider/model is not configured: {requested_provider}/{requested_model}",
            )
        changed["default_provider"] = requested_provider
        changed["default_model"] = requested_model

    for key, value in changed.items():
        setattr(settings, key, value)

    gateway.cache.similarity_threshold = float(settings.cache_threshold)
    gateway.cache.scorer.threshold = float(settings.cache_threshold)
    object.__setattr__(gateway.cache.policy, "semantic_enabled", bool(settings.semantic_cache_enabled))
    object.__setattr__(gateway.cache.policy, "exact_enabled", bool(settings.exact_cache_enabled))
    object.__setattr__(gateway.cache.policy, "ttl_seconds", int(settings.cache_ttl))
    object.__setattr__(gateway.cache.policy, "max_answer_length", int(settings.cache_max_answer_length))

    if "default_provider" in changed or "default_model" in changed:
        gateway.provider_name = requested_provider
        gateway.model_name = requested_model
        gateway.configured_model_name = requested_model
        gateway._providers.clear()
        try:
            gateway.provider = gateway._get_provider(requested_provider, requested_model)
        except Exception:
            gateway.provider = None

    if "log_level" in changed or "log_to_file" in changed or "log_file" in changed:
        _configure_logging()

    save_runtime_settings(changed, workspace_id=user["workspace"]["id"])

    return {
        "status": "ok",
        "changed": changed,
        "settings": _settings_view(),
    }


@router.post("/playground")
def playground(
    payload: PlaygroundRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
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
            workspace_id=workspace_id,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
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
