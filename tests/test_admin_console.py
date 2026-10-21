from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException


class AdminAuthorizationTests(unittest.TestCase):
    def test_admin_requires_immutable_id_and_database_flag(self):
        from app.auth.dependencies import get_current_admin
        from app.config.settings import settings

        with patch.object(settings, "admin_user_id", 1):
            with self.assertRaises(HTTPException) as missing_flag:
                get_current_admin({"id": 1, "is_admin": False})
            self.assertEqual(missing_flag.exception.status_code, 403)

            with self.assertRaises(HTTPException) as wrong_id:
                get_current_admin({"id": 2, "is_admin": True})
            self.assertEqual(wrong_id.exception.status_code, 403)

            user = {"id": 1, "is_admin": True}
            self.assertIs(get_current_admin(user), user)

        with patch.object(settings, "admin_user_id", None):
            with self.assertRaises(HTTPException) as not_configured:
                get_current_admin({"id": 1, "is_admin": True})
            self.assertEqual(not_configured.exception.status_code, 403)

    def test_admin_routes_reject_normal_user_and_hide_sensitive_fields(self):
        from fastapi.testclient import TestClient

        from app.api import admin_console
        from app.api.server import create_app
        from app.auth.dependencies import get_current_user
        from app.config.settings import settings

        app = create_app()
        normal_user = {"id": 2, "email": "user@example.test", "is_admin": False, "is_active": True}
        app.dependency_overrides[get_current_user] = lambda: normal_user
        with patch.object(settings, "admin_user_id", 1):
            with TestClient(app) as client:
                denied = client.get("/api/admin/users")
            self.assertEqual(denied.status_code, 403)
        app.dependency_overrides.clear()

        admin_user = {"id": 1, "email": "admin@example.test", "is_admin": True, "is_active": True}
        app.dependency_overrides[get_current_user] = lambda: admin_user
        snapshot = (
            [
                {
                    "id": 2,
                    "email": "user@example.test",
                    "is_admin": False,
                    "status": "active",
                    "workspace_count": 1,
                    "provider_count": 1,
                    "request_count": 1,
                    "total_tokens": 12,
                    "estimated_cost": 0.01,
                    "created_at": "2026-10-21T00:00:00+00:00",
                    "last_active_at": None,
                }
            ],
            [{"id": 20, "owner_user_id": 2, "name": "User Workspace"}],
            [
                {
                    "request_id": "req-1",
                    "user_id": "2",
                    "workspace_id": 20,
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "total_tokens": 12,
                    "cost": 0.01,
                    "status": "success",
                    "created_at": "2026-10-21T00:00:00+00:00",
                }
            ],
            {20: 1},
        )
        with patch.object(settings, "admin_user_id", 1), patch.object(admin_console, "_snapshot", return_value=snapshot):
            with TestClient(app) as client:
                allowed = client.get("/api/admin/users")
        self.assertEqual(allowed.status_code, 200)
        body = allowed.json()
        self.assertEqual(body["items"][0]["email"], "user@example.test")
        serialized = str(body)
        for secret_name in ("password_hash", "encrypted_api_key", "smtp_password", "api_key"):
            self.assertNotIn(secret_name, serialized)
        app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
