"""Thread-safe snapshot store for the mobile remote (§R.4).

The status poller runs on the Qt main thread (it reads QObject/libVLC state,
which must not happen off-thread) and publishes whole fresh dicts into this
store. The aiohttp server thread reads them for ``/api/status`` and the SSE
stream. The contract that makes ``dict()`` copies safe: a published snapshot
is never mutated afterwards — every poll builds a brand-new dict, so readers
always observe one complete, consistent version.
"""

from __future__ import annotations

import threading


class StatusStore:
    """Holds the latest status snapshot + a monotonic version counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict = {"app": "halcyon"}
        self._version = 0

    def update(self, snapshot: dict) -> None:
        """Publish a fresh snapshot (replaces, never mutates in place)."""
        with self._lock:
            self._snapshot = dict(snapshot)
            self._version += 1

    def snapshot(self) -> dict:
        """Latest complete snapshot. Safe to call from any thread."""
        with self._lock:
            return dict(self._snapshot)

    def version(self) -> int:
        with self._lock:
            return self._version
