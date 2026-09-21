from __future__ import annotations

import contextvars
import secrets
import threading
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()

REQUEST_ID_HEADERS = (
    "x-request-id",
    "request-id",
    "x-newapi-request-id",
    "x-new-api-request-id",
    "new-api-request-id",
    "x-oneapi-request-id",
    "x-one-api-request-id",
    "x-oneapi-requestid",
)


def default_log_path() -> Path:
    from services.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "image-trace.log"


def ensure_trace_log(log_path: Path | None = None) -> Path:
    path = log_path or default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()
    from utils.log import logger

    logger.info({"event": "image_trace_ready", "path": str(path.resolve())})
    return path


def reset_trace_log(log_path: Path | None = None) -> Path:
    path = log_path or default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        path.write_bytes(b"")
    from utils.log import logger

    logger.info({"event": "image_trace_reset", "path": str(path.resolve())})
    return path


def generate_trace_id(now: datetime | None = None) -> str:
    del now
    return f"img-{secrets.token_hex(4)}"


def resolve_trace_id(headers: Mapping[str, Any] | None) -> str:
    if headers is not None:
        lowered: dict[str, Any] = {}
        try:
            for key, value in headers.items():
                lowered[str(key).lower()] = value
        except Exception:
            lowered = {}
        for name in REQUEST_ID_HEADERS:
            text = str(lowered.get(name) or "").strip()
            if text:
                return text
        getter = getattr(headers, "get", None)
        if callable(getter):
            for name in REQUEST_ID_HEADERS:
                text = str(getter(name) or "").strip()
                if text:
                    return text
    return generate_trace_id()


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        items = ",".join(_format_value(item) for item in value)
        return items
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    if any(ch.isspace() for ch in text) or "=" in text:
        return '"' + text.replace('"', "'") + '"'
    return text


MODULE_WIDTH = 4
EVENT_WIDTH = 5

MODULE_NAMES = {
    "api": "api",
    "account": "acct",
    "upstream.prepare": "prep",
    "upstream.sse": "sse",
    "image.resolve": "rslv",
    "image.poll": "poll",
    "image.download": "down",
    "retry": "rtry",
}

EVENT_NAMES = {
    "api.start": "start",
    "api.end": "end",
    "account_acquired": "got",
    "image_bootstrap_end": "boot",
    "image_requirements_end": "req",
    "image_prepare_end": "conv",
    "image_25_prepare_end": "conv",
    "image_upload_end": "upld",
    "image_sse_start": "start",
    "image_sse_end": "end",
    "image_resolve_start": "start",
    "image_resolve_skip_poll": "skip",
    "image_poll_start": "start",
    "image_poll_end": "end",
    "image_download_start": "start",
    "image_download_end": "end",
    "image_poll_timeout_retry": "poll",
    "image_content_policy_retry": "plcy",
    "image_stream_skipped_mainline_retry": "main",
    "image_model_text_reply_retry": "text",
    "image_stream_tls_retry": "tls",
    "image_stream_conn_timeout_retry": "conn",
    "image_token_invalid_retry": "auth",
    "image_stream_sse_error_retry": "sse",
    "image_poll_backoff": "wait",
    "image_step_start": "go",
    "proxy_http_retry": "http",
    "image_pack_end": "pack",
}


def _pad_star(value: str, width: int) -> str:
    text = str(value or "")
    if len(text) >= width:
        return text
    return text + ("*" * (width - len(text)))


def normalize_module(module: str) -> str:
    return _pad_star(MODULE_NAMES.get(module, module), MODULE_WIDTH)


def normalize_event(event: str) -> str:
    return _pad_star(EVENT_NAMES.get(event, event), EVENT_WIDTH)


def classify_trace_error(message: object) -> str:
    text = str(message or "")
    lower = text.lower()
    if "生图超时" in text or ("poll" in lower and "timeout" in lower):
        return "poll_timeout"
    if "sse read timed out" in lower:
        return "sse_timeout"
    if (
        "curl: (28)" in lower
        or "connection timed out" in lower
        or "connect timeout" in lower
        or "upstream connection timed out" in lower
        or "operation timed out" in lower
    ):
        return "conn_timeout"
    if "429" in lower or "too many requests" in lower:
        return "http429"
    if "content policy" in lower or "content_policy" in lower:
        return "policy"
    if "timed out" in lower or "timeout" in lower:
        return "timeout"
    return ""


