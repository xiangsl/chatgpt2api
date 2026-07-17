from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.accounts as accounts_module


class FakeAccountService:
    def __init__(self) -> None:
        self.add_calls: list[list[str]] = []
        self.add_item_calls: list[list[dict]] = []
        self.proxy_allocation_calls: list[list[str]] = []
        self.refresh_calls: list[list[str]] = []

    def add_accounts(self, tokens: list[str], source_type: str = "web") -> dict:
        self.add_calls.append(tokens)
        return {"added": len(tokens), "skipped": 0, "items": []}

    def build_import_payloads_with_proxy_allocation(self, tokens: list[str], source_type: str = "web") -> list[dict]:
        self.proxy_allocation_calls.append(tokens)
        return [{"access_token": token, "source_type": source_type} for token in tokens]

    def add_account_items(self, items: list[dict]) -> dict:
        self.add_item_calls.append(items)
        tokens = [str(item.get("access_token") or "") for item in items]
        self.add_calls.append(tokens)
        return {"added": len(items), "skipped": 0, "items": []}

    def refresh_accounts(self, tokens: list[str], progress_id: str | None = None, defer_invalid_removal: bool = True) -> dict:
        self.refresh_calls.append(tokens)
        return {"refreshed": len(tokens), "errors": [], "items": []}

    def get_stats(self) -> dict:
        return {"active": 3, "total_quota": 12}

    def list_accounts(self) -> list[dict]:
        return []

    def get_invalid_account_total(self) -> int:
        return 4

    def reset_invalid_account_total(self) -> int:
        return 0


class AccountsImportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_service = FakeAccountService()
        self.service_patcher = mock.patch.object(accounts_module, "account_service", self.fake_service)
        self.service_patcher.start()
        self.admin_patcher = mock.patch.object(accounts_module, "require_admin", lambda _authorization: {"role": "admin"})
        self.admin_patcher.start()
        self.addCleanup(self.service_patcher.stop)
        self.addCleanup(self.admin_patcher.stop)
        app = FastAPI()
        app.include_router(accounts_module.create_router())
        self.client = TestClient(app)

    def test_import_access_token_single(self) -> None:
        response = self.client.post(
            "/api/accounts/import/access-token",
            headers={"Authorization": "Bearer test-admin"},
            json={"access_token": "token-a"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["refreshed"], 1)
        self.assertEqual(self.fake_service.add_calls, [["token-a"]])
        self.assertEqual(self.fake_service.refresh_calls, [["token-a"]])

    def test_get_accounts_includes_invalid_account_count(self) -> None:
        response = self.client.get(
            "/api/accounts",
            headers={"Authorization": "Bearer test-admin"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": [], "invalid_account_count": 4})

    def test_import_access_token_multiple(self) -> None:
        response = self.client.post(
            "/api/accounts/import/access-token",
            headers={"Authorization": "Bearer test-admin"},
            json={"tokens": ["token-a", "token-b"]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.fake_service.add_calls, [["token-a", "token-b"]])

    def test_import_access_token_stores_explicit_account_proxy(self) -> None:
        response = self.client.post(
            "/api/accounts/import/access-token",
            headers={"Authorization": "Bearer test-admin"},
            json={
                "tokens": ["token-a", "token-b"],
                "proxy": "  http://user:pass@127.0.0.1:7890  ",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.fake_service.add_item_calls,
            [[
                {"access_token": "token-a", "source_type": "web", "proxy": "http://user:pass@127.0.0.1:7890"},
                {"access_token": "token-b", "source_type": "web", "proxy": "http://user:pass@127.0.0.1:7890"},
            ]],
        )
        self.assertEqual(self.fake_service.proxy_allocation_calls, [])

    def test_import_access_token_requires_value(self) -> None:
        response = self.client.post(
            "/api/accounts/import/access-token",
            headers={"Authorization": "Bearer test-admin"},
            json={},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["error"], "access_token or tokens is required")

    def test_import_session_json_object(self) -> None:
        response = self.client.post(
            "/api/accounts/import/session-json",
            headers={"Authorization": "Bearer test-admin"},
            json={"session": {"accessToken": "session-token", "user": {"email": "a@example.com"}}},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.fake_service.add_calls, [["session-token"]])
        self.assertEqual(self.fake_service.refresh_calls, [["session-token"]])

    def test_import_session_json_string(self) -> None:
        response = self.client.post(
            "/api/accounts/import/session-json",
            headers={"Authorization": "Bearer test-admin"},
            json={"session_json": '{"accessToken":"raw-session-token"}'},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.fake_service.add_calls, [["raw-session-token"]])

    def test_import_session_json_missing_token(self) -> None:
        response = self.client.post(
            "/api/accounts/import/session-json",
            headers={"Authorization": "Bearer test-admin"},
            json={"session": {"user": {"email": "a@example.com"}}},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["error"], "accessToken not found in session JSON")

    def test_get_normal_account_stats(self) -> None:
        response = self.client.get(
            "/api/accounts/stats/normal",
            headers={"Authorization": "Bearer test-admin"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"active_count": 3, "total_quota": 12})

    def test_reset_invalid_account_stats(self) -> None:
        response = self.client.post(
            "/api/accounts/stats/invalid/reset",
            headers={"Authorization": "Bearer test-admin"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"invalid_account_count": 0})


if __name__ == "__main__":
    unittest.main()
