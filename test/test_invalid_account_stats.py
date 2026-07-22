from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend


class InvalidAccountStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.service = AccountService(JSONStorageBackend(root / "accounts.json"))
        self.stats_file = root / "invalid-account-total"
        self.success_stats_file = root / "invalid-account-success-total"
        self.recent_stats_file = root / "invalid-account-recent-successes"
        self.service._invalid_account_total = 0
        self.service._invalid_account_success_total = 0
        self.service._recent_invalid_successes.clear()
        self.stats_path_patcher = mock.patch.object(
            self.service,
            "_get_invalid_account_total_file",
            return_value=self.stats_file,
        )
        self.success_stats_path_patcher = mock.patch.object(
            self.service,
            "_get_invalid_account_success_total_file",
            return_value=self.success_stats_file,
        )
        self.recent_stats_path_patcher = mock.patch.object(
            self.service,
            "_get_recent_invalid_successes_file",
            return_value=self.recent_stats_file,
        )
        self.stats_path_patcher.start()
        self.success_stats_path_patcher.start()
        self.recent_stats_path_patcher.start()
        self.addCleanup(self.stats_path_patcher.stop)
        self.addCleanup(self.success_stats_path_patcher.stop)
        self.addCleanup(self.recent_stats_path_patcher.stop)

    def test_invalid_token_removal_is_counted_and_persisted(self) -> None:
        self.service.add_accounts(["invalid-token"])
        self.service.update_account("invalid-token", {"success": 7})
        with mock.patch("services.account_service.config") as config:
            config.auto_remove_invalid_accounts = True
            self.assertTrue(self.service.remove_invalid_token("invalid-token", "test"))

        self.assertEqual(self.service.get_invalid_account_total(), 1)
        self.assertEqual(self.service.get_invalid_account_success_total(), 7)
        self.assertEqual(self.service.get_invalid_account_recent_success_total(), 7)
        self.assertEqual(self.stats_file.read_text(), "1")
        self.assertEqual(self.success_stats_file.read_text(), "7")
        self.assertEqual(self.recent_stats_file.read_text(), "[7]")
        self.assertIsNone(self.service.get_account("invalid-token"))

    def test_recent_success_keeps_last_ten_only(self) -> None:
        for index in range(12):
            token = f"token-{index}"
            self.service.add_accounts([token])
            self.service.update_account(token, {"success": index + 1})
            with mock.patch("services.account_service.config") as config:
                config.auto_remove_invalid_accounts = True
                self.service.remove_invalid_token(token, "test")

        # last 10 successes: 3..12
        self.assertEqual(self.service.get_invalid_account_total(), 12)
        self.assertEqual(self.service.get_invalid_account_success_total(), sum(range(1, 13)))
        self.assertEqual(self.service.get_invalid_account_recent_success_total(), sum(range(3, 13)))
        self.assertEqual(list(self.service._recent_invalid_successes), list(range(3, 13)))

    def test_repeated_refresh_failures_are_counted(self) -> None:
        self.service.add_accounts(["failing-token"])
        self.service.update_account("failing-token", {"success": 3})
        for _ in range(3):
            self.service._record_refresh_failure("failing-token", "HTTP 500")

        self.assertEqual(self.service.get_invalid_account_total(), 1)
        self.assertEqual(self.service.get_invalid_account_success_total(), 3)
        self.assertEqual(self.service.get_invalid_account_recent_success_total(), 3)
        self.assertIsNone(self.service.get_account("failing-token"))

    def test_auto_removed_rate_limited_account_is_counted(self) -> None:
        self.service.add_accounts(["limited-token"])
        self.service.update_account("limited-token", {"success": 5})
        with mock.patch("services.account_service.config") as config:
            config.auto_remove_rate_limited_accounts = True
            self.assertIsNone(self.service.update_account("limited-token", {"status": "限流"}))

        self.assertEqual(self.service.get_invalid_account_total(), 1)
        self.assertEqual(self.service.get_invalid_account_success_total(), 5)
        self.assertEqual(self.service.get_invalid_account_recent_success_total(), 5)
        self.assertIsNone(self.service.get_account("limited-token"))

    def test_manual_delete_is_not_counted_and_reset_is_explicit(self) -> None:
        self.service.add_accounts(["manual-token"])
        self.service.update_account("manual-token", {"success": 9})
        self.service.delete_accounts(["manual-token"])

        self.assertEqual(self.service.get_invalid_account_total(), 0)
        self.assertEqual(self.service.get_invalid_account_success_total(), 0)
        self.assertEqual(self.service.get_invalid_account_recent_success_total(), 0)
        self.service._invalid_account_total = 3
        self.service._invalid_account_success_total = 12
        self.service._recent_invalid_successes.extend([1, 2, 3])
        self.assertEqual(
            self.service.reset_invalid_account_stats(),
            {
                "invalid_account_count": 0,
                "invalid_account_success_total": 0,
                "invalid_account_recent_success_total": 0,
            },
        )
        self.assertEqual(self.stats_file.read_text(), "0")
        self.assertEqual(self.success_stats_file.read_text(), "0")
        self.assertEqual(self.recent_stats_file.read_text(), "[]")


if __name__ == "__main__":
    unittest.main()
