"""Remote HTTP server — lifecycle, routes, real-time push (Phase R, §R.4).

Step 1 proved the lifecycle (start last, stop first, guarded). This extends it
with the full API surface the phone UI talks to:

* ``/`` + ``/static/*`` — the phone web app (glass UI, §R.3).
* ``/health``, ``/qr.png`` — pairing (§R.1#3).
* ``/api/status`` — the current snapshot.
* ``/api/events`` — Server-Sent Events; pushes a new snapshot whenever the
  version counter moves (real-time sync, PC is the source of truth).
* ``/api/drives``, ``/api/browse`` — the drive browser (Local chip).
* ``/api/cmd`` — every mutation, delivered to :class:`remote.bridge.RemoteBridge`
  which marshals it onto the Qt thread.

Safety: all player state is read on the Qt thread by the bridge poller; this
thread only reads plain dicts and emits queued signals.

**Shutdown is the other half of the contract.** ``/api/events`` is an endless
handler by design — it only returns when the phone goes away. aiohttp's
``cleanup()`` waits for every in-flight handler before it finishes, so an
endless handler plus aiohttp's 60 s default grace meant the server thread
outlived the window by a minute while the app waited only five seconds for it
and then dropped the handle: an orphaned event loop, a still-bound port and a
``python.exe`` left in Task Manager. Three things fix it, and all three are
load-bearing:

* a shutdown :class:`asyncio.Event` the SSE loop *waits on* instead of
  sleeping, so every stream returns the instant shutdown starts;
* ``shutdown_timeout`` cut to :data:`SHUTDOWN_TIMEOUT`, so aiohttp can never
  sit on a straggler for a minute;
* a single close path that runs *on the server thread*: cancel leftover tasks,
  drain async generators and the default executor, then close the loop — the
  executor threads are non-daemon, and a live one blocks interpreter exit long
  after the window is gone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
from pathlib import Path

from remote import drives as drive_api
from remote import qr as qr_api

log = logging.getLogger(__name__)

try:  # optional dependency — Phase R (§R.4)
    from aiohttp import web

    _AIOHTTP = True
except ImportError:  # pragma: no cover — depends on the environment
    web = None
    _AIOHTTP = False

DEFAULT_PORT = 8765
BIND_HOST = "0.0.0.0"
STATIC_DIR = Path(__file__).resolve().parent / "static"

#: How long aiohttp may wait for in-flight handlers during ``cleanup()``.
#: aiohttp's own default is 60 s, which is a shutdown hang by any other name
#: for a server whose main endpoint is an infinite SSE stream. Our streams are
#: woken explicitly by :attr:`RemoteServer._closing`, so this is only a
#: backstop for a handler that ignores it.
SHUTDOWN_TIMEOUT = 1.0

#: Hard cap on :meth:`RemoteServer.stop`. Past this the thread is abandoned —
#: but it is a *daemon* thread whose loop has already been told to close, so
#: abandoning it cannot keep the process alive.
STOP_JOIN_TIMEOUT = 4.0

#: Cadence of the SSE snapshot push. Waiting on the shutdown event for this
#: long is exactly equivalent to sleeping for it, except it returns early when
#: shutdown starts.
SSE_TICK = 0.15


def available() -> bool:
    """True when aiohttp is installed and the server can actually run."""
    return _AIOHTTP


def _make_runner(app):
    """Build the AppRunner with :data:`SHUTDOWN_TIMEOUT` applied.

    ``shutdown_timeout`` moved between aiohttp releases: it was a ``TCPSite``
    argument up to 3.11 and became a ``BaseRunner`` argument in 3.12, where
    passing it to the site warns. ``requirements.txt`` allows ``aiohttp>=3.9``,
    so ask the signature rather than the version string and return the kwargs
    the *site* should get. Getting this wrong is not cosmetic — the value
    silently reverting to aiohttp's 60 s default is the whole bug.
    """
    import inspect

    try:
        on_runner = "shutdown_timeout" in inspect.signature(
            web.BaseRunner.__init__
        ).parameters
    except (TypeError, ValueError):  # pragma: no cover — exotic build
        on_runner = False

    if on_runner:
        return web.AppRunner(app, shutdown_timeout=SHUTDOWN_TIMEOUT), {}
    return web.AppRunner(app), {"shutdown_timeout": SHUTDOWN_TIMEOUT}


def lan_ip() -> str:
    """Best-effort LAN IPv4 of this machine; '' when none can be found."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return ""


