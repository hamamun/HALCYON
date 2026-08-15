"""Opt-in watchdog that captures *where* a shutdown is stuck.

This module exists to diagnose a single, specific problem: the Halcyon window
closes, the visible cleanup logs print, but the Python process never exits and
the terminal stays frozen. A normal log cannot show that, because the process
is blocked inside Qt's own QML object destruction — after ``on_quit`` has
returned — where there is no Python frame to log from.

The approach is deliberately external to the shutdown path itself:

* a daemon thread sits idle for the whole session;
* :meth:`arm` is called once from ``aboutToQuit``, right before teardown;
* if the process exits within ``grace`` seconds (the healthy case), the thread
  is killed by interpreter shutdown and produces no output;
* if it is *still alive* after ``grace`` seconds, it writes ``faulthandler``
  stack dumps for **every** Python thread to a file, then keeps dumping every
  ``interval`` seconds so we can tell a thread that is merely slow from one
  that is genuinely blocked at the same C call.

Nothing here is imported or started unless ``--trace-shutdown`` (or
``HALCYON_TRACE_SHUTDOWN=1``) is supplied. It has zero effect on normal runs —
no threads, no timers, no signal connections — and never touches playback,
VLC, or QML. The thread is a daemon, so even in the worst case it cannot keep
the process alive by itself.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("halcyon.shutdown_trace")

#: Seconds between "arm" and the first dump. Long enough that a *normal* exit
#: (which typically completes well under a second) never triggers it, but short
#: enough that the user does not sit waiting.
DEFAULT_GRACE = 4.0

#: Seconds between repeated dumps after the first.
DEFAULT_INTERVAL = 2.0

#: Cap on how many dumps we write, so a truly abandoned process does not fill a
#: disk. Each dump is a few kilobytes.
DEFAULT_MAX_DUMPS = 6


def enabled(argv: list[str] | None = None) -> bool:
    """True when the user asked for a shutdown trace."""
    if argv is None:
        argv = sys.argv
    if "--trace-shutdown" in argv[1:]:
        return True
    return os.environ.get("HALCYON_TRACE_SHUTDOWN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class ShutdownTracer:
    """Daemon watchdog that dumps all thread stacks if shutdown stalls."""

    def __init__(
        self,
        dump_path: Path,
        grace: float = DEFAULT_GRACE,
        interval: float = DEFAULT_INTERVAL,
        max_dumps: int = DEFAULT_MAX_DUMPS,
    ) -> None:
        self._dump_path = Path(dump_path)
        self._grace = float(grace)
        self._interval = float(interval)
        self._max_dumps = int(max_dumps)
        self._armed = threading.Event()
        self._cancel = threading.Event()
        self._arm_time: float | None = None
        self._thread = threading.Thread(
            target=self._run, name="halcyon-shutdown-trace", daemon=True
        )

    def start(self) -> None:
        """Spawn the (idle) watcher thread. Safe to call once."""
        if self._thread.is_alive():
            return
        self._thread.start()
        log.info(
            "shutdown tracer armed — if the process hangs on close, stacks will "
            "be written to %s",
            self._dump_path,
        )

    def arm(self) -> None:
        """Mark that shutdown has begun. The grace countdown starts now.

        Called from ``aboutToQuit`` before any cleanup runs, so even if cleanup
        itself blocks we still get a dump.
        """
        self._arm_time = time.monotonic()
        self._armed.set()

    def cancel(self) -> None:
        """Cancel a pending dump (used if shutdown completes normally)."""
        self._cancel.set()

    def _run(self) -> None:
        # Wait until shutdown begins.
        self._armed.wait()
        # Then wait for healthy exit. If the process exits during this wait,
        # the daemon thread dies silently with no output.
        if self._cancel.wait(timeout=self._grace):
            return

        try:
            self._dump_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # If we can't write next to the repo, fall back to the temp dir so
            # the diagnostic still lands somewhere retrievable.
            import tempfile

            self._dump_path = Path(tempfile.gettempdir()) / self._dump_path.name

        for n in range(1, self._max_dumps + 1):
            self._write_dump(n)
            if self._cancel.wait(timeout=self._interval):
                return

    def _write_dump(self, n: int) -> None:
        now = time.monotonic()
        elapsed = (now - self._arm_time) if self._arm_time else 0.0
        header = (
            f"\n{'=' * 72}\n"
            f"HALCYON SHUTDOWN TRACE — dump #{n} at {elapsed:.2f}s after "
            f"aboutToQuit\n"
            f"process still alive; if this is the last entry, a native/Qt call "
            f"is blocking\n"
            f"{'=' * 72}\n"
        )
        try:
            with open(self._dump_path, "a", encoding="utf-8") as fh:
                fh.write(header)
                fh.flush()
                # dump_traceback with all_threads=True writes every Python
                # thread's current frame. The GUI thread will usually show the
                # last Python frame before it entered the blocking C call.
                faulthandler.dump_traceback(fh, all_threads=True)
                fh.write("\n")
            log.warning(
                "shutdown tracer: process still alive %.1fs after aboutToQuit — "
                "stack dump #%d written to %s",
                elapsed,
                n,
                self._dump_path,
            )
        except Exception:
            log.exception("shutdown tracer could not write %s", self._dump_path)
