from __future__ import annotations

import hashlib

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from .database import (
    get_connection,
    init_db,
)

from .security import (
    create_reset_token,
    create_verification_token,
    hash_password,
    verify_password,
)
from app.workspace.service import ensure_personal_workspace
from app.db.postgres import postgres_configured


def _now() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def _user(row):

    if row is None:
        return None

    user = {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "is_active": bool(
            row["is_active"]
        ),
        "is_verified": bool(
            row["is_verified"]
        ),
        "is_admin": bool(
            row["is_admin"]
        ),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    user["workspace"] = ensure_personal_workspace(user["id"], user["email"])
    return user


def register(
    email: str,
    password: str,
    admin_email: str | None = None,
) -> dict:

    init_db()

    email = email.strip().lower()

    now = _now()

    is_admin = bool(
        admin_email
        and email == admin_email.strip().lower()
    )

    with get_connection() as conn:

        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

        if existing:
            raise ValueError(
                "Email already registered"
            )

        insert_sql = """
            INSERT INTO users
                (email, password_hash, is_active, is_verified, is_admin, created_at, updated_at)
            VALUES (?, ?, 1, 0, ?, ?, ?)
        """
        if postgres_configured():
            cur = conn.execute(
                insert_sql.replace("1, 0", "TRUE, FALSE") + " RETURNING id",
                (email, hash_password(password), bool(is_admin), now, now),
            )
            user_id = cur.fetchone()["id"]
        else:
            cur = conn.execute(insert_sql, (email, hash_password(password), int(is_admin), now, now))
            user_id = cur.lastrowid

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    return _user(row)


def authenticate(
    email: str,
    password: str,
) -> dict | None:

    init_db()

    email = email.strip().lower()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

    user = _user(row)

    if not user:
        return None

    if not user["is_active"]:
        return None

    if not user["is_verified"]:
        raise ValueError(
            "Email address has not been verified"
        )

    if not verify_password(
        password,
        user["password_hash"],
    ):
        return None

    return user


def get_user(
    user_id: int,
) -> dict | None:

    init_db()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    return _user(row)


def create_email_verification(
    user_id: int,
    expires_minutes: int = 30,
) -> str:

    init_db()

    raw_token, token_hash = (
        create_verification_token()
    )

    now = datetime.now(
        timezone.utc
    )

    expires = (
        now
        + timedelta(
            minutes=expires_minutes
        )
    )

    with get_connection() as conn:

        conn.execute(
            """
            UPDATE email_verification_tokens
            SET used = TRUE
            WHERE user_id = ?
              AND used = FALSE
            """,
            (user_id,),
        )

        conn.execute(
            """
            INSERT INTO email_verification_tokens
                (
                    user_id,
                    token_hash,
                    expires_at,
                    used,
                    created_at
                )
            VALUES (?, ?, ?, FALSE, ?)
            """,
            (
                user_id,
                token_hash,
                expires.isoformat(),
                now.isoformat(),
            ),
        )

    return raw_token


def verify_email(
    token: str,
) -> bool:

    init_db()

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    now = datetime.now(
        timezone.utc
    )

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT
                id,
                user_id,
                expires_at,
                used
            FROM email_verification_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if not row:
            return False

        if row["used"]:
            return False

        try:
            expires = datetime.fromisoformat(
                row["expires_at"]
            )
        except ValueError:
            return False

        if expires <= now:
            return False

        conn.execute(
            """
            UPDATE users
            SET
                is_verified = TRUE,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now.isoformat(),
                row["user_id"],
            ),
        )

        conn.execute(
            """
            UPDATE email_verification_tokens
            SET used = TRUE
            WHERE id = ?
            """,
            (row["id"],),
        )

    return True


def create_password_reset(
    email: str,
    expires_minutes: int = 30,
) -> str | None:

    init_db()

    email = email.strip().lower()

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

        if not row:
            return None

        raw_token, token_hash = (
            create_reset_token()
        )

        now = datetime.now(
            timezone.utc
        )

        expires = (
            now
            + timedelta(
                minutes=expires_minutes
            )
        )

        conn.execute(
            """
            UPDATE password_reset_tokens
            SET used = TRUE
            WHERE user_id = ?
              AND used = FALSE
            """,
            (row["id"],),
        )

        conn.execute(
            """
            INSERT INTO password_reset_tokens
                (
                    user_id,
                    token_hash,
                    expires_at,
                    used,
                    created_at
                )
            VALUES (?, ?, ?, FALSE, ?)
            """,
            (
                row["id"],
                token_hash,
                expires.isoformat(),
                now.isoformat(),
            ),
        )

    return raw_token


def reset_password(
    token: str,
    new_password: str,
) -> bool:

    init_db()

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    now = datetime.now(
        timezone.utc
    )

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT
                id,
                user_id,
                expires_at,
                used
            FROM password_reset_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if not row:
            return False

        if row["used"]:
            return False

        try:
            expires = datetime.fromisoformat(
                row["expires_at"]
            )
        except ValueError:
            return False

        if expires <= now:
            return False

        conn.execute(
            """
            UPDATE users
            SET
                password_hash = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                hash_password(new_password),
                now.isoformat(),
                row["user_id"],
            ),
        )

        conn.execute(
            """
            UPDATE password_reset_tokens
            SET used = TRUE
            WHERE id = ?
            """,
            (row["id"],),
        )

    return True
