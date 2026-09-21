from __future__ import annotations

import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.image_trace import (
    compact_trace_fields,
    ensure_trace_log,
    format_trace_line,
    generate_trace_id,
    reset_image_trace,
    reset_trace_log,
    resolve_trace_id,
    start_image_trace,
    trace_log,
    trace_span,
)


class ImageTraceTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_image_trace()

    def test_prefer_request_id_header(self) -> None:
        trace_id = resolve_trace_id({"X-Request-Id": "202609210738351329377618268d9d6T4IDyMx9"})
        self.assertEqual(trace_id, "202609210738351329377618268d9d6T4IDyMx9")

    def test_generate_when_header_missing(self) -> None:
        trace_id = resolve_trace_id({})
        self.assertRegex(trace_id, r"^img-[0-9a-f]{8}$")
        self.assertRegex(generate_trace_id(), r"^img-[0-9a-f]{8}$")

    def test_plain_text_line_is_compact(self) -> None:
        line = format_trace_line(
            timestamp=datetime(2026, 9, 21, 16, 0, 1, 123000),
            level="info",
            trace_id="img-41462103",
            module="image.poll",
            event="image_poll_end",
            stage_ms=100012,
            total_ms=120122,
            fields={"status": "timeout", "conversation_id": "conv-1"},
        )
        self.assertTrue(line.startswith("09-21 16:00:01 INFO*** trace_id=img-41462103 "))
        self.assertIn("trace_id=img-41462103", line)
        self.assertIn("module=poll", line)
        self.assertIn("event=end**", line)
        self.assertIn("stage=100", line)
        self.assertIn("total=120", line)
        self.assertNotIn("stage_ms=", line)
        self.assertNotIn("2026-", line)

    def test_compact_fields_drop_defaults(self) -> None:
        compacted = compact_trace_fields({
            "n": 1,
            "stream": False,
            "prompt_len": 498,
            "plan_type": "-",
            "source": "web",
            "has_token": True,
            "path": "/backend-api/f/conversation/prepare",
            "index": 1,
            "total": 1,
            "account_email": "a@b.com",
            "file_id": "file_00000000ed44823095f0acdde0cf11e6",
            "file_size": 259280,
            "width": 3584,
            "height": 2016,
        })
        self.assertEqual(compacted["account_email"], "a@b.com")
        self.assertEqual(compacted["size"], "3584x2016")
        self.assertNotIn("n", compacted)
        self.assertNotIn("stream", compacted)
        self.assertNotIn("prompt_len", compacted)
        self.assertNotIn("plan_type", compacted)
        self.assertNotIn("source", compacted)
        self.assertNotIn("has_token", compacted)
        self.assertNotIn("path", compacted)
        self.assertNotIn("index", compacted)
        self.assertNotIn("file_id", compacted)

    def test_subsecond_duration_is_zero(self) -> None:
        line = format_trace_line(
            timestamp=datetime(2026, 9, 21, 9, 3, 48),
            level="INFO",
            trace_id="img-abc",
            module="api",
            event="api.start",
            stage_ms=758,
            total_ms=4801,
        )
        self.assertIn("module=api*", line)
        self.assertIn("event=start", line)
        self.assertIn("stage=0", line)
        self.assertIn("total=4", line)

    def test_writes_start_and_end_to_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-trace.log"
            start_image_trace({"x-request-id": "abc-123"}, log_path=path)
            trace_span("image.poll")
            trace_log("image.poll", "image_poll_start", timeout_secs=100)
            time.sleep(0.02)
            trace_log("image.poll", "image_poll_end", status="timeout")
            text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("trace_id=abc-123", lines[0])
        self.assertIn("stage=0", lines[0])
        self.assertIn("event=end**", lines[1])
        self.assertIn("module=poll", lines[0])

    def test_module_and_event_are_aligned(self) -> None:
        from utils.image_trace import EVENT_NAMES, MODULE_NAMES, normalize_event, normalize_module

        modules = {normalize_module(name) for name in MODULE_NAMES}
        events = {normalize_event(name) for name in EVENT_NAMES}
        self.assertTrue(all(len(item) == 4 for item in modules))
        self.assertTrue(all(len(item) == 5 for item in events))
        api_line = format_trace_line(
            timestamp=datetime(2026, 9, 21, 9, 3, 48),
            level="INFO",
            trace_id="img-1",
            module="api",
            event="api.start",
            stage_ms=0,
            total_ms=0,
        )
        poll_line = format_trace_line(
            timestamp=datetime(2026, 9, 21, 9, 3, 49),
            level="INFO",
            trace_id="img-1",
            module="image.poll",
            event="image_poll_end",
            stage_ms=2000,
            total_ms=2000,
        )
        self.assertEqual(api_line.index("module="), poll_line.index("module="))
        self.assertEqual(api_line.index("event="), poll_line.index("event="))
        self.assertEqual(api_line.index("stage="), poll_line.index("stage="))
        self.assertLess(api_line.index("trace_id="), api_line.index("module="))

    def test_ensure_trace_log_creates_empty_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-trace.log"
            created = ensure_trace_log(path)
            self.assertEqual(created, path)
            self.assertTrue(path.exists())

    def test_reset_trace_log_clears_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-trace.log"
            path.write_text("old line\n", encoding="utf-8")
            reset_trace_log(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_trace_log_is_noop_without_active_trace(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-trace.log"
            reset_image_trace()
            trace_log("api", "api.start")
            self.assertFalse(path.exists())


    def test_http_step_from_url(self) -> None:
        from utils.image_trace import http_step_from_url, short_http_path

        self.assertEqual(http_step_from_url("https://chatgpt.com/"), "boot")
        self.assertEqual(http_step_from_url("https://chatgpt.com/backend-api/sentinel/chat-requirements/prepare"), "req")
        self.assertEqual(http_step_from_url("https://chatgpt.com/backend-api/f/conversation/prepare"), "conv")
        self.assertEqual(short_http_path("https://chatgpt.com/backend-api/sentinel/chat-requirements/prepare"), "/sentinel/chat-requirements/prepare")

    def test_proxy_retry_writes_when_trace_active(self) -> None:
        from utils.image_trace import start_image_trace
        from services.proxy_service import request_with_proxy_retry

        class FakeSession:
            def request(self, method: str, url: str, **kwargs: object) -> None:
                raise TimeoutError("curl: (28) Operation timed out after 30002 milliseconds")

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-trace.log"
            start_image_trace({"x-request-id": "retry-1"}, log_path=path)
            with patch(
                "services.proxy_service.config.get_proxy_retry_settings",
                return_value={"interval_secs": 0, "rounds": 3},
            ):
                with self.assertRaises(TimeoutError):
                    request_with_proxy_retry(FakeSession(), "GET", "https://chatgpt.com/")
            text = path.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("event=http*"), 3)
        self.assertIn("step=boot", text)
        self.assertIn("status=retry", text)
        self.assertIn("status=fail", text)


if __name__ == "__main__":
    unittest.main()
