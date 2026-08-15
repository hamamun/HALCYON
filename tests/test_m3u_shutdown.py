"""M3U shutdown hygiene — private load pool, bounded wait, cancelled emits.

The shutdown hang hunt (2026-08) flagged that M3U loaded playlists on
``QThreadPool.globalInstance()`` while every other component used a private
pool so it could drain it during teardown. These tests pin the fixed
behaviour:

* loads go to the context's own pool, never the shared global one;
* ``shutdown()`` is idempotent and blocks until in-flight loads have parked,
  with the ``cancelled`` flag silencing their signal emits;
* a worker that finishes after ``shutdown()`` reports nothing.

Mirrors the pattern Local already had (modes/local/playlist.py, §9).
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QThreadPool, Signal

from modes.m3u import parser
from modes.m3u.playlist import M3UContext
from modes.m3u.sources import KIND_URL


class _Engine(QObject):
    errorOccurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.currentMedia = ""

    def stop(self) -> None:
        pass

    def open(self, _url: str) -> None:
        pass


class _Controller(QObject):
    activeModeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.activeMode = "m3u"

    def stop(self) -> None:
        pass


class _Settings:
    def __init__(self, path) -> None:
        self.path = path
        self.values = {}

    def get_mode(self, _mode: str, _key: str, default):
        return default

    def set_mode(self, mode: str, key: str, value) -> None:
        self.values[(mode, key)] = value


def _make_context(tmp_path) -> M3UContext:
    context = M3UContext(_Engine(), _Controller(), _Settings(tmp_path / "settings.json"))
    context.addSource("IPTV", "http://example.com/list.m3u8", KIND_URL)
    source = context._store.list()[0]
    return context, source.id


def test_loads_go_to_a_private_pool_never_the_global_one(tmp_path) -> None:
    context, source_id = _make_context(tmp_path)

    assert context._pool is not None
    assert context._pool is not QThreadPool.globalInstance()

    started = threading.Event()
    release = threading.Event()

    def _blocking_fetch(_url: str) -> str:
        started.set()
        release.wait(10)
        return "#EXTM3U\n"

    parser.fetch_playlist = _blocking_fetch
    try:
        context.loadSource(source_id)
        assert started.wait(5), "load worker never started"
        # The load is parked inside the fetch right now. Had it run on the
        # global pool, the global pool would report an active thread; on the
        # private pool it must not.
        assert QThreadPool.globalInstance().activeThreadCount() == 0
    finally:
        release.set()
        context.shutdown()
    assert context._inflight == {}


def test_shutdown_is_idempotent_and_waits_for_inflight_loads(tmp_path) -> None:
    context, source_id = _make_context(tmp_path)

    started = threading.Event()
    release = threading.Event()

    def _blocking_fetch(_url: str) -> str:
        started.set()
        release.wait(10)
        return "#EXTM3U\n"

    parser.fetch_playlist = _blocking_fetch
    try:
        context.loadSource(source_id)
        assert started.wait(5), "load worker never started"

        # shutdown() must not return while the load is still running.
        result: list[bool] = []

        def _shutdown() -> None:
            context.shutdown()
            result.append(True)

        thread = threading.Thread(target=_shutdown)
        thread.start()
        time.sleep(0.2)
        assert thread.is_alive(), "shutdown() returned while a load was in flight"
        assert result == []

        release.set()
        thread.join(10)
        assert not thread.is_alive(), "shutdown() never returned after the load parked"
        assert result == [True]

        # Idempotent: a second call returns immediately and stays a no-op.
        context.shutdown()
        context.shutdown()
    finally:
        release.set()
        context.shutdown()

    assert context._inflight == {}


def test_worker_emits_are_silenced_after_shutdown(tmp_path) -> None:
    """A load that finishes after shutdown reports nothing (no emit into a
    receiver that is about to go away)."""
    context, source_id = _make_context(tmp_path)
    source = context._store.get(source_id)

    from modes.m3u.playlist import _LoadSignals, _LoadWorker

    delivered: list[str] = []
    # A worker finishing *after* shutdown() has set the cancelled flag must
    # stay silent: its signal QObject is about to be collected at exit.
    cancelled = _LoadSignals(context)
    cancelled.cancelled = True
    cancelled.succeeded.connect(lambda sid, text: delivered.append("succeeded"))
    cancelled.failed.connect(lambda sid, msg: delivered.append("failed"))

    parser.fetch_playlist = lambda _url: "#EXTM3U\n"
    _LoadWorker(source, cancelled).run()
    assert delivered == []

    # Sanity: without the flag, the same worker does emit.
    live = _LoadSignals(context)
    live.succeeded.connect(lambda sid, text: delivered.append("succeeded"))
    _LoadWorker(source, live).run()
    assert delivered == ["succeeded"]
