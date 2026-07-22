from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.system as system_module
from services.config import ConfigStore


AUTH_HEADERS = {"Authorization": "Bearer chatgpt2api"}


class ProxySettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config_path = Path(self.tmp.name) / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "auth-key": "chatgpt2api",
                    "proxy": {
                        "enabled": False,
                        "url": "http://old.example:8080",
                        "interval_secs": 2,
                        "rounds": 3,
                    },
                    "account_proxy_list_enabled": False,
                    "account_proxy_list": ["http://keep.example:1"],
                    "accounts_per_proxy": 2,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.config = ConfigStore(config_path)
        self.patchers = [
            mock.patch.object(system_module, "config", self.config),
            mock.patch.object(system_module, "require_admin", lambda _authorization: {"role": "admin"}),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(system_module.create_router("9.9.9-test"))
        self.client = TestClient(app)

    def test_get_proxy_settings(self) -> None:
        response = self.client.get("/api/proxy/settings", headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["proxy"]["enabled"])
        self.assertEqual(payload["proxy"]["url"], "http://old.example:8080")
        self.assertFalse(payload["account_proxy_list_enabled"])
        self.assertEqual(payload["account_proxy_list"], ["http://keep.example:1"])

    def test_patch_only_provided_fields(self) -> None:
        response = self.client.post(
            "/api/proxy/settings",
            headers=AUTH_HEADERS,
            json={"proxy_enabled": True, "proxy_url": "http://new.example:7890"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["proxy"]["enabled"])
        self.assertEqual(payload["proxy"]["url"], "http://new.example:7890")
        self.assertEqual(payload["proxy"]["interval_secs"], 2)
        self.assertEqual(payload["proxy"]["rounds"], 3)
        self.assertFalse(payload["account_proxy_list_enabled"])
        self.assertEqual(payload["account_proxy_list"], ["http://keep.example:1"])

    def test_clear_with_minus_one(self) -> None:
        self.config.update(
            {
                "proxy": {"enabled": True, "url": "http://new.example:7890"},
                "account_proxy_list_enabled": True,
                "account_proxy_list": ["http://a", "http://b"],
            }
        )
        response = self.client.post(
            "/api/proxy/settings",
            headers=AUTH_HEADERS,
            json={
                "proxy_enabled": -1,
                "proxy_url": -1,
                "account_proxy_list_enabled": "-1",
                "account_proxy_list": -1,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["proxy"]["enabled"])
        self.assertEqual(payload["proxy"]["url"], "")
        self.assertFalse(payload["account_proxy_list_enabled"])
        self.assertEqual(payload["account_proxy_list"], [])

    def test_account_proxy_list_accepts_newline_string(self) -> None:
        response = self.client.post(
            "/api/proxy/settings",
            headers=AUTH_HEADERS,
            json={
                "account_proxy_list_enabled": True,
                "account_proxy_list": "http://a\nhttp://b\n",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["account_proxy_list_enabled"])
        self.assertEqual(payload["account_proxy_list"], ["http://a", "http://b"])

    def test_empty_body_keeps_existing_values(self) -> None:
        response = self.client.post("/api/proxy/settings", headers=AUTH_HEADERS, json={})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["proxy"]["url"], "http://old.example:8080")
        self.assertEqual(payload["account_proxy_list"], ["http://keep.example:1"])


if __name__ == "__main__":
    unittest.main()
