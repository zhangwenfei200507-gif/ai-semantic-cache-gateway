from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from uuid import uuid4


@unittest.skipUnless(
    os.getenv("STAGE5_TEST_DATABASE_URL"),
    "Stage 5 security tests require an isolated PostgreSQL database",
)
class Stage5SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["STAGE5_TEST_DATABASE_URL"]
        os.environ["APP_ENV"] = "production"
        os.environ["BYOK_ENABLED"] = "true"
        os.environ["ALLOW_GLOBAL_PROVIDER_FALLBACK"] = "false"
        os.environ["COOKIE_SECURE"] = "true"
        os.environ["COOKIE_SAMESITE"] = "lax"
        os.environ["CSRF_ENABLED"] = "true"
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://stage5.example.test"
        os.environ["AUTH_FRONTEND_URL"] = "https://stage5.example.test"
        os.environ["IMAGE_STORAGE_BACKEND"] = "s3"
        os.environ["S3_BUCKET"] = "stage5-private"
        os.environ["S3_ACCESS_KEY_ID"] = "test-access"
        os.environ["S3_SECRET_ACCESS_KEY"] = "test-secret"

        from app.auth.database import get_connection
        from app.auth.security import hash_password
        from app.db.schema import apply_schema

        apply_schema(os.environ["DATABASE_URL"])
        cls.password = "Stage5-pass-123!"
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, email, password_hash, is_verified FROM users ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                raise unittest.SkipTest("isolated database has no user fixture")
            cls.user_id = row["id"]
            cls.email = row["email"]
            cls.old_password_hash = row["password_hash"]
            cls.old_is_verified = row["is_verified"]
            conn.execute(
                "UPDATE users SET password_hash = ?, is_verified = TRUE WHERE id = ?",
                (hash_password(cls.password), cls.user_id),
            )

    @classmethod
    def tearDownClass(cls):
        from app.auth.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, is_verified = ? WHERE id = ?",
                (cls.old_password_hash, cls.old_is_verified, cls.user_id),
            )

    def test_secure_cookie_csrf_and_cors(self):
        from app.api.server import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app(), base_url="https://testserver")
        login = client.post(
            "/api/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(client.cookies.get("ascg_access_token"))
        csrf_token = client.cookies.get("ascg_csrf_token")
        self.assertTrue(csrf_token)

        cookie_header = login.headers.get("set-cookie", "").lower()
        self.assertIn("secure", cookie_header)
        self.assertIn("httponly", cookie_header)
        self.assertIn("samesite=lax", cookie_header)

        denied = client.post("/api/auth/logout")
        self.assertEqual(denied.status_code, 403, denied.text)
        allowed = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

        allowed_cors = client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://stage5.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(
            allowed_cors.headers.get("access-control-allow-origin"),
            "https://stage5.example.test",
        )
        denied_cors = client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://evil.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertIsNone(denied_cors.headers.get("access-control-allow-origin"))

        self.assertEqual(login.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(login.headers.get("x-frame-options"), "DENY")

    def test_registration_verification_login_and_workspace(self):
        from app.auth.database import get_connection
        from app.auth.service import (
            authenticate,
            create_email_verification,
            register,
            verify_email,
        )

        email = f"stage5-{uuid4().hex}@example.test"
        password = "Stage5-registration-123!"
        user = register(email, password)
        self.assertIsNotNone(user.get("workspace", {}).get("id"))
        with self.assertRaises(ValueError):
            authenticate(email, password)

        token = create_email_verification(user["id"])
        self.assertTrue(verify_email(token))
        authenticated = authenticate(email, password)
        self.assertEqual(authenticated["id"], user["id"])
        self.assertEqual(authenticated["workspace"]["id"], user["workspace"]["id"])

        with get_connection() as conn:
            conn.execute("DELETE FROM workspaces WHERE owner_user_id = ?", (user["id"],))
            conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))


class RedisFailureDegradationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("STAGE5_REDIS_URL"),
        "Stage 5 Redis rate-limit test requires an isolated Redis instance",
    )
    def test_redis_rate_limit_enforces_429(self):
        from fastapi import HTTPException
        from unittest.mock import patch

        from app.config.settings import settings
        from app.security.rate_limit import GatewayRateLimiter

        with patch.object(settings, "redis_url", os.environ["STAGE5_REDIS_URL"]):
            with patch.object(settings, "rate_limit_enabled", True):
                limiter = GatewayRateLimiter()
                scope = f"stage5-rate-{uuid4().hex}"
                limiter.check(scope, "workspace-a", limit=2)
                limiter.check(scope, "workspace-a", limit=2)
                with self.assertRaises(HTTPException) as error:
                    limiter.check(scope, "workspace-a", limit=2)
                self.assertEqual(error.exception.status_code, 429)

    def test_provider_base_url_ssrf_guard(self):
        from unittest.mock import patch

        from app.config.settings import settings
        from app.security.guards import validate_provider_base_url

        with patch.object(settings, "app_env", "production"):
            with self.assertRaises(ValueError):
                validate_provider_base_url("http://127.0.0.1:9000/v1")
            with self.assertRaises(ValueError):
                validate_provider_base_url("https://10.0.0.8/v1")
            self.assertEqual(
                validate_provider_base_url("https://api.example.test/v1"),
                "https://api.example.test/v1",
            )

    def test_cache_lookup_failure_reaches_provider(self):
        from app.cache.cache_service import CacheService
        from app.gateway import AIGateway
        from app.schemas.llm_response import LLMResponse

        class ExplodingRepository:
            def find(self, *args, **kwargs):
                raise ConnectionError("redis offline")

            def search(self, *args, **kwargs):
                raise ConnectionError("redis offline")

            def save(self, *args, **kwargs):
                raise ConnectionError("redis offline")

        class Embedding:
            def encode(self, _text):
                return [1.0]

        class Provider:
            def chat(self, **kwargs):
                return LLMResponse(
                    answer="provider reached",
                    model="deepseek-chat",
                    provider="deepseek",
                )

        cache = CacheService(
            repository=ExplodingRepository(),
            embedding_service=Embedding(),
        )
        gateway = AIGateway(
            provider="deepseek",
            model="deepseek-chat",
            cache=cache,
        )
        gateway._resolve_routing = lambda *args, **kwargs: SimpleNamespace(
            candidates=[SimpleNamespace(provider="deepseek", model="deepseek-chat")],
            provider="deepseek",
            model="deepseek-chat",
            to_dict=lambda: {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
        )
        gateway._get_provider = lambda *args, **kwargs: Provider()
        gateway._save_history = lambda *args, **kwargs: None
        gateway._persist_images = lambda *args, **kwargs: None

        response = gateway.chat(
            [{"role": "user", "content": "redis outage fallback"}],
            model="auto",
            user_id="1",
            workspace_id="1",
        )
        self.assertEqual(response.answer, "provider reached")
        self.assertFalse(response.cache_hit)


if __name__ == "__main__":
    unittest.main()
