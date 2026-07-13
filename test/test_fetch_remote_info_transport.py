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

    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    def test_fallback_to_clearance(self, local_mock, clearance_mock) -> None:
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        clearance_mock.return_value = {"email": "a@b.com", "status": "正常"}

        result = fetch_user_info_with_403_fallback("token-a")

        self.assertEqual(result["email"], "a@b.com")
        local_mock.assert_called_once_with("token-a")
        clearance_mock.assert_called_once_with("token-a")

    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    def test_clearance_success_skips_further_fallback(self, local_mock, clearance_mock) -> None:
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        clearance_mock.return_value = {"email": "a@b.com", "status": "正常"}

        result = fetch_user_info_with_403_fallback("token-a")

        self.assertEqual(result["email"], "a@b.com")
        clearance_mock.assert_called_once_with("token-a")

    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    def test_non_403_error_is_not_retried(self, local_mock) -> None:
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 500")

        with self.assertRaises(RuntimeError):
            fetch_user_info_with_403_fallback("token-a")

    @patch("services.fetch_remote_info_transport.fetch_user_info_clearance")
    @patch("services.fetch_remote_info_transport.fetch_user_info_local")
    def test_no_register_proxy_fallback(self, local_mock, clearance_mock) -> None:
        local_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")
        clearance_mock.side_effect = RuntimeError("/backend-api/me failed: HTTP 403")

        with self.assertRaises(RuntimeError) as ctx:
            fetch_user_info_with_403_fallback("token-a")

        self.assertIn("HTTP 403", str(ctx.exception))
        local_mock.assert_called_once_with("token-a")
        clearance_mock.assert_called_once_with("token-a")


if __name__ == "__main__":
    unittest.main()
