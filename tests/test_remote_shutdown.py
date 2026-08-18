"""Remote shutdown must leave nothing behind (§R.4).

The bug these tests pin: with a phone holding the ``/api/events`` SSE stream
open, closing Halcyon left the server thread running. ``/api/events`` looped
forever on a bare sleep, ``AppRunner.cleanup()`` waits for live handlers with
aiohttp's 60 s default grace, and ``stop()`` gave up after 5 s and dropped the
thread and loop handles — so the window closed, the terminal never returned
and ``python.exe`` stayed in Task Manager.

Every test here is about *teardown*, never about a feature. They are written
against the observable contract (no live thread, port released, loop closed)
rather than the implementation, so they keep their meaning if the internals
are rewritten again.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from remote.server import STOP_JOIN_TIMEOUT, RemoteServer
from remote.status import StatusStore


def _remote_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "halcyon-remote"]


def _port_is_free(port: int) -> bool:
    """True when nothing is listening on ``port`` any more."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex(("127.0.0.1", port)) != 0
    finally:
        sock.close()


class _SseClient:
    """Holds an /api/events stream open from a background thread.

    This is the phone. Its whole job is to still be connected at the moment
    the server is asked to stop.

    ``connected`` fires when the response *headers* arrive, not on the first
    data chunk: with no bridge wired there is no snapshot to push, so the
    stream is legitimately silent — but the handler is running, which is the
    condition that used to block cleanup.
    """

    def __init__(self, port: int) -> None:
        self.url = f"http://127.0.0.1:{port}/api/events"
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.status: int | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            resp = urllib.request.urlopen(self.url, timeout=30)
            self.status = resp.status
            self.connected.set()
            try:
                while resp.read(1):
                    pass
            finally:
                resp.close()
        except Exception:
            pass
        finally:
            self.connected.set()
            self.finished.set()

    def await_connected(self, timeout: float = 5.0) -> bool:
        return self.connected.wait(timeout)

    def join(self, timeout: float) -> bool:
        return self.finished.wait(timeout)


class _NonReadingSseClient:
    """A phone whose browser accepted the stream and then stopped draining it."""

    def __init__(self, port: int) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Keep the receive window small so a large snapshot reaches transport
        # back-pressure promptly on every OS, including Windows CI.
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        self._socket.settimeout(5.0)
        self._socket.connect(("127.0.0.1", port))
        self._socket.sendall(
            b"GET /api/events HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Accept: text/event-stream\r\n\r\n"
        )
        headers = bytearray()
        while b"\r\n\r\n" not in headers:
            chunk = self._socket.recv(1)
            if not chunk:
                break
            headers.extend(chunk)
        assert b"200 OK" in headers
        # Deliberately never read the event body.

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


class _LargeSnapshotBridge:
    """Enough payload to block a client with a closed receive window."""

    def __init__(self) -> None:
        self.store = StatusStore()
        self.store.update({"app": "halcyon", "payload": "x" * 16_000_000})

    def set_server_url(self, _url: str) -> None:
        pass


@pytest.fixture()
def server():
    srv = RemoteServer(port=0)
    assert srv.start(), "server should start (aiohttp is installed in the venv)"
    yield srv
    srv.stop()


# --------------------------------------------------------------- the bug ---
def test_stop_ends_the_server_thread_with_an_open_sse_stream(server):
    """The regression itself: a connected phone must not keep the thread up."""
    client = _SseClient(server.port)
    client.start()
    assert client.await_connected(), "SSE stream never opened"

    started = time.monotonic()
    assert server.stop() is True
    elapsed = time.monotonic() - started

    assert not _remote_threads(), "server thread outlived stop()"
    # Comfortably under the old 5 s give-up, let alone aiohttp's 60 s grace.
    assert elapsed < STOP_JOIN_TIMEOUT, f"stop() took {elapsed:.1f}s"


