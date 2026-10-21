from __future__ import annotations

from datetime import datetime, timezone

from app.db.postgres import postgres_configured
from app.workspace.service import ensure_personal_workspace

from .database import get_connection, init_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(row) -> dict | None:
    if row is None:
        return None

    user = {
        "id": row["id"],
        "email": row["email"],
        "is_active": bool(row["is_active"]),
        "is_verified": True,
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    user["workspace"] = ensure_personal_workspace(user["id"], user["email"])
    return user


def get_user(user_id: int) -> dict | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row is not None:
            oauth_account = conn.execute(
                "SELECT 1 FROM oauth_accounts WHERE user_id = ? LIMIT 1",
                (int(user_id),),
            ).fetchone()
            if oauth_account is None:
                return None
    return _user(row)


def _insert_user(conn, email: str, now: str) -> dict:
    if postgres_configured():
        row = conn.execute(
            """
            INSERT INTO users
                (email, password_hash, is_active, is_verified, is_admin, created_at, updated_at)
            VALUES (?, NULL, TRUE, TRUE, FALSE, ?, ?)
            RETURNING *
            """,
            (email, now, now),
        ).fetchone()
        return row

    cur = conn.execute(
        """
        INSERT INTO users
            (email, password_hash, is_active, is_verified, is_admin, created_at, updated_at)
        VALUES (?, '', 1, 1, 0, ?, ?)
        """,
        (email, now, now),
    )
    return conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()


def authenticate_oauth(
    provider: str,
    provider_subject: str,
    email: str,
    email_verified: bool,
) -> dict:
    """Link a verified OAuth identity to an existing user or create one."""

    if not email_verified:
        raise ValueError("The identity provider did not verify this email address")

    provider = str(provider).strip().lower()
    provider_subject = str(provider_subject).strip()
    email = str(email).strip().lower()
    if provider not in {"github", "google"} or not provider_subject or not email:
        raise ValueError("Invalid OAuth identity")

    init_db()
    now = _now()
    with get_connection() as conn:
        linked = conn.execute(
            """
            SELECT u.*
            FROM oauth_accounts a
            JOIN users u ON u.id = a.user_id
            WHERE a.provider = ? AND a.provider_subject = ?
            """,
            (provider, provider_subject),
        ).fetchone()

        if linked is None:
            existing = conn.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(?)",
                (email,),
            ).fetchone()
            if existing is None:
                user = _insert_user(conn, email, now)
                user_id = int(user["id"])
            else:
                user_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE users
                    SET email = ?, is_active = TRUE, is_verified = TRUE, updated_at = ?
                    WHERE id = ?
                    """,
                    (email, now, user_id),
                )

            conn.execute(
                """
                INSERT INTO oauth_accounts
                    (user_id, provider, provider_subject, email, email_verified, created_at, last_login_at)
                VALUES (?, ?, ?, ?, TRUE, ?, ?)
                """,
                (user_id, provider, provider_subject, email, now, now),
            )
            linked = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        else:
            conn.execute(
                """
                UPDATE oauth_accounts
                SET email = ?, email_verified = TRUE, last_login_at = ?
                WHERE provider = ? AND provider_subject = ?
                """,
                (email, now, provider, provider_subject),
            )
            conn.execute(
                "UPDATE users SET email = ?, is_verified = TRUE, updated_at = ? WHERE id = ?",
                (email, now, int(linked["id"])),
            )
            linked = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (int(linked["id"]),),
            ).fetchone()

        conn.commit()

    return _user(linked)


__all__ = [
    "authenticate_oauth",
    "get_user",
]
