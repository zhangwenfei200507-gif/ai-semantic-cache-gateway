from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class OAuthAuthenticationTests(unittest.TestCase):
    def test_verified_oauth_identity_links_existing_user_and_workspace(self):
        from app.auth.database import init_db
        from app.auth.service import authenticate_oauth

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.db"
            with (
                patch("app.auth.database.DB_PATH", path),
                patch("app.auth.database.postgres_configured", return_value=False),
                patch("app.auth.service.postgres_configured", return_value=False),
                patch("app.workspace.service.postgres_configured", return_value=False),
            ):
                init_db()
                with sqlite3.connect(path) as conn:
                    conn.execute(
                        "INSERT INTO users(email, password_hash, is_active, is_verified, is_admin, created_at, updated_at) VALUES (?, '', 1, 1, 0, ?, ?)",
                        ("owner@example.test", "2026-10-21T00:00:00+00:00", "2026-10-21T00:00:00+00:00"),
                    )
                    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "INSERT INTO workspaces(owner_user_id, name, kind, created_at, updated_at) VALUES (?, ?, 'personal', ?, ?)",
                        (user_id, "Owner Workspace", "2026-10-21T00:00:00+00:00", "2026-10-21T00:00:00+00:00"),
                    )
                    conn.commit()
                conn.close()

                from app.auth.service import get_user
                self.assertIsNone(get_user(user_id))
                user = authenticate_oauth("google", "google-subject-1", "owner@example.test", True)
                self.assertEqual(user["id"], user_id)
                self.assertEqual(user["workspace"]["name"], "Owner Workspace")
                self.assertEqual(get_user(user_id)["id"], user_id)

                with sqlite3.connect(path) as conn:
                    account = conn.execute(
                        "SELECT provider, provider_subject, user_id FROM oauth_accounts"
                    ).fetchone()
                conn.close()
                self.assertEqual(account, ("google", "google-subject-1", user_id))

    def test_new_verified_oauth_identity_creates_user_and_workspace(self):
        from app.auth.database import init_db
        from app.auth.service import authenticate_oauth

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.db"
            with (
                patch("app.auth.database.DB_PATH", path),
                patch("app.auth.database.postgres_configured", return_value=False),
                patch("app.auth.service.postgres_configured", return_value=False),
                patch("app.workspace.service.postgres_configured", return_value=False),
            ):
                init_db()
                user = authenticate_oauth("github", "github-subject-1", "new@example.test", True)
                self.assertEqual(user["email"], "new@example.test")
                self.assertTrue(user["workspace"]["id"])

                with self.assertRaises(ValueError):
                    authenticate_oauth("google", "google-subject-2", "unverified@example.test", False)


if __name__ == "__main__":
    unittest.main()
