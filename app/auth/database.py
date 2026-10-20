from __future__ import annotations

import sqlite3

from app.config.settings import BASE_DIR
from app.db.postgres import get_postgres_connection, postgres_configured


DB_PATH = BASE_DIR / "config" / "auth.db"


def get_connection():
    if postgres_configured():
        return get_postgres_connection()

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row

    return conn


def _column_exists(
    conn: sqlite3.Connection,
    table: str,
    column: str,
) -> bool:
    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(
        row["name"] == column
        for row in rows
    )


def init_db() -> None:
    if postgres_configured():
        from app.db.schema import require_schema

        require_schema()
        return

    with get_connection() as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_verified INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'personal',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner_user_id) REFERENCES users(id)
            )
            """
        )

        # ------------------------------------------------------
        # Migration for existing databases
        # ------------------------------------------------------

        if not _column_exists(
            conn,
            "users",
            "is_verified",
        ):
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0
                """
            )

        if not _column_exists(
            conn,
            "users",
            "is_admin",
        ):
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0
                """
            )

        # ------------------------------------------------------
        # Email verification tokens
        # ------------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # ------------------------------------------------------
        # Password reset tokens
        # ------------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # ------------------------------------------------------
        # Indexes
        # ------------------------------------------------------

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workspaces_owner
            ON workspaces(owner_user_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_verification_token_hash
            ON email_verification_tokens(token_hash)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reset_token_hash
            ON password_reset_tokens(token_hash)
            """
        )

        conn.commit()
