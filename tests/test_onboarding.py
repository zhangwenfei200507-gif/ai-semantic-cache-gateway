from __future__ import annotations

import unittest
from unittest.mock import patch


class OnboardingStateTests(unittest.TestCase):
    user = {
        "id": 7,
        "email": "new-user@example.test",
        "workspace": {"id": 70, "name": "Personal Workspace"},
    }

    def _state(self, providers, history):
        from app.api import management

        with patch.object(management, "_provider_rows", return_value=providers), patch.object(
            management.history_repository,
            "list",
            return_value=history,
        ), patch.object(management, "get_gateway", return_value=object()):
            return management.onboarding(self.user)

    def test_new_workspace_requires_provider(self):
        state = self._state([], [])
        self.assertEqual(state["state"], "no_provider")
        self.assertTrue(state["show_getting_started"])
        self.assertEqual(state["steps"][0]["status"], "current")
        self.assertEqual(state["steps"][1]["status"], "locked")
        self.assertIn("add=1", state["primary_action"]["href"])

    def test_unverified_provider_requires_connection_test(self):
        state = self._state([{"name": "deepseek", "configured": True, "verified": False}], [])
        self.assertEqual(state["state"], "needs_verification")
        self.assertEqual(state["steps"][0]["action"], "Verify Connection")
        self.assertEqual(state["steps"][1]["status"], "locked")

    def test_verified_provider_unlocks_playground_then_completion(self):
        provider = {"name": "deepseek", "configured": True, "verified": True}
        ready = self._state([provider], [])
        self.assertEqual(ready["state"], "ready_for_playground")
        self.assertEqual(ready["steps"][0]["status"], "completed")
        self.assertEqual(ready["steps"][1]["status"], "current")
        completed = self._state([provider], [{"request_id": "req-1"}])
        self.assertEqual(completed["state"], "completed")
        self.assertFalse(completed["show_getting_started"])
        self.assertEqual(completed["steps"][2]["status"], "current")

    def test_onboarding_route_is_workspace_authenticated(self):
        from fastapi.testclient import TestClient

        from app.api import management
        from app.api.server import create_app
        from app.auth.dependencies import get_current_user

        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: self.user
        with patch.object(
            management,
            "_provider_rows",
            return_value=[{"name": "deepseek", "configured": True, "verified": True}],
        ), patch.object(management.history_repository, "list", return_value=[]), patch.object(
            management, "get_gateway", return_value=object()
        ):
            with TestClient(app) as client:
                response = client.get("/api/onboarding")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "ready_for_playground")
        app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