class RemoteServer:
    """Owns the server thread, the aiohttp app and its lifecycle."""

    def __init__(self, bridge=None, settings=None, port: int | None = None):
        self._bridge = bridge
        self._settings = settings

        requested: int | None = port
        if requested is None and settings is not None:
            try:
                requested = int(settings.get("remote.port", DEFAULT_PORT))
            except (TypeError, ValueError):
                requested = None
        self._port = requested if requested is not None else DEFAULT_PORT

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._started = False
        self._ready = threading.Event()
        #: Set on the server loop the moment shutdown begins. Created there
        #: too: an asyncio.Event must belong to the loop that awaits it.
        self._closing: asyncio.Event | None = None
        #: True from the first stop() call onwards, readable from any thread.
        #: Guards against a late start() and against re-entering the teardown.
        self._stopping = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------- state ---
    @property
    def port(self) -> int:
        return self._port

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopping(self) -> bool:
        """True once :meth:`stop` has been entered. Safe from any thread."""
        return self._stopping

    @property
    def base_url(self) -> str:
        ip = lan_ip() or "127.0.0.1"
        return f"http://{ip}:{self._port}"

    # ------------------------------------------------------------- app -----
    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/qr.png", self._handle_qr)
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/events", self._handle_events)
        app.router.add_get("/api/drives", self._handle_drives)
        app.router.add_get("/api/browse", self._handle_browse)
        app.router.add_post("/api/cmd", self._handle_cmd)
        app.router.add_static("/static/", STATIC_DIR, show_index=False)
        return app

    # ---------------------------------------------------------- handlers ----
    async def _handle_index(self, _request: web.Request) -> web.StreamResponse:
        index = STATIC_DIR / "index.html"
        if index.exists():
            return web.FileResponse(index)
        return web.Response(
            text="<h1>Halcyon mobile remote</h1><p>Server is running.</p>",
            content_type="text/html",
        )

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "app": "halcyon",
                "pid": os.getpid(),
                "url": self.base_url,
                "qr": qr_api.available(),
            }
        )

    async def _handle_qr(self, _request: web.Request) -> web.Response:
        data = qr_api.qr_png_bytes(self.base_url)
        if data is None:
            return web.Response(status=503, text="qrcode is not installed")
        return web.Response(body=data, content_type="image/png")

    async def _handle_status(self, _request: web.Request) -> web.Response:
        if self._bridge is None:
            return web.json_response({"app": "halcyon", "connected": True})
        return web.json_response(self._bridge.store.snapshot())

    async def _handle_events(self, request: web.Request) -> web.StreamResponse:
        """SSE stream — pushes each new snapshot to the phone.

        Reduced from 0.4s to 0.15s polling for remote web responsiveness.
        Bridge also now emits publish_now on tab/bookmark/media changes via
        QTimer.singleShot(25ms), so bookmark taps feel <200ms.

        **This handler must end when the app closes.** It used to loop on a
        bare ``asyncio.sleep``, so it only ever returned when the phone hung
        up — and ``AppRunner.cleanup()``, which waits for live handlers,
        therefore waited out its full grace period on every close where a
        phone still had the page open. Waiting on ``self._closing`` instead of
        sleeping keeps the 0.15 s cadence identical while making shutdown
        immediate.
        """
        if self._stopping:
            # Shutdown already started; do not open a new endless stream.
            return web.Response(status=503, text="shutting down")

        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await resp.prepare(request)
        closing = self._closing
        last = -1
        try:
            while not self._stopping:
                if self._bridge is not None:
                    version = self._bridge.store.version()
                    if version != last:
                        last = version
                        payload = json.dumps(
                            self._bridge.store.snapshot(), ensure_ascii=False
                        )
                        await resp.write(f"data: {payload}\n\n".encode("utf-8"))
                if closing is None:  # pragma: no cover — defensive
                    await asyncio.sleep(SSE_TICK)
                    continue
                try:
                    # Returns early the instant shutdown starts; otherwise this
                    # is just the poll interval.
                    await asyncio.wait_for(closing.wait(), timeout=SSE_TICK)
                    break  # closing was set
                except asyncio.TimeoutError:
                    pass
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
            pass
        except Exception:  # pragma: no cover — a dead socket must not log-spam
            log.debug("remote SSE stream ended with an error", exc_info=True)
        return resp

    async def _handle_drives(self, _request: web.Request) -> web.Response:
        return web.json_response({"drives": drive_api.list_drives()})

    async def _handle_browse(self, request: web.Request) -> web.Response:
        path = request.query.get("path", "")
        try:
            listing = drive_api.list_dir(path)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError as exc:
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(listing)

    async def _handle_cmd(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)
        action = str(body.get("action", ""))
        payload = body.get("payload") or {}
        if not action:
            return web.json_response({"error": "missing action"}, status=400)
        if self._bridge is None:
            return web.json_response({"error": "bridge not wired"}, status=503)
        # Once shutdown has begun the player is being torn down; a command
        # accepted now would be dispatched into half-destroyed objects (§R.4:
        # the remote stops accepting outside input first).
        if self._stopping:
            return web.json_response({"error": "shutting down"}, status=503)
        self._bridge.request(action, payload)
        return web.json_response({"ok": True})

    # --------------------------------------------------------- lifecycle ----
    def start(self) -> bool:
        """Start serving on a daemon thread. Never raises.

        Returns True once the socket is listening, False when the server is
        unavailable (aiohttp missing) or failed to bind.
        """
        if self._started:
            return True
        if self._stopping:
            # A stop() has been issued; refuse to resurrect the server.
            return False
        if not _AIOHTTP:
            log.warning("mobile remote disabled — aiohttp is not installed")
            return False

        self._loop = asyncio.new_event_loop()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="halcyon-remote", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            log.error("mobile remote server failed to start within 10s")
            # The thread is still trying to bind. Tear it down rather than
            # leaking it: a half-started server is exactly the case that used
            # to leave a live thread nobody held a handle to any more.
            self.stop(force=True)
            # A failed start is not a shutdown — leave the object usable so a
            # caller may retry (e.g. after freeing the port).
            self._stopping = False
            return False
        if not self._started:
            # Bind failed (port in use, etc.). _run has already unwound its
            # loop; drop the handles so a later stop() is a clean no-op.
            self._join_thread()
        return self._started

    def _run(self) -> None:
        """Server thread body: bind, serve, and — always — close the loop.

        The loop is created in :meth:`start` but *closed here*, on the thread
        that owns it, after ``run_forever`` returns. Closing it from the
        caller's thread (or not at all, which is what happened before) leaves
        the selector, its socket and the loop's default executor alive.
        """
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        try:
            self._closing = asyncio.Event()
            self._runner, site_kwargs = _make_runner(self._build_app())
            loop.run_until_complete(self._runner.setup())
            self._site = web.TCPSite(
                self._runner, BIND_HOST, self._port, **site_kwargs
            )
            loop.run_until_complete(self._site.start())
            self._port = self._actual_port()
            self._started = True
            if self._bridge is not None:
                setter = getattr(self._bridge, "set_server_url", None)
                if setter is not None:
                    setter(self.base_url)
            log.info("mobile remote listening on %s", self.base_url)
        except Exception:
            log.exception("mobile remote server failed to start")
            self._started = False
            self._ready.set()  # never leave start() blocked
            self._close_loop(loop)
            return
        finally:
            self._ready.set()

        try:
            loop.run_forever()
        except Exception:  # pragma: no cover — loop failure is fatal anyway
            log.exception("mobile remote server loop ended unexpectedly")
        finally:
            self._started = False
            self._close_loop(loop)

    @staticmethod
    def _close_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Fully retire ``loop``. Runs on the server thread, never raises.

        ``run_forever`` returning is not the end of a loop's resources. Tasks
        may still be pending, async generators unfinalized, and — the one that
        actually keeps a process alive — the loop's default ``ThreadPoolExecutor``
        may hold *non-daemon* worker threads (aiohttp's static-file responses
        use it). Interpreter exit joins those threads, so skipping this is a
        hang with no Python frame to blame it on.
        """
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            log.debug("remote loop task cancellation failed", exc_info=True)
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            log.debug("remote loop asyncgen shutdown failed", exc_info=True)
        try:
            # Python 3.9+. This is the step that joins the executor's
            # non-daemon threads while we can still bound it.
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            log.debug("remote loop executor shutdown failed", exc_info=True)
        try:
            loop.close()
        except Exception:
            log.debug("remote loop close failed", exc_info=True)

    def _actual_port(self) -> int:
        try:
            return self._site._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]
        except Exception:
            return self._port

    def stop(self, force: bool = False) -> None:
        """Stop serving. Idempotent and safe to call from any thread.

        Ordered so nothing can be left behind:

        1. flip ``_stopping`` — new commands are refused and every SSE loop
           sees its exit condition on the next check;
        2. set the shutdown event *on the loop*, waking those loops now
           instead of at their next 0.15 s tick;
        3. ``runner.cleanup()`` — closes the listening socket and finishes the
           remaining handlers, bounded by :data:`SHUTDOWN_TIMEOUT`;
        4. ``loop.stop()``, which lets :meth:`_run` fall through to
           :meth:`_close_loop`;
        5. join the thread, bounded by :data:`STOP_JOIN_TIMEOUT`.

        The previous version returned immediately when ``_started`` was False,
        which skipped cleanup for a server still mid-bind, and it dropped the
        thread/loop handles even when the join timed out — the leak behind
        "window closed but python.exe is still in Task Manager".
        """
        with self._lock:
            if self._stopping and not force:
                # A stop is already in flight (or finished). Still wait for the
                # thread so callers can rely on stop() being synchronous.
                thread = self._thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=STOP_JOIN_TIMEOUT)
                return
            self._stopping = True
            thread = self._thread
            loop = self._loop

        self._started = False

        if loop is not None:

            def _schedule_cleanup() -> None:
                closing = self._closing
                if closing is not None:
                    closing.set()  # wake every SSE stream right now

                async def _cleanup() -> None:
                    try:
                        if self._site is not None:
                            # Close the listening socket first so no new
                            # connection can arrive during cleanup.
                            await self._site.stop()
                    except Exception:
                        log.debug("remote site stop failed", exc_info=True)
                    try:
                        if self._runner is not None:
                            await self._runner.cleanup()
                    except Exception:
                        log.debug("remote runner cleanup failed", exc_info=True)
                    finally:
                        loop.stop()

                loop.create_task(_cleanup())

            try:
                loop.call_soon_threadsafe(_schedule_cleanup)
            except RuntimeError:  # loop already closed — nothing to unwind
                pass

        if thread is not None and thread.is_alive():
            thread.join(timeout=STOP_JOIN_TIMEOUT)
            if thread.is_alive():
                # Should not happen: cleanup is bounded well under the join
                # timeout. Log loudly — a surviving thread here is precisely
                # the symptom we are fixing, and silence is what made it hard
                # to find last time. It is a daemon thread whose loop has been
                # told to stop, so it cannot hold the process open by itself.
                log.error(
                    "mobile remote thread still alive after %.1fs — "
                    "abandoning it (daemon, loop already stopped)",
                    STOP_JOIN_TIMEOUT,
                )

        with self._lock:
            self._thread = None
            self._loop = None
            self._runner = None
            self._site = None
            self._closing = None
        log.info("mobile remote stopped")

    def _join_thread(self) -> None:
        """Reap a thread whose loop already unwound (failed bind)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout=STOP_JOIN_TIMEOUT)
        with self._lock:
            self._thread = None
            self._loop = None
            self._runner = None
            self._site = None
            self._closing = None
