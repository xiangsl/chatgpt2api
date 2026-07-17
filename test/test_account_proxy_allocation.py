from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.account_service import AccountService
from services.config import ConfigStore
from services.storage.json_storage import JSONStorageBackend


class AccountProxyAllocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config_path = self.root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "auth-key": "test-auth",
                    "account_proxy_list": ["http://a", "http://b", "http://c"],
                    "accounts_per_proxy": 2,
                    "account_proxy_rr_index": 0,
                    "account_proxy_rr_count": 0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.config = ConfigStore(config_path)
        self.service = AccountService(JSONStorageBackend(self.root / "accounts.json"))

    def test_empty_proxy_list_does_not_set_proxy(self) -> None:
        with mock.patch("services.account_service.config") as cfg:
            cfg.allocate_account_proxies.return_value = []
            payloads = self.service.build_import_payloads_with_proxy_allocation(["t1", "t2"])
        self.assertEqual(
            payloads,
            [
                {"access_token": "t1", "source_type": "web"},
                {"access_token": "t2", "source_type": "web"},
            ],
        )

    def test_persistent_cursor_across_single_imports(self) -> None:
        """一次导入一个时，必须跨请求记住当前代理和已分配数量。"""
        results = []
        for index in range(7):
            token = f"t{index + 1}"
            with mock.patch("services.account_service.config", self.config):
                payloads = self.service.build_import_payloads_with_proxy_allocation([token])
            proxy = payloads[0]["proxy"]
            results.append(proxy)
            self.service.add_account_items(payloads)

        # per_proxy=2: a,a, b,b, c,c, a
        self.assertEqual(
            results,
            ["http://a", "http://a", "http://b", "http://b", "http://c", "http://c", "http://a"],
        )
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 0)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 1)

    def test_switch_proxy_resets_count_so_cycle_can_continue(self) -> None:
        self.config.data["accounts_per_proxy"] = 10
        self.config.data["account_proxy_rr_index"] = 0
        self.config.data["account_proxy_rr_count"] = 10  # 1号已满
        self.config._save()

        allocated = self.config.allocate_account_proxies(1)
        self.assertEqual(allocated, ["http://b"])  # 切到 2 号并从 0 开始
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 1)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 1)

        # 模拟 2、3 号也都满了后回到 1 号，计数已清零，可以继续导入
        self.config.data["account_proxy_rr_index"] = 2
        self.config.data["account_proxy_rr_count"] = 10
        self.config._save()
        allocated = self.config.allocate_account_proxies(1)
        self.assertEqual(allocated, ["http://a"])
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 0)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 1)

    def test_existing_account_keeps_proxy_and_skips_quota(self) -> None:
        self.service.add_account_items([{"access_token": "t1", "proxy": "http://keep"}])
        with mock.patch("services.account_service.config", self.config):
            payloads = self.service.build_import_payloads_with_proxy_allocation(["t1", "t2", "t3"])
        by_token = {item["access_token"]: item for item in payloads}
        self.assertNotIn("proxy", by_token["t1"])
        self.assertEqual(by_token["t2"]["proxy"], "http://a")
        self.assertEqual(by_token["t3"]["proxy"], "http://a")
        # 连续分了 2 个给 a，达到上限后切到 b，计数清零
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 1)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 0)

    def test_saving_same_accounts_per_proxy_does_not_reset_count(self) -> None:
        self.config.data["account_proxy_rr_index"] = 1
        self.config.data["account_proxy_rr_count"] = 7
        self.config._save()
        self.config.update({"accounts_per_proxy": 2, "base_url": "https://example.com"})
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 1)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 7)

    def test_changing_accounts_per_proxy_resets_count(self) -> None:
        self.config.data["account_proxy_rr_index"] = 1
        self.config.data["account_proxy_rr_count"] = 7
        self.config._save()
        self.config.update({"accounts_per_proxy": 10})
        self.assertEqual(self.config.data.get("account_proxy_rr_index"), 1)
        self.assertEqual(self.config.data.get("account_proxy_rr_count"), 0)


if __name__ == "__main__":
    unittest.main()
