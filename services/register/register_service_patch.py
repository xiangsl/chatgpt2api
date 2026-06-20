from __future__ import annotations

import threading
from typing import Any, Type

from services.register.runner_loop import run_register_loop
from services.register.runner_watchdog import RegisterRunnerWatchdog

_PATCHED = False


def patch_register_service(register_service_cls: Type[Any]) -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    original_init = register_service_cls.__init__
    original_start = register_service_cls.start
    original_stop = register_service_cls.stop
    original_run = register_service_cls._run

    def patched_init(self, store_file):
        self._runner_watchdog = RegisterRunnerWatchdog(self)
        original_init(self, store_file)
        self._runner_watchdog.start_monitor()

    def patched_start(self):
        self._runner_watchdog.reset_user_stop()
        return original_start(self)

    def patched_stop(self):
        self._runner_watchdog.request_user_stop()
        return original_stop(self)

    def patched_run(self):
        control = self._runner_watchdog.begin_run()
        try:
            run_register_loop(self, control)
        except Exception as error:
            self._append_log(f"注册线程异常退出: {error}，等待监控线程自动重启", "red")

    register_service_cls.__init__ = patched_init
    register_service_cls.start = patched_start
    register_service_cls.stop = patched_stop
    register_service_cls._run = patched_run

    register_service_cls._run_original = original_run  # noqa: SLF001 — 保留原版便于调试/对比
