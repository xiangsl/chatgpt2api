from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.register.worker_guard import WORKER_MAX_SECONDS, guarded_worker


WAIT_SLICE_SECONDS = 15.0


@dataclass
class RunnerControl:
    stop_event: threading.Event = field(default_factory=threading.Event)
    heartbeat_at: float = field(default_factory=time.monotonic)
    generation: int = 0

    def heartbeat(self) -> None:
        self.heartbeat_at = time.monotonic()

    def should_stop(self) -> bool:
        return self.stop_event.is_set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_register_loop(service, control: RunnerControl) -> None:
    threads = int(service.get()["threads"])
    snapshot = service.get()
    stats = snapshot.get("stats") if isinstance(snapshot.get("stats"), dict) else {}
    submitted = int(stats.get("done") or 0)
    done = submitted
    success = int(stats.get("success") or 0)
    fail = int(stats.get("fail") or 0)
    executor = ThreadPoolExecutor(max_workers=threads)
    futures: dict = {}
    forced_stop = False
    completed_normally = False

    try:
        while not control.should_stop():
            control.heartbeat()
            cfg = service.get()
            while (
                not control.should_stop()
                and service.get()["enabled"]
                and not service._target_reached(cfg, submitted)
                and len(futures) < threads
            ):
                submitted += 1
                future = executor.submit(guarded_worker, submitted)
                futures[future] = time.monotonic()

            service._bump(running=len(futures), done=done, success=success, fail=fail)

            if not futures and (not service.get()["enabled"] or str(cfg.get("mode") or "total") == "total"):
                completed_normally = True
                break

            if not futures:
                interval = max(1, int(cfg.get("check_interval") or 5))
                if control.stop_event.wait(interval):
                    forced_stop = True
                    break
                continue

            finished, pending = wait(set(futures.keys()), timeout=WAIT_SLICE_SECONDS, return_when=FIRST_COMPLETED)
            control.heartbeat()

            now = time.monotonic()
            for future in list(pending):
                started_at = futures.get(future, now)
                if now - started_at <= WORKER_MAX_SECONDS:
                    continue
                service._append_log(
                    f"注册 worker 超时({int(WORKER_MAX_SECONDS)}s)，标记失败并继续调度",
                    "yellow",
                )
                future.cancel()
                futures.pop(future, None)
                done += 1
                fail += 1

            for future in finished:
                started_at = futures.pop(future, now)
                done += 1
                try:
                    result = future.result(timeout=0)
                    if result.get("ok"):
                        success += 1
                    else:
                        fail += 1
                except Exception:
                    fail += 1
                if time.monotonic() - started_at > WORKER_MAX_SECONDS:
                    service._append_log(
                        f"注册 worker 在 {int(time.monotonic() - started_at)}s 后结束（已超出上限）",
                        "yellow",
                    )
    finally:
        fast_shutdown = control.should_stop() or forced_stop or not completed_normally
        if fast_shutdown:
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=True, cancel_futures=False)

        bump_kwargs = {"running": 0, "done": done, "success": success, "fail": fail}
        if completed_normally:
            bump_kwargs["finished_at"] = _now()
        service._bump(**bump_kwargs)

    if control.should_stop() or forced_stop:
        return
    if not completed_normally:
        return

    with service._lock:
        service._config["enabled"] = False
        service._save()
    service._append_log(f"注册任务结束，成功{success}，失败{fail}", "yellow")