def test_stop_aborts_a_non_reading_phone_without_a_graceful_final_write():
    """A backgrounded phone must not hold prepare/write/write_eof open.

    The older test client continuously drained the body, so aiohttp's final
    write always succeeded and the real mobile failure was never represented.
    This raw client reads the headers and then closes its receive window in
    practice by never consuming the 16 MB snapshot.
    """
    srv = RemoteServer(bridge=_LargeSnapshotBridge(), port=0)
    assert srv.start()
    loop = srv._loop
    # A real browser fetches the static shell before opening EventSource. That
    # creates aiohttp's default-executor worker, another resource which must be
    # gone before process finalization.
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/", timeout=5) as response:
        response.read()
    client = _NonReadingSseClient(srv.port)
    try:
        started = time.monotonic()
        assert srv.stop() is True
        elapsed = time.monotonic() - started
    finally:
        client.close()
        srv.stop()

    assert elapsed < STOP_JOIN_TIMEOUT
    assert not _remote_threads()
    assert not [thread for thread in threading.enumerate() if thread.name.startswith("asyncio")]
    assert loop is not None and loop.is_closed()
    assert srv._sse_tasks == set()
    assert srv._sse_transports == set()


def test_open_sse_stream_is_released_by_stop(server):
    """The stream itself must end, not just be abandoned by the server."""
    client = _SseClient(server.port)
    client.start()
    assert client.await_connected()

    server.stop()
    assert client.join(5.0), "SSE client was never released"


def test_stop_releases_the_port(server):
    port = server.port
    client = _SseClient(port)
    client.start()
    assert client.await_connected()

    server.stop()
    # Give the OS a moment to reap the socket.
    for _ in range(50):
        if _port_is_free(port):
            break
        time.sleep(0.1)
    assert _port_is_free(port), "listening socket still bound after stop()"


def test_stop_closes_the_event_loop(server):
    loop = server._loop
    assert loop is not None
    server.stop()
    assert loop.is_closed(), "event loop was left open"


def test_stop_clears_its_handles(server):
    server.stop()
    assert server._thread is None
    assert server._loop is None
    assert server._runner is None
    assert server._site is None


# ------------------------------------------------------- shutdown gating ---
def test_commands_are_refused_once_stopping(server):
    server.stop()
    # The socket is closed, so the command cannot even be delivered — which is
    # the point: no outside input reaches a torn-down player.
    with pytest.raises(Exception):
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/cmd",
            data=json.dumps({"action": "playPause"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)


def test_stopping_flag_is_visible(server):
    assert server.stopping is False
    server.stop()
    assert server.stopping is True


def test_start_after_stop_is_refused(server):
    server.stop()
    assert server.start() is False, "a stopped server must not resurrect"
    assert not _remote_threads()


# ------------------------------------------------------------ robustness ---
def test_stop_is_idempotent_and_leaves_no_thread(server):
    server.stop()
    server.stop()
    server.stop()
    assert not _remote_threads()


def test_stop_without_any_client(server):
    assert server.stop() is True
    assert not _remote_threads()


def test_failed_join_retains_live_handles_and_reports_false(monkeypatch):
    """Never claim success or discard the only handle to a surviving thread."""

    class StuckThread:
        def __init__(self) -> None:
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout=None) -> None:
            pass

    stuck = StuckThread()
    srv = RemoteServer(port=0)
    srv._thread = stuck
    srv._started = True
    monkeypatch.setattr("remote.server.STOP_JOIN_TIMEOUT", 0.01)

    assert srv.stop() is False
    assert srv._thread is stuck

    # Once the owner really has ended, the same idempotent stop may clear it.
    stuck.alive = False
    assert srv.stop() is True
    assert srv._thread is None


def test_many_streams_all_released(server):
    clients = [_SseClient(server.port) for _ in range(5)]
    for c in clients:
        c.start()
    for c in clients:
        assert c.await_connected()

    server.stop()
    assert not _remote_threads()
    for c in clients:
        assert c.join(5.0), "a stream was left hanging"


def test_never_started_server_stops_cleanly():
    """aiohttp missing, or simply never started — stop() must be a no-op."""
    srv = RemoteServer(port=0)
    srv.stop()
    assert not _remote_threads()


