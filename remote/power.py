"""PC power actions for the mobile remote — ⚡ Power (§R.2).

Sleep and Shutdown act on the PC running Halcyon. The commands are OS-level
and injectable for tests: an executor is a ``callable(list[str]) -> int``;
defaults to ``subprocess.run``. Nothing here touches Qt, so the calls are
safe from either thread.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger(__name__)


def _default_executor(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, timeout=10).returncode
    except Exception as exc:  # pragma: no cover — OS dependent
        log.warning("power command %s failed: %s", argv, exc)
        return 1


def _sleep_argv() -> list[str]:
    if sys.platform == "win32":
        # SetSuspendState 0,1,0 = suspend (not hibernate), no wake timer.
        return ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"]
    return ["systemctl", "suspend"]


def _shutdown_argv() -> list[str]:
    if sys.platform == "win32":
        return ["shutdown", "/s", "/t", "0"]
    return ["systemctl", "poweroff"]


def sleep_pc(executor=_default_executor) -> bool:
    """Put the PC to sleep. Returns True when the command was issued."""
    return executor(_sleep_argv()) == 0


def shutdown_pc(executor=_default_executor) -> bool:
    """Shut the PC down. Returns True when the command was issued."""
    return executor(_shutdown_argv()) == 0
