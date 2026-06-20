from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from services.register.runner_loop import RunnerControl

if TYPE_CHECKING:
    from services.register_service import RegisterService

MONITOR_INTERVAL_SECONDS = 30.0
HEARTBEAT_STALE_SECONDS = 90.0
RUNNER_JOIN_SECONDS = 45.0


class RegisterRunnerWatchdog:
    def __init__(self, service: RegisterService) -> None:
        self._service = service
        self._lock = threading.RLock()
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._control: RunnerControl | None = None
        self._user_stop_requested = False

    def start_monitor(self) -> None:
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            self._monitor_stop.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="openai-register-watchdog",
            )
            self._monitor_thread.start()

    def reset_user_stop(self) -> None:
        with self._lock:
            self._user_stop_requested = False

    def begin_run(self) -> RunnerControl:
        with self._lock:
            generation = (self._control.generation + 1) if self._control else 1
            self._control = RunnerControl(generation=generation)
            return self._control

    def request_user_stop(self) -> None:
        with self._lock:
            self._user_stop_requested = True
            if self._control is not None:
                self._control.stop_event.set()

    def _runner_alive(self) -> bool:
        runner = getattr(self._service, "_runner", None)
        return runner is not None and runner.is_alive()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(MONITOR_INTERVAL_SECONDS):
            self._check_and_restart()

    def _check_and_restart(self) -> None:
        with self._lock:
            if self._user_stop_requested:
                return
            if not self._service._config.get("enabled"):
                return

            control = self._control
            if not self._runner_alive():
                reason = "注册线程未运行"
            elif control is not None and time.monotonic() - control.heartbeat_at > HEARTBEAT_STALE_SECONDS:
                reason = f"注册线程心跳超时（>{int(HEARTBEAT_STALE_SECONDS)}s）"
            else:
                return

            self._service._append_log(f"检测到{reason}，正在自动重启注册线程", "yellow")

        self._restart(reason)

    def _restart(self, reason: str) -> None:
        with self._lock:
            if self._control is not None:
                self._control.stop_event.set()
            runner = getattr(self._service, "_runner", None)

        if runner is not None and runner.is_alive():
            runner.join(timeout=RUNNER_JOIN_SECONDS)
            if runner.is_alive():
                self._service._append_log("旧注册线程未在时限内退出，跳过本次重启", "yellow")
                return

        with self._lock:
            if self._user_stop_requested or not self._service._config.get("enabled"):
                return
            if self._runner_alive():
                return

            self._service._runner = threading.Thread(
                target=self._service._run,
                daemon=True,
                name="openai-register",
            )
            self._service._runner.start()
            self._service._append_log(f"注册线程已自动重启（原因: {reason}）", "yellow")