def test_bind_failure_leaves_no_thread():
    """A port collision must not leak the thread that tried to bind."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        srv = RemoteServer(port=port)
        assert srv.start() is False, "binding a taken port should fail"
        # The thread that tried to bind must be gone, not lingering.
        for _ in range(50):
            if not _remote_threads():
                break
            time.sleep(0.1)
        assert not _remote_threads()
        srv.stop()
    finally:
        blocker.close()


# ------------------------------------------------------------ the bridge ---
# The server is only half of shutdown. The bridge holds the controller, the
# engine and every mode context, arms a 40 ms singleShot after each command,
# and runs a 300 ms poll timer — all of which can fire into objects Qt is
# already destroying unless stop() closes it properly.

from PySide6.QtCore import QCoreApplication, QObject  # noqa: E402

from remote.bridge import RemoteBridge  # noqa: E402


def _pump(ms: int = 300) -> None:
    app = QCoreApplication.instance()
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


class _FakeEngine(QObject):
    def __init__(self):
        super().__init__()
        self.calls = []

    def isPlaying(self): return False
    def time(self): return 0
    def duration(self): return 1000
    def position(self): return 0.0
    def volume(self): return 50
    def muted(self): return False
    def rate(self): return 1.0
    def seek(self, ms): self.calls.append(("seek", ms))


class _FakeController(QObject):
    def __init__(self):
        super().__init__()
        self.calls = []

    def activeMode(self): return "local"
    def playPause(self): self.calls.append("playPause")
    def currentPlaybackLabel(self): return ""
    @property
    def currentFileStem(self): return ""
    def audioTracks(self): return []
    def subtitleTracks(self): return []
    def currentAudioId(self): return -1
    def currentSubtitleId(self): return -1
    def subtitleDelayMs(self): return 0


@pytest.fixture()
def bridge():
    b = RemoteBridge(controller=_FakeController(), engine=_FakeEngine())
    yield b
    b.stop()


def test_bridge_stop_halts_the_poll_timer(bridge):
    assert bridge._timer.isActive()
    bridge.stop()
    assert not bridge._timer.isActive()


def test_bridge_ignores_commands_after_stop(bridge):
    controller = bridge._controller
    bridge.stop()
    bridge.request("playPause", {})
    _pump()
    assert not controller.calls, "a command was executed during teardown"


def test_bridge_drops_a_command_already_in_flight(bridge):
    """Queued delivery means a command can be emitted before stop and land after."""
    controller = bridge._controller
    bridge.request("playPause", {})  # queued, not yet delivered
    bridge.stop()                    # the window closes first
    _pump()
    assert not controller.calls, "an in-flight command reached a dead player"


def test_bridge_stop_releases_the_player(bridge):
    bridge.stop()
    assert bridge._controller is None
    assert bridge._engine is None
    assert bridge._contexts == {}


def test_publish_after_stop_is_inert(bridge):
    """The 40 ms singleShot armed by the last command must not read a dead engine."""
    bridge.stop()
    bridge.publish_now()  # must not raise despite _engine being None
    _pump(100)


def test_bridge_stop_is_idempotent(bridge):
    bridge.stop()
    bridge.stop()
    bridge.stop()


def test_full_shutdown_order_leaves_nothing(bridge):
    """Server then bridge — the order main.py's on_quit uses."""
    srv = RemoteServer(bridge=bridge, port=0)
    assert srv.start()
    client = _SseClient(srv.port)
    client.start()
    assert client.await_connected()

    srv.stop()
    bridge.stop()

    assert not _remote_threads()
    assert client.join(5.0)
    assert not bridge._timer.isActive()


# ------------------------------------------------- the grace period itself ---
# SHUTDOWN_TIMEOUT reverting to aiohttp's 60 s default would restore the
# original bug silently — cleanup would once again outlast the join. The
# argument also *moved* between aiohttp releases (TCPSite up to 3.11,
# BaseRunner from 3.12) while requirements.txt still allows >=3.9, so passing
# it to the wrong object is a real way to lose it without any error.

def test_shutdown_timeout_is_far_below_the_join_timeout():
    from remote.server import SHUTDOWN_TIMEOUT

    assert SHUTDOWN_TIMEOUT < STOP_JOIN_TIMEOUT, (
        "cleanup must finish well inside the join, or stop() abandons the thread"
    )


def test_shutdown_timeout_is_actually_applied_not_aiohttps_default():
    from aiohttp import web

    from remote.server import SHUTDOWN_TIMEOUT, _make_runner

    runner, site_kwargs = _make_runner(web.Application())
    applied = getattr(runner, "shutdown_timeout", None)
    if applied is None:
        applied = getattr(runner, "_shutdown_timeout", None)

    if site_kwargs:
        # Older aiohttp: the site carries it instead.
        assert site_kwargs == {"shutdown_timeout": SHUTDOWN_TIMEOUT}
    else:
        assert applied == SHUTDOWN_TIMEOUT, (
            f"shutdown_timeout is {applied}, not {SHUTDOWN_TIMEOUT} — "
            "it silently reverted to aiohttp's default"
        )
