from __future__ import annotations

import sqlite3

from app.config.settings import BASE_DIR
from app.db.postgres import get_postgres_connection, postgres_configured


DB_PATH = BASE_DIR / "config" / "auth.db"


class _SQLiteConnection(sqlite3.Connection):
    """Close local SQLite connections when their context manager exits."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


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
        factory=_SQLiteConnection,
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
                password_hash TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_verified INTEGER NOT NULL DEFAULT 1,
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
        # OAuth migration
        # ------------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                provider_subject TEXT NOT NULL,
                email TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL,
                UNIQUE(provider, provider_subject),
                UNIQUE(provider, user_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
            CREATE INDEX IF NOT EXISTS idx_oauth_accounts_user
            ON oauth_accounts(user_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_oauth_accounts_email
            ON oauth_accounts(email)
            """
        )

        # Retire the old password and email-token data while preserving the
        # user rows that own Workspaces, history and provider configuration.
        conn.execute("DROP TABLE IF EXISTS email_verification_tokens")
        conn.execute("DROP TABLE IF EXISTS password_reset_tokens")
        conn.execute(
            "UPDATE users SET password_hash = '', is_verified = 1"
        )

        conn.commit()
