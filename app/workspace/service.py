from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.auth.database import get_connection, init_db
from app.config.settings import BASE_DIR
from app.db.postgres import postgres_configured


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_legacy_history(user_id: int, email: str) -> None:
    """Attach only records explicitly written with this user's email.

    Older single-user builds stored the email in gateway_history.user_id.
    Unknown test identifiers remain unowned instead of being exposed to a
    newly created account.
    """
    if postgres_configured() or not email:
        return
    path = BASE_DIR / "data" / "gateway.db"
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "UPDATE gateway_history SET user_id = ? WHERE user_id = ?",
            (str(user_id), email.strip().lower()),
        )
        conn.commit()
    except sqlite3.Error:
        # History recovery must never prevent login or workspace creation.
        pass
    finally:
        conn.close()


def ensure_personal_workspace(user_id: int, email: str = "") -> dict:
    init_db()
    _claim_legacy_history(int(user_id), email)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE owner_user_id = ?",
            (int(user_id),),
        ).fetchone()
        if row:
            return dict(row)
        now = _now()
        label = f"{email.split('@')[0]}'s Workspace" if email else "Personal Workspace"
        conn.execute(
            "INSERT INTO workspaces(owner_user_id,name,kind,created_at,updated_at) VALUES(?,?,?,?,?)",
            (int(user_id), label[:120], "personal", now, now),
        )
        row = conn.execute(
            "SELECT * FROM workspaces WHERE owner_user_id = ?",
            (int(user_id),),
        ).fetchone()
        return dict(row)


def get_workspace(user_id: int) -> dict:
    return ensure_personal_workspace(int(user_id))
