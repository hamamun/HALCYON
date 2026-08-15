"""Opt-in watchdog that captures *where* a shutdown is stuck.

This module exists to diagnose a single, specific problem: the Halcyon window
closes, the visible cleanup logs print ("taskbar preview shutdown", "mobile
remote stopped", "engine shut down"), Qt emits ``QObject::disconnect:
Unexpected nullptr parameter`` — and then the Python process never exits. The
terminal stays frozen and ``python.exe`` lingers in Task Manager until it is
killed.

**Why this is out-of-process.** The first version of this tracer was an
in-process daemon thread that called :func:`faulthandler.dump_traceback`. It
produced no output file at all. That null result is itself the finding: a
Python thread can only run when it holds the GIL, and the main thread is
blocked inside a native Qt call during QML teardown *while still holding the
GIL*. No in-process Python code can ever be scheduled again, so no in-process
tracer can report anything.

The only observer that can see a GIL-held native hang is one that is not
subject to the GIL — a separate OS process. So:

* :meth:`start` records intent and logs that the tracer is armed;
* :meth:`arm` is called once from ``aboutToQuit``, right before teardown, and
  spawns :mod:`core.shutdown_trace_helper` as a detached child process with the
  parent's PID, an output path, and a grace period;
* the helper waits out the grace period on the parent's *process handle*. If
  Halcyon exits normally (the healthy case) the wait returns immediately, the
  helper exits, and nothing is written;
* if Halcyon is still alive when the grace expires, the helper suspends every
  thread in the parent, reads each thread's instruction pointer, maps it to the
  owning DLL, writes a per-thread report and a minidump, then resumes the
  threads.

:meth:`cancel` is deliberately a **no-op**. In the healthy case the process is
already gone, and the helper detects that on its own via the process handle;
there is nothing left in-process that could reliably signal the child anyway,
which is precisely the constraint that forced this design.

Nothing here is imported or started unless ``--trace-shutdown`` (or
``HALCYON_TRACE_SHUTDOWN=1``) is supplied. It has zero effect on normal runs —
no threads, no timers, no signal connections — and never touches playback, VLC,
or QML.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("halcyon.shutdown_trace")

#: Seconds between "arm" and the snapshot. Long enough that a *normal* exit
#: (which typically completes well under a second) never triggers it, but short
#: enough that the user does not sit waiting.
DEFAULT_GRACE = 5.0

#: ``CREATE_NO_WINDOW`` — the helper is a console script, and without this flag
#: Windows would flash a console window in the user's face at every shutdown.
CREATE_NO_WINDOW = 0x08000000

#: ``DETACHED_PROCESS`` — the helper must outlive the parent it is watching, so
#: it must not share (or be tied to) the parent's console.
DETACHED_PROCESS = 0x00000008

#: Filename of the helper, resolved next to this module.
_HELPER_NAME = "shutdown_trace_helper.py"


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
    """Launches an out-of-process watcher if shutdown stalls.

    The public surface is unchanged from the in-process version
    (:meth:`start` / :meth:`arm` / :meth:`cancel`) so ``main.py`` needs no
    edits, but the mechanism behind it is entirely different.
    """

    def __init__(self, dump_path: Path, grace: float = DEFAULT_GRACE) -> None:
        self._dump_path = Path(dump_path)
        self._grace = float(grace)
        self._helper = Path(__file__).resolve().parent / _HELPER_NAME
        self._started = False
        self._child: subprocess.Popen | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Arm the tracer for the session. Cheap: nothing is spawned yet.

        The helper is not launched here because a process that sits watching
        for the entire session is both wasteful and easy to orphan. It is
        launched at :meth:`arm`, when shutdown actually begins.
        """
        if self._started:
            return
        self._started = True
        if not self._helper.is_file():
            log.warning(
                "shutdown tracer requested but helper is missing at %s", self._helper
            )
            return
        log.info(
            "shutdown tracer armed — if the process hangs on close, a thread "
            "report and minidump will be written next to %s",
            self._dump_path,
        )

    def arm(self) -> None:
        """Shutdown has begun: spawn the external watcher.

        Called from ``aboutToQuit`` before any cleanup runs, so a hang inside
        cleanup itself is captured as well as one during QML teardown.
        """
        if not self._started or self._child is not None:
            return
        if not self._helper.is_file():
            return

        cmd = [
            sys.executable,
            str(self._helper),
            str(os.getpid()),
            str(self._dump_path),
            str(self._grace),
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = CREATE_NO_WINDOW | DETACHED_PROCESS

        try:
            self._child = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
                cwd=str(self._dump_path.parent if self._dump_path.parent.exists() else Path.cwd()),
            )
        except Exception:
            # A diagnostic that breaks shutdown is worse than no diagnostic.
            log.debug("shutdown tracer helper could not be launched", exc_info=True)

    def cancel(self) -> None:
        """No-op, by design.

        Kept so ``main.py`` can call it unconditionally after ``app.exec()``
        returns. There is nothing to cancel: the helper decides for itself
        whether to report, by waiting on this process's handle. If we exited
        normally it sees that and writes nothing.
        """
        return
