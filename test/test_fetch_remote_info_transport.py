import unittest
from unittest.mock import patch

from services.fetch_remote_info_transport import (
    fetch_user_info_with_403_fallback,
    is_http_403_error,
)


class FetchRemoteInfoTransportTests(unittest.TestCase):
    def test_is_http_403_error(self) -> None:
        self.assertTrue(is_http_403_error(RuntimeError("/backend-api/me failed: HTTP 403")))
        self.assertFalse(is_http_403_error(RuntimeError("/backend-api/me failed: HTTP 401")))

    @patch("services.fetch_remote_info_transport.fetch_user_info_proxy")
    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    @patch("services.fetch_remote_info_transport.openai_register")
    def test_fallback_chain(
        self,
        register_mock,
        local_mock,
        clearance_mock,
        proxy_mock,
    ) -> None:
        register_mock.config = {
            "proxy": "http://proxy.example:8080",
            "always_use_fetch_remote_info_proxy": False,
        }
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        clearance_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        proxy_mock.return_value = {"email": "a@b.com", "status": "正常"}

        result = fetch_user_info_with_403_fallback("token-a")

        self.assertEqual(result["email"], "a@b.com")
        local_mock.assert_called_once_with("token-a")
        clearance_mock.assert_called_once_with("token-a")
        proxy_mock.assert_called_once_with("token-a", "http://proxy.example:8080")

    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    @patch("services.fetch_remote_info_transport.openai_register")
    def test_clearance_success_skips_proxy(self, register_mock, local_mock, clearance_mock) -> None:
        register_mock.config = {
            "proxy": "http://proxy.example:8080",
            "always_use_fetch_remote_info_proxy": False,
        }
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        clearance_mock.return_value = {"email": "a@b.com", "status": "正常"}

        result = fetch_user_info_with_403_fallback("token-a")

        self.assertEqual(result["email"], "a@b.com")
        clearance_mock.assert_called_once_with("token-a")

    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    @patch("services.fetch_remote_info_transport.openai_register")
    def test_non_403_error_is_not_retried(self, register_mock, local_mock) -> None:
        register_mock.config = {
            "proxy": "",
            "always_use_fetch_remote_info_proxy": False,
        }
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 500")

        with self.assertRaises(RuntimeError):
            fetch_user_info_with_403_fallback("token-a")

    @patch("services.fetch_remote_info_transport.fetch_user_info_proxy")
    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    @patch("services.fetch_remote_info_transport.openai_register")
    def test_always_use_proxy_skips_local_and_clearance(
        self,
        register_mock,
        local_mock,
        clearance_mock,
        proxy_mock,
    ) -> None:
        register_mock.config = {
            "proxy": "http://proxy.example:8080",
            "always_use_fetch_remote_info_proxy": True,
        }
        proxy_mock.return_value = {"email": "a@b.com", "status": "正常"}

        result = fetch_user_info_with_403_fallback("token-a")

        self.assertEqual(result["email"], "a@b.com")
        local_mock.assert_not_called()
        clearance_mock.assert_not_called()
        proxy_mock.assert_called_once_with("token-a", "http://proxy.example:8080")


if __name__ == "__main__":
    unittest.main()
