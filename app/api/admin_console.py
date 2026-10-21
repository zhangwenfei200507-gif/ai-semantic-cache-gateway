from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.database import get_connection, init_db
from app.auth.dependencies import get_current_admin
from app.config.settings import settings
from app.gateway import get_gateway
from app.history.repository import history_repository


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _safe_number(value: Any) -> int | float:
    if value is None:
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _auth_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, str], dict[int, str]]:
    """Read non-sensitive account metadata from the configured auth database."""
    init_db()
    with get_connection() as conn:
        users = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, email, is_active, is_verified, is_admin,
                       created_at, updated_at
                FROM users
                ORDER BY id
                """
            ).fetchall()
        ]
        workspaces = [dict(row) for row in conn.execute("SELECT * FROM workspaces ORDER BY id").fetchall()]
        last_login: dict[int, str] = {}
        try:
            for row in conn.execute(
                "SELECT user_id, MAX(last_login_at) AS last_login_at FROM oauth_accounts GROUP BY user_id"
            ).fetchall():
                last_login[int(row["user_id"])] = row["last_login_at"]
        except Exception:
            # Very old local auth databases may not have OAuth metadata yet.
            pass
    workspace_names = {int(item["id"]): str(item.get("name") or "") for item in workspaces}
    workspace_owners = {int(item["id"]): int(item["owner_user_id"]) for item in workspaces}
    for user in users:
        user["id"] = int(user["id"])
        user["is_active"] = bool(user["is_active"])
        user["is_verified"] = bool(user["is_verified"])
        user["is_admin"] = bool(user["is_admin"])
    return users, workspaces, workspace_names, last_login


def _history_snapshot() -> list[dict[str, Any]]:
    try:
        # The admin view is intentionally bounded. The persisted count remains
        # available in overview, while charts avoid unbounded memory growth.
        return history_repository.list(limit=100_000)
    except Exception as exc:
        logger.warning("admin_history_read_failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Admin history is temporarily unavailable") from exc


def _provider_counts() -> dict[int, int]:
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT workspace_id, COUNT(*) AS count FROM providers WHERE workspace_id IS NOT NULL GROUP BY workspace_id"
            ).fetchall()
        return {int(row["workspace_id"]): int(row["count"]) for row in rows}
    except Exception:
        # Local SQLite keeps provider metadata in the legacy configuration
        # path; production PostgreSQL exposes this table.
        return {}


def _user_history(user_id: int, workspace_ids: set[int], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_text = str(user_id)
    result = []
    seen: set[str] = set()
    for item in history:
        request_id = str(item.get("request_id") or item.get("id") or "")
        matches = str(item.get("user_id") or "") == user_text
        workspace = item.get("workspace_id")
        try:
            matches = matches or int(workspace) in workspace_ids
        except (TypeError, ValueError):
            pass
        if matches and request_id not in seen:
            seen.add(request_id)
            result.append(item)
    return result


def _user_view(
    user: dict[str, Any],
    workspace_ids_by_user: dict[int, set[int]],
    workspace_names: dict[int, str],
    last_login: dict[int, str],
    history: list[dict[str, Any]],
    provider_counts: dict[int, int],
) -> dict[str, Any]:
    user_id = int(user["id"])
    workspace_ids = workspace_ids_by_user.get(user_id, set())
    records = _user_history(user_id, workspace_ids, history)
    last_active = last_login.get(user_id)
    for item in records:
        candidate = item.get("created_at")
        if _parse_time(candidate) and (not last_active or _parse_time(candidate) > _parse_time(last_active)):
            last_active = candidate
    tokens = sum(int(item.get("total_tokens") or 0) for item in records)
    cost = sum(float(item.get("cost") or 0) for item in records)
    workspace_rows = [
        {"id": workspace_id, "name": workspace_names.get(workspace_id, "Workspace")}
        for workspace_id in sorted(workspace_ids)
    ]
    now = datetime.now(timezone.utc)
    active_at = _parse_time(last_active)
    online = bool(active_at and active_at >= now - timedelta(minutes=15))
    if not user["is_active"]:
        status = "disabled"
    elif not user["is_verified"]:
        status = "pending"
    else:
        status = "active"
    return {
        "id": user_id,
        "email": user["email"],
        "is_active": user["is_active"],
        "is_verified": user["is_verified"],
        "is_admin": user["is_admin"],
        "status": status,
        "created_at": user["created_at"],
        "updated_at": user.get("updated_at"),
        "last_active_at": last_active,
        "online_estimate": online,
        "workspace_count": len(workspace_rows),
        "provider_count": sum(provider_counts.get(workspace_id, 0) for workspace_id in workspace_ids),
        "request_count": len(records),
        "total_tokens": tokens,
        "estimated_cost": cost,
        "workspaces": workspace_rows,
    }


def _snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[int, int]]:
    users, workspaces, workspace_names, last_login = _auth_snapshot()
    history = _history_snapshot()
    workspace_ids_by_user: dict[int, set[int]] = defaultdict(set)
    for workspace in workspaces:
        workspace_ids_by_user[int(workspace["owner_user_id"])].add(int(workspace["id"]))
    provider_counts = _provider_counts()
    views = [
        _user_view(user, workspace_ids_by_user, workspace_names, last_login, history, provider_counts)
        for user in users
    ]
    return views, workspaces, history, provider_counts


def _audit(user: dict[str, Any], action: str) -> None:
    logger.info("admin_access user_id=%s action=%s", int(user["id"]), action)


@router.get("/overview")
def overview(admin: dict = Depends(get_current_admin)) -> dict[str, Any]:
    _audit(admin, "overview")
    users, workspaces, history, _ = _snapshot()
    hits = sum(1 for item in history if item.get("cache_hit"))
    now = datetime.now(timezone.utc)
    online = sum(1 for user in users if user["online_estimate"])
    return {
        "users": {
            "total": len(users),
            "active": sum(1 for user in users if user["is_active"]),
            "verified": sum(1 for user in users if user["is_verified"]),
            "online_estimate": online,
            "online_window_minutes": 15,
        },
        "workspaces": {"total": len(workspaces)},
        "requests": {
            "total": len(history),
            "cache_hits": hits,
            "cache_hit_rate": round(hits / len(history) * 100, 2) if history else 0,
            "since": min((item.get("created_at") for item in history if item.get("created_at")), default=None),
            "as_of": now.isoformat(),
        },
        "usage": {
            "total_tokens": sum(int(item.get("total_tokens") or 0) for item in history),
            "estimated_cost": sum(float(item.get("cost") or 0) for item in history),
            "saved_cost": sum(float(item.get("saved_cost") or 0) for item in history),
        },
    }


@router.get("/users")
def users(
    q: str = Query(default="", max_length=120),
    status: str = Query(default="all", pattern="^(all|active|pending|disabled)$"),
    sort: str = Query(default="created_at", pattern="^(created_at|email|requests|tokens|last_active)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
) -> dict[str, Any]:
    _audit(admin, "users")
    records, _, history, _ = _snapshot()
    needle = q.strip().lower()
    records = [item for item in records if not needle or needle in str(item["email"]).lower() or needle == str(item["id"])]
    if status != "all":
        records = [item for item in records if item["status"] == status]
    key_map = {
        "created_at": lambda item: _parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
        "email": lambda item: str(item.get("email") or "").lower(),
        "requests": lambda item: int(item.get("request_count") or 0),
        "tokens": lambda item: int(item.get("total_tokens") or 0),
        "last_active": lambda item: _parse_time(item.get("last_active_at")) or datetime.min.replace(tzinfo=timezone.utc),
    }
    records.sort(key=key_map[sort], reverse=order == "desc")
    total = len(records)
    start = (page - 1) * page_size
    return {
        "items": records[start:start + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size},
        "history_loaded": len(history),
    }


@router.get("/users/{user_id}")
def user_detail(user_id: int, admin: dict = Depends(get_current_admin)) -> dict[str, Any]:
    _audit(admin, "user_detail")
    records, workspaces, history, provider_counts = _snapshot()
    record = next((item for item in records if item["id"] == user_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="User not found")

    workspace_ids = {int(item["id"]) for item in record["workspaces"]}
    providers: list[dict[str, Any]] = []
    try:
        with get_connection() as conn:
            provider_rows = conn.execute(
                """
                SELECT p.id, p.workspace_id, p.name, p.display_name, p.role,
                       p.status, p.enabled, p.default_model,
                       COUNT(m.id) AS model_count
                FROM providers p
                LEFT JOIN provider_models m ON m.provider_id = p.id
                WHERE p.workspace_id = ANY(?)
                GROUP BY p.id
                ORDER BY p.id
                """,
                (list(workspace_ids),),
            ).fetchall()
            providers = [dict(row) for row in provider_rows]
    except Exception:
        # SQLite development mode has no workspace provider tables; the
        # detail response still remains useful and contains no credentials.
        providers = []
    return {
        "user": record,
        "workspaces": [item for item in workspaces if int(item["id"]) in workspace_ids],
        "providers": providers,
        "request_summary": {
            "total": record["request_count"],
            "tokens": record["total_tokens"],
            "estimated_cost": record["estimated_cost"],
            "recent": [
                {
                    "request_id": item.get("request_id"),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "cache_hit": bool(item.get("cache_hit")),
                    "total_tokens": int(item.get("total_tokens") or 0),
                    "cost": float(item.get("cost") or 0),
                    "status": item.get("status"),
                    "created_at": item.get("created_at"),
                }
                for item in _user_history(user_id, workspace_ids, history)[:20]
            ],
        },
        "provider_count": sum(provider_counts.get(workspace_id, 0) for workspace_id in workspace_ids),
    }


def _bucket_time(value: Any, period: str) -> datetime | None:
    moment = _parse_time(value)
    if not moment:
        return None
    if period == "24h":
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/analytics")
def analytics(
    period: str = Query(default="7d", pattern="^(24h|7d|30d)$"),
    admin: dict = Depends(get_current_admin),
) -> dict[str, Any]:
    _audit(admin, "analytics")
    users, _, history, _ = _snapshot()
    duration = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}[period]
    cutoff = datetime.now(timezone.utc) - duration
    records = [item for item in history if (_parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    buckets: dict[str, dict[str, Any]] = {}
    active_users: dict[str, set[str]] = defaultdict(set)
    for item in records:
        bucket = _bucket_time(item.get("created_at"), period)
        if not bucket:
            continue
        key = bucket.isoformat()
        row = buckets.setdefault(key, {"bucket": key, "requests": 0, "errors": 0, "hits": 0, "tokens": 0, "cost": 0.0})
        row["requests"] += 1
        row["errors"] += int(str(item.get("status") or "").lower() == "error" or bool(item.get("error")))
        row["hits"] += int(bool(item.get("cache_hit")))
        row["tokens"] += int(item.get("total_tokens") or 0)
        row["cost"] += float(item.get("cost") or 0)
        active_users[key].add(str(item.get("user_id") or item.get("workspace_id") or "unknown"))
    provider_usage: dict[str, dict[str, Any]] = defaultdict(lambda: {"provider": "", "requests": 0, "tokens": 0, "cost": 0.0})
    for item in records:
        provider = str(item.get("provider") or "unknown")
        row = provider_usage[provider]
        row["provider"] = provider
        row["requests"] += 1
        row["tokens"] += int(item.get("total_tokens") or 0)
        row["cost"] += float(item.get("cost") or 0)
    user_growth = []
    for user in users:
        moment = _parse_time(user.get("created_at"))
        if moment and moment >= cutoff:
            bucket = _bucket_time(moment, period)
            if bucket:
                user_growth.append(bucket.isoformat())
    growth_counts: dict[str, int] = defaultdict(int)
    for key in user_growth:
        growth_counts[key] += 1
    ordered = [buckets[key] for key in sorted(buckets)]
    return {
        "period": period,
        "request_volume": ordered,
        "token_consumption": [{"bucket": row["bucket"], "tokens": row["tokens"], "cost": row["cost"]} for row in ordered],
        "cache_performance": [{"bucket": row["bucket"], "hits": row["hits"], "misses": row["requests"] - row["hits"]} for row in ordered],
        "daily_active_users": [{"bucket": key, "users": len(active_users[key])} for key in sorted(active_users)],
        "user_growth": [{"bucket": key, "users": growth_counts[key]} for key in sorted(growth_counts)],
        "provider_usage": [provider_usage[key] for key in sorted(provider_usage)],
    }


@router.get("/health")
def admin_health(admin: dict = Depends(get_current_admin)) -> dict[str, Any]:
    _audit(admin, "health")
    gateway = get_gateway()
    try:
        gateway_health = gateway.health()
    except Exception:
        gateway_health = {"status": "degraded", "redis": False}
    database = False
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        database = True
    except Exception:
        pass
    embedding = False
    try:
        embedding = bool(gateway.cache.embedding_service.is_ready)
    except Exception:
        pass
    return {
        "gateway": {"status": gateway_health.get("status"), "provider": gateway_health.get("provider"), "model": gateway_health.get("model")},
        "database": {"backend": "postgres" if settings.database_url else "sqlite", "ready": database},
        "redis": {"ready": bool(gateway_health.get("redis")), "cache_size": gateway_health.get("cache_size", 0)},
        "embedding": {"ready": embedding, "model": settings.embedding_model},
        "storage": {"backend": settings.image_storage_backend, "configured": bool(settings.s3_bucket) if settings.image_storage_backend == "s3" else True},
    }


__all__ = ["router"]
