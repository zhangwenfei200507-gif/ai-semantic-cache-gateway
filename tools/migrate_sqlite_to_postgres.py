from __future__ import annotations

import argparse
import hashlib
import json
import sys
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.postgres import direct_connection
from app.db.schema import apply_schema


DEFAULT_AUTH = ROOT / "config" / "auth.db"
DEFAULT_HISTORY = ROOT / "data" / "gateway.db"
RUNTIME_SETTINGS = ROOT / "config" / "runtime_settings.json"
RUN_PREFIX = "sqlite-stage2-"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decimal_text(value: Any) -> str:
    number = Decimal(str(value or 0))
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def scalar_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        return Decimal(str(left)) == Decimal(str(right))
    return left == right


def sqlite_rows(path: Path, query: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def inspect_sources(auth_path: Path, history_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "auth_sha256": sha256(auth_path),
        "history_sha256": sha256(history_path),
    }
    for path in (auth_path, history_path):
        conn = sqlite3.connect(str(path))
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {path}")
        finally:
            conn.close()

    users = sqlite_rows(auth_path, "SELECT * FROM users ORDER BY id")
    workspaces = sqlite_rows(auth_path, "SELECT * FROM workspaces ORDER BY id")
    verification = sqlite_rows(auth_path, "SELECT * FROM email_verification_tokens ORDER BY id")
    resets = sqlite_rows(auth_path, "SELECT * FROM password_reset_tokens ORDER BY id")
    history = sqlite_rows(history_path, "SELECT * FROM gateway_history ORDER BY id")
    by_email = {str(row["email"]).strip().lower(): row for row in users}
    by_id = {str(row["id"]): row for row in users}
    workspace_by_owner = {int(row["owner_user_id"]): row for row in workspaces}

    mapped = 0
    unassigned = 0
    mapping_types: dict[str, int] = {}
    mapped_values: set[str] = set()
    for row in history:
        raw = "" if row.get("user_id") is None else str(row["user_id"]).strip()
        match_type = None
        if raw.isdigit() and raw in by_id:
            match_type = "numeric_id"
        elif raw and raw.lower() in by_email:
            match_type = "email"
        if match_type:
            mapped += 1
            mapped_values.add(raw)
            mapping_types[match_type] = mapping_types.get(match_type, 0) + 1
        else:
            unassigned += 1

    result["counts"] = {
        "users": len(users),
        "workspaces": len(workspaces),
        "email_verification_tokens": len(verification),
        "password_reset_tokens": len(resets),
        "gateway_history": len(history),
        "mapped_history": mapped,
        "mapped_legacy_values": len(mapped_values),
        "unassigned_history": unassigned,
        "mapping_types": mapping_types,
    }
    result["aggregates"] = {
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in history),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in history),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in history),
        "cost": decimal_text(sum(Decimal(str(row.get("cost") or 0)) for row in history)),
        "saved_cost": decimal_text(sum(Decimal(str(row.get("saved_cost") or 0)) for row in history)),
    }
    return result


def _table_count(conn, table: str) -> int:
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchone()
    if not exists:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def target_state(database_url: str) -> dict[str, Any]:
    with direct_connection(database_url) as conn:
        return {
            "schema_migrations": _table_count(conn, "schema_migrations"),
            "users": _table_count(conn, "users"),
            "workspaces": _table_count(conn, "workspaces"),
            "gateway_history": _table_count(conn, "gateway_history"),
            "migration_runs": _table_count(conn, "migration_runs"),
        }


def _mapping(history_row: dict[str, Any], by_id: dict[str, dict], by_email: dict[str, dict], workspace_by_owner: dict[int, dict]):
    raw = "" if history_row.get("user_id") is None else str(history_row["user_id"]).strip()
    user = None
    match_type = None
    if raw.isdigit() and raw in by_id:
        user = by_id[raw]
        match_type = "numeric_id"
    elif raw and raw.lower() in by_email:
        user = by_email[raw.lower()]
        match_type = "email"
    if user:
        owner_id = int(user["id"])
        workspace = workspace_by_owner.get(owner_id)
        return str(owner_id), int(workspace["id"]) if workspace else None, raw, match_type
    return (raw or None), None, raw or None, None