def _ms_to_seconds(value_ms: int) -> int:
    return max(0, int(value_ms) // 1000)


def _is_empty(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, (list, tuple, set, dict)) and not value:
        return True
    return False


def compact_trace_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(fields or {})
    width = data.pop("width", None)
    height = data.pop("height", None)
    if width and height and "size" not in data:
        data["size"] = f"{width}x{height}"
    data.pop("file_id", None)
    data.pop("file_size", None)
    if data.get("index") in (1, "1") and data.get("total") in (1, "1"):
        data.pop("index", None)
        data.pop("total", None)

    skip_always = {"prompt_len", "path", "duration_ms"}
    compacted: dict[str, Any] = {}
    for key, value in data.items():
        if key in skip_always or _is_empty(value):
            continue
        if key == "has_token" and value is True:
            continue
        if key in {"stream", "has_mask"} and value is False:
            continue
        if key in {"n", "image_count"} and value in (0, 1, "0", "1"):
            continue
        if key in {"plan_type", "source"} and value in {"", "-", "web"}:
            continue
        compacted[key] = value
    return compacted


def format_trace_line(
    *,
    timestamp: datetime,
    level: str,
    trace_id: str,
    module: str,
    event: str,
    stage_ms: int,
    total_ms: int,
    fields: Mapping[str, Any] | None = None,
) -> str:
    parts = [
        timestamp.strftime("%m-%d %H:%M:%S"),
        _pad_star(level.upper(), 7),
        f"trace_id={trace_id}",
        f"module={normalize_module(module)}",
        f"event={normalize_event(event)}",
        f"stage={_ms_to_seconds(stage_ms)}",
        f"total={_ms_to_seconds(total_ms)}",
    ]
    for key, value in compact_trace_fields(fields).items():
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def current_trace() -> ImageTrace | None:
    return _TRACE.get()


def start_image_trace(headers: Mapping[str, Any] | None = None, *, log_path: Path | None = None) -> ImageTrace:
    trace = ImageTrace(resolve_trace_id(headers), log_path=log_path)
    _TRACE.set(trace)
    return trace


def reset_image_trace() -> None:
    _TRACE.set(None)


def bind_trace(**fields: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.bind(**fields)


def trace_span(module: str) -> None:
    trace = current_trace()
    if trace is not None:
        trace.mark(module)


def trace_log(module: str, event: str, *, level: str = "INFO", **fields: Any) -> None:
    trace = current_trace()
    if trace is not None:
        trace.log(module, event, level=level, **fields)


def short_http_path(url: str) -> str:
    text = str(url or "").strip()
    try:
        from urllib.parse import urlparse

        path = urlparse(text).path or "/"
    except Exception:
        path = text
    parts = [item for item in path.split("/") if item]
    if not parts:
        return "/"
    if len(parts) > 3:
        path = "/" + "/".join(parts[-3:])
    else:
        path = "/" + "/".join(parts)
    return path[:80]


def http_step_from_url(url: str) -> str:
    path = short_http_path(url).lower()
    if path == "/":
        return "boot"
    if "chat-requirements" in path:
        return "req"
    if path.endswith("/conversation/prepare") or "/conversation/prepare" in path:
        return "conv"
    if "/files" in path:
        return "upld"
    if "/tasks" in path:
        return "task"
    if "/f/conversation" in path:
        return "sse"
    if "/conversation" in path:
        return "poll"
    return "http"


def trace_proxy_http_retry(
    *,
    method: str,
    url: str,
    attempt: int,
    rounds: int,
    sleep: float,
    exc: BaseException,
    final: bool,
    timeout: object = None,
) -> None:
    if current_trace() is None:
        return
    extra: dict[str, Any] = {
        "times": attempt,
        "rounds": rounds,
        "method": str(method or "GET").upper(),
        "step": http_step_from_url(url),
        "path": short_http_path(url),
        "status": "fail" if final else "retry",
        "err": type(exc).__name__,
        "error": str(exc)[:180],
    }
    why = classify_trace_error(exc)
    if why:
        extra["why"] = why
    if timeout is not None and timeout != "":
        extra["timeout"] = timeout
    if not final and sleep:
        extra["sleep"] = int(sleep)
    trace_log("retry", "proxy_http_retry", level="WARNING", **extra)


class ImageTrace:
    def __init__(self, trace_id: str, log_path: Path | None = None) -> None:
        self.trace_id = trace_id
        self.log_path = log_path or default_log_path()
        self._start = time.perf_counter()
        self._stage_started: dict[str, float] = {}
        self._bound: dict[str, Any] = {}
        self._ended = False

    def bind(self, **fields: Any) -> None:
        for key, value in fields.items():
            if value is None or value == "":
                continue
            self._bound[key] = value

    def mark(self, module: str) -> None:
        self._stage_started[module] = time.perf_counter()

    def log(self, module: str, event: str, *, level: str = "INFO", **fields: Any) -> None:
        if event == "api.end":
            if self._ended:
                return
            self._ended = True
        now = time.perf_counter()
        total_ms = int((now - self._start) * 1000)
        started = self._stage_started.get(module)
        stage_ms = int((now - started) * 1000) if started is not None else 0
        merged = dict(self._bound)
        merged.update(fields)
        line = format_trace_line(
            timestamp=datetime.now(),
            level=level,
            trace_id=self.trace_id,
            module=module,
            event=event,
            stage_ms=stage_ms,
            total_ms=total_ms,
            fields=merged,
        )
        _append_line(self.log_path, line)


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
                file.flush()
    except Exception as exc:
        from utils.log import logger

        logger.error({
            "event": "image_trace_write_failed",
            "path": str(path.resolve()),
            "error": str(exc),
        })


_TRACE: contextvars.ContextVar[ImageTrace | None] = contextvars.ContextVar("image_trace", default=None)
