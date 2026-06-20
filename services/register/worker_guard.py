from __future__ import annotations

import threading
import time
from typing import Any, Callable

WORKER_MAX_SECONDS = 200.0

_local = threading.local()
_patches_installed = False


class WorkerDeadlineExceeded(TimeoutError):
    pass


def activate_worker_deadline(max_seconds: float = WORKER_MAX_SECONDS) -> None:
    _local.deadline = time.monotonic() + max(1.0, float(max_seconds))


def clear_worker_deadline() -> None:
    _local.deadline = None


def check_worker_deadline(step: str = "") -> None:
    deadline = getattr(_local, "deadline", None)
    if deadline is None:
        return
    if time.monotonic() > deadline:
        suffix = f"（{step}）" if step else ""
        raise WorkerDeadlineExceeded(f"注册任务超时{suffix}")


def _wrap_callable(original: Callable[..., Any], step: str) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        check_worker_deadline(step)
        result = original(*args, **kwargs)
        check_worker_deadline(step)
        return result

    return wrapper


def install_worker_guards() -> None:
    global _patches_installed
    if _patches_installed:
        return
    _patches_installed = True

    from services.register import mail_provider, openai_register

    if not getattr(openai_register.request_with_local_retry, "_worker_guard_wrapped", False):
        original_retry = openai_register.request_with_local_retry

        def guarded_retry(session, method, url, retry_attempts: int = 3, **kwargs):
            check_worker_deadline(f"HTTP {method.upper()} {url}")
            return original_retry(session, method, url, retry_attempts=retry_attempts, **kwargs)

        guarded_retry._worker_guard_wrapped = True  # type: ignore[attr-defined]
        openai_register.request_with_local_retry = guarded_retry

    if not getattr(mail_provider.wait_for_code, "_worker_guard_wrapped", False):
        original_wait = mail_provider.wait_for_code
        wrapped_wait = _wrap_callable(original_wait, "等待验证码")
        wrapped_wait._worker_guard_wrapped = True  # type: ignore[attr-defined]
        mail_provider.wait_for_code = wrapped_wait


def guarded_worker(index: int) -> dict:
    from services.register import openai_register, post_register_warmup

    install_worker_guards()
    activate_worker_deadline()
    try:
        result = openai_register.worker(index)
        if result.get("ok"):
            payload = result.get("result") if isinstance(result.get("result"), dict) else {}
            access_token = str(payload.get("access_token") or "").strip()
            if access_token:
                post_register_warmup.run_post_register_warmup(
                    access_token,
                    index=index,
                    step_fn=openai_register.step,
                )
        return result
    except WorkerDeadlineExceeded as error:
        return {"ok": False, "index": index, "error": str(error)}
    finally:
        clear_worker_deadline()
