from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor


@unittest.skipUnless(
    os.getenv("STAGE3_TEST_DATABASE_URL"),
    "Stage 3 isolation tests require an isolated PostgreSQL database",
)
class BYOKIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["STAGE3_TEST_DATABASE_URL"]
        os.environ["BYOK_ENABLED"] = "true"
        os.environ["APP_ENV"] = "production"
        os.environ["ALLOW_GLOBAL_PROVIDER_FALLBACK"] = "false"
        from cryptography.fernet import Fernet
        os.environ["PROVIDER_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

        from app.db.schema import apply_schema
        apply_schema(os.environ["DATABASE_URL"])
        from app.providers.workspace_store import WorkspaceProviderStore
        cls.store_a = WorkspaceProviderStore(1)
        cls.store_b = WorkspaceProviderStore(2)
        cls.store_a.delete("deepseek")
        cls.store_a.delete("qwen")
        cls.store_b.delete("deepseek")
        cls.store_b.delete("qwen")

    def setUp(self):
        for store in (self.store_a, self.store_b):
            for provider in ("deepseek", "openai", "qwen"):
                store.delete(provider)

    @classmethod
    def tearDownClass(cls):
        cls.store_a.delete("deepseek")
        cls.store_a.delete("qwen")
        cls.store_b.delete("deepseek")
        cls.store_b.delete("qwen")

    def test_credentials_are_encrypted_and_workspace_scoped(self):
        from app.providers.factory import ProviderFactory

        self.store_a.upsert(
            "deepseek",
            "DeepSeek",
            "https://api.deepseek.com",
            ["deepseek-chat"],
            api_key="sk-workspace-a",
        )
        self.store_b.upsert(
            "deepseek",
            "DeepSeek",
            "https://api.deepseek.com",
            ["deepseek-chat"],
            api_key="sk-workspace-b",
        )

        rows_a = self.store_a.list()
        rows_b = self.store_b.list()
        self.assertEqual(rows_a[0]["name"], "deepseek")
        self.assertNotIn("sk-workspace-a", repr(rows_a))
        self.assertNotIn("sk-workspace-b", repr(rows_b))
        self.assertEqual(
            ProviderFactory.create_for_workspace("deepseek", "deepseek-chat", 1).client.api_key,
            "sk-workspace-a",
        )
        self.assertEqual(
            ProviderFactory.create_for_workspace("deepseek", "deepseek-chat", 2).client.api_key,
            "sk-workspace-b",
        )

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(
                    ProviderFactory.create_for_workspace,
                    "deepseek",
                    "deepseek-chat",
                    1 if index % 2 == 0 else 2,
                )
                for index in range(8)
            ]
        keys = [future.result().client.api_key for future in futures]
        self.assertEqual(keys, ["sk-workspace-a", "sk-workspace-b"] * 4)

    def test_model_level_qwen_image_credential_and_delete(self):
        from app.providers.factory import ProviderFactory
        from app.providers.qwen_image_provider import QwenImageProvider

        self.store_a.upsert(
            "qwen",
            "Qwen",
            "https://dashscope.aliyuncs.com/api/v1",
            [{
                "model_id": "qwen-image-3.0",
                "modality": "image",
                "runtime_provider": "qwen_image",
                "role": "image",
                "base_url": "https://dashscope.aliyuncs.com/api/v1",
                "api_key": "sk-qwen-image-a",
            }],
        )
        provider = ProviderFactory.create_for_workspace("qwen_image", "qwen-image-3.0", 1)
        self.assertIsInstance(provider, QwenImageProvider)
        self.assertEqual(provider.client.api_key, "sk-qwen-image-a")
        self.assertTrue(self.store_a.delete_credential("qwen", "qwen-image-3.0"))
        with self.assertRaises(RuntimeError):
            ProviderFactory.create_for_workspace("qwen_image", "qwen-image-3.0", 1)

    def test_cache_scope_never_crosses_workspaces(self):
        from app.cache.cache_service import CacheService

        class Repository:
            def __init__(self):
                self.values = {}

            def save(self, key, answer, embedding, **kwargs):
                self.values[(str(kwargs["workspace_id"]), key, kwargs["cache_scope"])] = answer

            def find(self, key, workspace_id=None, cache_scope=None):
                for (workspace, cached_key, _), value in self.values.items():
                    if workspace == str(workspace_id) and cached_key == key:
                        return value
                return None

            def search(self, *args, **kwargs):
                return None

        class Embedding:
            def encode(self, text):
                return [1.0]

        repository = Repository()
        cache = CacheService(repository=repository, embedding_service=Embedding())
        messages = [{"role": "user", "content": "same request"}]
        context = {"model": "auto", "temperature": 0.7, "max_tokens": 100, "modality": "text"}
        cache.set(messages, "answer-a", workspace_id="1", cache_context=context)
        self.assertTrue(cache.lookup(messages, workspace_id="1", cache_context=context)["hit"])
        self.assertFalse(cache.lookup(messages, workspace_id="2", cache_context=context)["hit"])

    def test_history_queries_are_workspace_scoped(self):
        from app.history.repository import history_repository

        request_a = "req_stage3_workspace_a"
        request_b = "req_stage3_workspace_b"
        history_repository.save({
            "request_id": request_a, "user_id": "1", "workspace_id": 1,
            "question": "a", "answer": "a", "status": "success",
        })
        history_repository.save({
            "request_id": request_b, "user_id": "2", "workspace_id": 2,
            "question": "b", "answer": "b", "status": "success",
        })
        try:
            workspace_a = [item["request_id"] for item in history_repository.list(workspace_id=1)]
            self.assertIn(request_a, workspace_a)
            self.assertNotIn(request_b, workspace_a)
            self.assertIsNone(history_repository.get(request_b, workspace_id=1))
        finally:
            from app.db.postgres import get_postgres_connection
            with get_postgres_connection() as conn:
                conn.execute(
                    "DELETE FROM gateway_history WHERE request_id IN (?, ?)",
                    (request_a, request_b),
                )

    def test_provider_api_isolation(self):
        from app.auth.security import create_access_token
        from app.auth.service import get_user
        from app.api.server import create_app
        from fastapi.testclient import TestClient

        user_a = get_user(1)
        user_b = get_user(2)
        if not user_a or not user_b or not user_a["is_verified"] or not user_b["is_verified"]:
            self.skipTest("isolated database fixture does not have two verified users")
        self.store_a.upsert("deepseek", "DeepSeek", "https://api.deepseek.com", ["deepseek-chat"], api_key="sk-a")
        self.store_b.upsert("openai", "OpenAI", "https://api.openai.com/v1", ["gpt-test"], api_key="sk-b")
        client = TestClient(create_app())
        headers_a = {"Authorization": f"Bearer {create_access_token(user_a['id'], user_a['email'])}"}
        headers_b = {"Authorization": f"Bearer {create_access_token(user_b['id'], user_b['email'])}"}
        response_a = client.get("/api/providers", headers=headers_a)
        response_b = client.get("/api/providers", headers=headers_b)
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual({item["name"] for item in response_a.json()["providers"]}, {"deepseek"})
        self.assertEqual({item["name"] for item in response_b.json()["providers"]}, {"openai"})

    def test_router_candidates_are_workspace_scoped(self):
        from app.gateway import AIGateway

        self.store_a.upsert("deepseek", "DeepSeek", "https://api.deepseek.com", ["deepseek-chat"], api_key="sk-a")
        self.store_b.upsert("openai", "OpenAI", "https://api.openai.com/v1", ["gpt-test"], api_key="sk-b")
        gateway = AIGateway(cache=None)
        messages = [{"role": "user", "content": "Explain a database index."}]
        decision_a = gateway._resolve_routing(messages, "auto", workspace_id="1")
        decision_b = gateway._resolve_routing(messages, "auto", workspace_id="2")
        self.assertEqual({item.provider for item in decision_a.candidates}, {"deepseek"})
        self.assertEqual({item.provider for item in decision_b.candidates}, {"openai"})


if __name__ == "__main__":
    unittest.main()
