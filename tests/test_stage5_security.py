from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


class Stage5SecurityTests(unittest.TestCase):
    def test_oauth_provider_configuration_and_state_url(self):
        from app.auth.router import _authorization_url, _provider_config
        from app.config.settings import settings

        with (
            patch.object(settings, "github_oauth_client_id", "github-client"),
            patch.object(settings, "github_oauth_client_secret", "github-secret"),
            patch.object(settings, "auth_frontend_url", "https://gateway.example.test"),
        ):
            self.assertEqual(_provider_config("github"), ("github-client", "github-secret"))
            url = _authorization_url("github", "state-value", "github-client")
            self.assertIn("client_id=github-client", url)
            self.assertIn("state=state-value", url)
            self.assertIn("api%2Fauth%2Foauth%2Fgithub%2Fcallback", url)

    @unittest.skipUnless(
        os.getenv("STAGE5_TEST_DATABASE_URL"),
        "Stage 5 security tests require an isolated PostgreSQL database",
    )
    def test_secure_cookie_csrf_and_cors_with_oauth_session(self):
        from fastapi.testclient import TestClient
        from starlette.responses import Response

        from app.api.server import create_app
        from app.auth.router import _set_session
        from app.auth.service import authenticate_oauth
        from app.config.settings import settings
        from app.db.schema import apply_schema

        os.environ["DATABASE_URL"] = os.environ["STAGE5_TEST_DATABASE_URL"]
        with (
            patch.object(settings, "app_env", "production"),
            patch.object(settings, "cookie_secure", True),
            patch.object(settings, "cookie_samesite", "lax"),
            patch.object(settings, "csrf_enabled", True),
            patch.object(settings, "cors_allowed_origins", "https://stage5.example.test"),
            patch.object(settings, "auth_frontend_url", "https://stage5.example.test"),
        ):
            apply_schema(os.environ["STAGE5_TEST_DATABASE_URL"])
            from app.auth.database import get_connection

            with get_connection() as conn:
                row = conn.execute("SELECT id, email FROM users ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self.skipTest("isolated database has no user fixture")

            user = authenticate_oauth("github", f"stage5-{uuid4().hex}", row["email"], True)
            response = Response()
            _set_session(response, user)
            token = None
            csrf = None
            for header in response.raw_headers:
                if header[0].lower() != b"set-cookie":
                    continue
                value = header[1].decode()
                if value.startswith("ascg_access_token="):
                    token = value.split("=", 1)[1].split(";", 1)[0]
                if value.startswith("ascg_csrf_token="):
                    csrf = value.split("=", 1)[1].split(";", 1)[0]

            self.assertTrue(token)
            self.assertTrue(csrf)
            client = TestClient(create_app(), base_url="https://testserver")
            client.cookies.set("ascg_access_token", token)
            client.cookies.set("ascg_csrf_token", csrf)
            self.assertEqual(client.get("/api/auth/me").status_code, 200)
            self.assertEqual(client.post("/api/auth/logout").status_code, 403)
            self.assertEqual(
                client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code,
                200,
            )

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

    def test_provider_base_url_ssrf_guard(self):
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


class RedisFailureDegradationTests(unittest.TestCase):
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

        cache = CacheService(repository=ExplodingRepository(), embedding_service=Embedding())
        gateway = AIGateway(provider="deepseek", model="deepseek-chat", cache=cache)
        gateway._resolve_routing = lambda *args, **kwargs: SimpleNamespace(
            candidates=[SimpleNamespace(provider="deepseek", model="deepseek-chat")],
            provider="deepseek",
            model="deepseek-chat",
            to_dict=lambda: {"provider": "deepseek", "model": "deepseek-chat"},
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