def _load_runtime_settings() -> dict[str, Any]:
    if not RUNTIME_SETTINGS.exists():
        return {}
    try:
        value = json.loads(RUNTIME_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    allowed = {
        "app_name", "default_provider", "default_model", "deepseek_models", "openai_models",
        "qwen_image_models", "llm_timeout", "llm_max_retries", "cache_threshold", "cache_ttl",
        "semantic_cache_enabled", "exact_cache_enabled", "cache_max_answer_length", "log_level",
        "log_to_file", "log_file", "auth_token_expiration_hours", "notifications_enabled",
    }
    return {key: item for key, item in value.items() if key in allowed}


def migrate(database_url: str, auth_path: Path, history_path: Path, source: dict[str, Any]) -> dict[str, Any]:
    apply_schema(database_url)
    users = sqlite_rows(auth_path, "SELECT * FROM users ORDER BY id")
    workspaces = sqlite_rows(auth_path, "SELECT * FROM workspaces ORDER BY id")
    verification = sqlite_rows(auth_path, "SELECT * FROM email_verification_tokens ORDER BY id")
    resets = sqlite_rows(auth_path, "SELECT * FROM password_reset_tokens ORDER BY id")
    history = sqlite_rows(history_path, "SELECT * FROM gateway_history ORDER BY id")
    by_id = {str(row["id"]): row for row in users}
    by_email = {str(row["email"]).strip().lower(): row for row in users}
    workspace_by_owner = {int(row["owner_user_id"]): row for row in workspaces}
    run_id = RUN_PREFIX + source["auth_sha256"][:16] + source["history_sha256"][:16]
    started = now()
    details = {"source_counts": source["counts"], "source_aggregates": source["aggregates"]}

    with direct_connection(database_url) as conn:
        existing_run = conn.execute("SELECT status FROM migration_runs WHERE run_id = %s", (run_id,)).fetchone()
        if not existing_run:
            conn.execute(
                "INSERT INTO migration_runs(run_id, source_auth_sha256, source_history_sha256, status, details, started_at) VALUES(%s, %s, %s, %s, %s, %s)",
                (run_id, source["auth_sha256"], source["history_sha256"], "running", Jsonb(details), started),
            )
            conn.commit()
        elif existing_run["status"] == "running":
            conn.execute("UPDATE migration_runs SET status = 'running', started_at = %s WHERE run_id = %s", (started, run_id))
            conn.commit()

        try:
            for row in users:
                conn.execute(
                    """
                    INSERT INTO users(id,email,password_hash,is_active,is_verified,is_admin,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (row["id"], row["email"], row["password_hash"], bool(row["is_active"]), bool(row["is_verified"]), bool(row["is_admin"]), row["created_at"], row["updated_at"]),
                )
            for row in workspaces:
                conn.execute(
                    """
                    INSERT INTO workspaces(id,owner_user_id,name,kind,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (row["id"], row["owner_user_id"], row["name"], row["kind"], row["created_at"], row["updated_at"]),
                )
                conn.execute(
                    """
                    INSERT INTO workspace_members(workspace_id,user_id,role,created_at)
                    VALUES(%s,%s,'owner',%s)
                    ON CONFLICT(workspace_id,user_id) DO NOTHING
                    """,
                    (row["id"], row["owner_user_id"], row["created_at"]),
                )
            for row in verification:
                conn.execute(
                    """
                    INSERT INTO email_verification_tokens(id,user_id,token_hash,expires_at,used,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (row["id"], row["user_id"], row["token_hash"], row["expires_at"], bool(row["used"]), row["created_at"]),
                )
            for row in resets:
                conn.execute(
                    """
                    INSERT INTO password_reset_tokens(id,user_id,token_hash,expires_at,used,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (row["id"], row["user_id"], row["token_hash"], row["expires_at"], bool(row["used"]), row["created_at"]),
                )
            runtime = Jsonb(_load_runtime_settings())
            for workspace in workspaces:
                conn.execute(
                    """
                    INSERT INTO workspace_settings(workspace_id,settings_json,version,updated_at)
                    VALUES(%s,%s,1,%s)
                    ON CONFLICT(workspace_id) DO NOTHING
                    """,
                    (workspace["id"], runtime, now()),
                )
            for row in history:
                user_id, workspace_id, raw_user_id, match_type = _mapping(row, by_id, by_email, workspace_by_owner)
                conn.execute(
                    """
                    INSERT INTO gateway_history
                    (id,request_id,user_id,workspace_id,legacy_user_id,provider,model,question,answer,cache_hit,cache_type,similarity,threshold,
                     prompt_tokens,completion_tokens,total_tokens,cost,saved_cost,latency_ms,provider_latency_ms,status,error,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(request_id) DO NOTHING
                    """,
                    (row["id"], row["request_id"], user_id, workspace_id, raw_user_id if match_type == "email" else None,
                     row["provider"], row["model"], row["question"], row["answer"], bool(row["cache_hit"]), row["cache_type"], row["similarity"], row["threshold"],
                     row["prompt_tokens"] or 0, row["completion_tokens"] or 0, row["total_tokens"] or 0, row["cost"] or 0, row["saved_cost"] or 0,
                     row["latency_ms"] or 0, row["provider_latency_ms"] or 0, row["status"] or "success", row["error"], row["created_at"] or ""),
                )
                if match_type:
                    mapped_user = by_email[raw_user_id.lower()] if match_type == "email" else by_id[raw_user_id]
                    mapped_workspace = workspace_by_owner.get(int(mapped_user["id"]))
                    conn.execute(
                        """
                        INSERT INTO legacy_user_mapping(legacy_value,user_id,workspace_id,match_type,created_at)
                        VALUES(%s,%s,%s,%s,%s)
                        ON CONFLICT(legacy_value) DO NOTHING
                        """,
                        (raw_user_id, mapped_user["id"], mapped_workspace["id"] if mapped_workspace else None, match_type, now()),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO legacy_unassigned_records(request_id,raw_user_id,reason,created_at)
                        VALUES(%s,%s,%s,%s)
                        ON CONFLICT(request_id) DO NOTHING
                        """,
                        (row["request_id"], raw_user_id or None, "empty_or_unmatched_user_id", now()),
                    )
            for table, column in (("users", "id"), ("workspaces", "id"), ("email_verification_tokens", "id"), ("password_reset_tokens", "id"), ("providers", "id"), ("provider_models", "id"), ("provider_credentials", "id")):
                conn.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), COALESCE(MAX({column}), 1), MAX({column}) IS NOT NULL) FROM {table}"
                )
            details["completed_at"] = now()
            conn.execute(
                "UPDATE migration_runs SET status = 'completed', details = %s, completed_at = %s WHERE run_id = %s",
                (Jsonb(details), details["completed_at"], run_id),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            with direct_connection(database_url) as failed_conn:
                failed_conn.execute(
                    "UPDATE migration_runs SET status = 'failed', details = details || %s, completed_at = %s WHERE run_id = %s",
                    (Jsonb({"error": str(exc)}), now(), run_id),
                )
                failed_conn.commit()
            raise

    return {"run_id": run_id, "status": "completed", "source": source}


def verify(database_url: str, auth_path: Path, history_path: Path) -> dict[str, Any]:
    source = inspect_sources(auth_path, history_path)
    source_workspaces = sqlite_rows(auth_path, "SELECT id,owner_user_id,name,kind,created_at,updated_at FROM workspaces ORDER BY id")
    source_verification = sqlite_rows(auth_path, "SELECT id,user_id,token_hash,expires_at,used,created_at FROM email_verification_tokens ORDER BY id")
    source_resets = sqlite_rows(auth_path, "SELECT id,user_id,token_hash,expires_at,used,created_at FROM password_reset_tokens ORDER BY id")
    source_history = sqlite_rows(history_path, "SELECT * FROM gateway_history ORDER BY id")
    with direct_connection(database_url) as conn:
        actual = {
            "users": _table_count(conn, "users"),
            "workspaces": _table_count(conn, "workspaces"),
            "workspace_settings": _table_count(conn, "workspace_settings"),
            "email_verification_tokens": _table_count(conn, "email_verification_tokens"),
            "password_reset_tokens": _table_count(conn, "password_reset_tokens"),
            "gateway_history": _table_count(conn, "gateway_history"),
            "legacy_user_mapping": _table_count(conn, "legacy_user_mapping"),
            "legacy_unassigned_records": _table_count(conn, "legacy_unassigned_records"),
        }
        aggregate_row = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, COALESCE(SUM(completion_tokens),0) AS completion_tokens, COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(cost),0) AS cost, COALESCE(SUM(saved_cost),0) AS saved_cost FROM gateway_history"
        ).fetchone()
        aggregate = {
            "prompt_tokens": int(aggregate_row["prompt_tokens"]),
            "completion_tokens": int(aggregate_row["completion_tokens"]),
            "total_tokens": int(aggregate_row["total_tokens"]),
            "cost": decimal_text(aggregate_row["cost"]),
            "saved_cost": decimal_text(aggregate_row["saved_cost"]),
        }
        request_ids = {row["request_id"] for row in conn.execute("SELECT request_id FROM gateway_history").fetchall()}
        source_ids = {row["request_id"] for row in sqlite_rows(history_path, "SELECT request_id FROM gateway_history")}
        users = conn.execute("SELECT id,email,password_hash,is_active,is_verified,is_admin,created_at,updated_at FROM users ORDER BY id").fetchall()
        source_users = sqlite_rows(auth_path, "SELECT id,email,password_hash,is_active,is_verified,is_admin,created_at,updated_at FROM users ORDER BY id")
        users_match = [dict(row) for row in users] == source_users
        workspaces = [dict(row) for row in conn.execute("SELECT id,owner_user_id,name,kind,created_at,updated_at FROM workspaces ORDER BY id").fetchall()]
        workspace_match = workspaces == source_workspaces
        verification = [dict(row) for row in conn.execute("SELECT id,user_id,token_hash,expires_at,used,created_at FROM email_verification_tokens ORDER BY id").fetchall()]
        verification_match = verification == source_verification
        resets = [dict(row) for row in conn.execute("SELECT id,user_id,token_hash,expires_at,used,created_at FROM password_reset_tokens ORDER BY id").fetchall()]
        reset_match = resets == source_resets
        target_history = [dict(row) for row in conn.execute("SELECT * FROM gateway_history ORDER BY id").fetchall()]
        target_settings = [row["settings_json"] for row in conn.execute("SELECT settings_json FROM workspace_settings").fetchall()]

    history_fields = (
        "id", "request_id", "provider", "model", "question", "answer", "cache_hit", "cache_type",
        "similarity", "threshold", "prompt_tokens", "completion_tokens", "total_tokens", "cost",
        "saved_cost", "latency_ms", "provider_latency_ms", "status", "error", "created_at",
    )
    history_fields_match = len(target_history) == len(source_history) and all(
        all(scalar_equal(target.get(field), source_row.get(field)) for field in history_fields)
        for target, source_row in zip(target_history, source_history)
    )
    runtime = _load_runtime_settings()
    settings_match = len(target_settings) == source["counts"]["workspaces"] and all(
        item == runtime for item in target_settings
    )
    expected = {
        "users": source["counts"]["users"],
        "workspaces": source["counts"]["workspaces"],
        "workspace_settings": source["counts"]["workspaces"],
        "email_verification_tokens": source["counts"]["email_verification_tokens"],
        "password_reset_tokens": source["counts"]["password_reset_tokens"],
        "gateway_history": source["counts"]["gateway_history"],
        "legacy_user_mapping": source["counts"]["mapped_legacy_values"],
        "legacy_unassigned_records": source["counts"]["unassigned_history"],
    }
    aggregates_match = all(
        Decimal(str(aggregate[key])) == Decimal(str(source["aggregates"][key]))
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost", "saved_cost")
    )
    result = {
        "source_sha256": {"auth": source["auth_sha256"], "history": source["history_sha256"]},
        "expected_counts": expected,
        "actual_counts": actual,
        "counts_match": actual == expected,
        "expected_aggregates": source["aggregates"],
        "actual_aggregates": aggregate,
        "aggregates_match": aggregates_match,
        "request_ids_match": request_ids == source_ids,
        "users_match": users_match,
        "workspaces_match": workspace_match,
        "verification_tokens_match": verification_match,
        "password_reset_tokens_match": reset_match,
        "history_fields_match": history_fields_match,
        "workspace_settings_match": settings_match,
    }
    result["ok"] = all((
        result["counts_match"], aggregates_match, result["request_ids_match"], users_match,
        workspace_match, verification_match, reset_match, history_fields_match, settings_match,
    ))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe, repeatable SQLite to PostgreSQL migration")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--mode", choices=("dry-run", "migrate", "verify"), default="dry-run")
    parser.add_argument("--auth-db", type=Path, default=DEFAULT_AUTH)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY)
    args = parser.parse_args()
    for path in (args.auth_db, args.history_db):
        if not path.exists():
            raise SystemExit(f"Source SQLite database not found: {path}")
    source = inspect_sources(args.auth_db, args.history_db)
    if args.mode == "dry-run":
        result = {"mode": args.mode, "source": source, "target": target_state(args.database_url), "schema": apply_schema(args.database_url, dry_run=True)}
    elif args.mode == "migrate":
        result = {"mode": args.mode, **migrate(args.database_url, args.auth_db, args.history_db, source)}
    else:
        result = {"mode": args.mode, **verify(args.database_url, args.auth_db, args.history_db)}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise

