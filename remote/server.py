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
``python.exe`` left in Task Manager. The close path therefore uses independent
layers rather than trusting one cooperative timeout:

* stop accepting requests and set a shutdown event;
* abort every registered SSE socket (covering prepare, writes, and aiohttp's
  automatic final write), then cancel its task without swallowing cancellation;
* bound aiohttp cleanup and independently stop the event loop if cleanup itself
  fails to honour cancellation;
* cancel remaining tasks and retire the default executor before closing the
  loop. ``concurrent.futures`` joins all of its workers at interpreter exit,
  including workers that inherited daemon status from this server thread;
* retain and report any thread that somehow survives instead of logging a false
  success and throwing away the only handles that can still stop it.
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

#: Hard cap on the graceful aiohttp cleanup coroutine.  A second loop-level
#: stopper below is deliberately independent of this coroutine: cancellation
#: itself can stall in a third-party awaitable, so one timeout cannot safely
#: supervise another timeout.
CLEANUP_TIMEOUT = 2.0
LOOP_HARD_STOP_TIMEOUT = 2.5

#: Bounds for the final event-loop retirement steps.  These run after the
#: listening socket and every SSE transport have already been closed.
TASK_CANCEL_TIMEOUT = 0.5
ASYNCGEN_SHUTDOWN_TIMEOUT = 0.5
EXECUTOR_SHUTDOWN_TIMEOUT = 1.0

#: Hard cap on :meth:`RemoteServer.stop`.  This is longer than every server-loop
#: deadline combined.  If it is ever reached we retain the live handles and
#: report failure truthfully; dropping them is what made the old orphan
#: impossible to stop or diagnose.
STOP_JOIN_TIMEOUT = 5.0

#: Cadence of the SSE snapshot push. Waiting on the shutdown event for this
#: long is exactly equivalent to sleeping for it, except it returns early when
#: shutdown starts.
SSE_TICK = 0.15

#: Upper bound on a single SSE write. A phone whose screen has turned off (or
#: whose browser backgrounded the tab) stops draining its socket but keeps the
#: TCP connection alive; ``resp.write()`` then blocks on the flow-control
#: drain, and the shutdown event cannot wake a handler stuck *inside* a write.
#: That blocked handler is what ``runner.cleanup()`` then waits out on close —
#: the "closed the window but Halcyon is still in Task Manager, unless I close
#: the remote page on the phone first" report. Bounding the write converts a
#: non-draining client into a dead client: the stream ends, the handler
#: returns, and shutdown never has anything to wait for.
SSE_WRITE_TIMEOUT = 1.0


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
        #: The live SSE request tasks and their underlying socket transports.
        #: They are mutated only on the aiohttp loop thread.  Tracking both is
        #: intentional: cancelling a coroutine is cooperative, while aborting
        #: its transport is an immediate OS-level end to a sleeping phone's
        #: non-draining connection.
        self._sse_tasks: set[asyncio.Task] = set()
        self._sse_transports: set[object] = set()
        self._cleanup_scheduled = False
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
        app.router.add_get("/manifest.webmanifest", self._handle_manifest)
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

    async def _handle_manifest(self, _request: web.Request) -> web.StreamResponse:
        """Serve install metadata with the MIME type PWA clients expect."""
        manifest = STATIC_DIR / "manifest.webmanifest"
        if not manifest.exists():
            return web.Response(status=404, text="manifest unavailable")
        response = web.FileResponse(manifest)
        response.content_type = "application/manifest+json"
        return response

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

        The task *and* transport are registered before ``prepare()``.  This is
        the important real-phone distinction: a backgrounded browser can stop
        draining at any await point, including response preparation and
        aiohttp's automatic final ``write_eof()`` after this handler returns.
        On shutdown :meth:`_abort_sse` closes the socket itself, so no graceful
        final write can hold process exit hostage.
        """
        if self._stopping:
            # Shutdown already started; do not open a new endless stream.
            return web.Response(status=503, text="shutting down")

        task = asyncio.current_task()
        transport = request.transport
        if task is not None:
            self._sse_tasks.add(task)
        if transport is not None:
            self._sse_transports.add(transport)

        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        try:
            await resp.prepare(request)
            closing = self._closing
            last = -1
            while not self._stopping:
                if self._bridge is not None:
                    version = self._bridge.store.version()
                    if version != last:
                        last = version
                        payload = json.dumps(
                            self._bridge.store.snapshot(), ensure_ascii=False
                        )
                        # A per-write bound protects normal operation.  The
                        # transport abort in stop() is the stronger shutdown
                        # guarantee and also covers prepare/write_eof.
                        await asyncio.wait_for(
                            resp.write(f"data: {payload}\n\n".encode("utf-8")),
                            timeout=SSE_WRITE_TIMEOUT,
                        )
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
        except asyncio.CancelledError:
            # Never turn cancellation into a normal response.  Swallowing it
            # makes aiohttp attempt write_eof(), which is precisely the
            # unbounded graceful write a sleeping phone can fail to drain.
            raise
        except (ConnectionResetError, ConnectionError):
            pass
        except Exception:  # pragma: no cover — a dead socket must not log-spam
            log.debug("remote SSE stream ended with an error", exc_info=True)
        finally:
            # An SSE handler has no normal finite completion.  If it is leaving,
            # the client is dead, a write timed out, or shutdown has begun. Abort
            # before unregistering so aiohttp's automatic write_eof cannot take
            # over on the same non-draining socket outside our timeout.
            if transport is not None:
                self._abort_transport(transport)
                self._sse_transports.discard(transport)
            if task is not None:
                self._sse_tasks.discard(task)
        return resp

    @staticmethod
    def _abort_transport(transport) -> None:
        """End one asyncio transport without waiting for buffered output."""
        try:
            abort = getattr(transport, "abort", None)
            if callable(abort):
                abort()
            else:  # pragma: no cover - unusual asyncio transport
                transport.close()
        except Exception:
            log.debug("remote SSE transport abort failed", exc_info=True)

    def _abort_sse(self) -> None:
        """Abort every active event stream.  Runs only on the server loop.

        ``transport.abort()`` is deliberately used instead of ``close()``:
        close is graceful and may wait for buffered bytes, while abort drops
        the socket immediately.  Cancellation then retires the Python handler;
        it is not relied upon to interrupt the OS write by itself.
        """
        for transport in tuple(self._sse_transports):
            self._abort_transport(transport)
        for task in tuple(self._sse_tasks):
            if not task.done():
                task.cancel()

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
        self._sse_tasks.clear()
        self._sse_transports.clear()
        self._cleanup_scheduled = False
        self._thread = threading.Thread(
            target=self._run, name="halcyon-remote", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            log.error("mobile remote server failed to start within 10s")
            # The thread is still trying to bind. Tear it down rather than
            # leaking it: a half-started server is exactly the case that used
            # to leave a live thread nobody held a handle to any more.
            stopped = self.stop(force=True)
            # A failed start is not a shutdown.  Leave the object reusable only
            # when teardown really completed; resurrecting an object that still
            # owns a live thread creates two servers sharing one set of fields.
            if stopped:
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
        """Retire ``loop`` on its owning thread, with a bound on every wait.

        aiohttp's static-file responses use the loop's default
        :class:`~concurrent.futures.ThreadPoolExecutor`. Its workers inherit
        daemon status from this server thread, but ``concurrent.futures`` still
        registers an interpreter-exit hook that joins every worker. Leaving one
        behind can therefore keep Halcyon in Task Manager. Conversely, waiting
        forever for a broken worker merely moves the hang here. Every phase is
        either time-bounded or asks the executor to cancel queued work.
        """
        try:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                _done, still_pending = loop.run_until_complete(
                    asyncio.wait(pending, timeout=TASK_CANCEL_TIMEOUT)
                )
                if still_pending:
                    log.warning(
                        "remote loop closing with %d task(s) still pending",
                        len(still_pending),
                    )
        except Exception:
            log.debug("remote loop task cancellation failed", exc_info=True)

        try:
            asyncgen_task = loop.create_task(loop.shutdown_asyncgens())
            _done, still_pending = loop.run_until_complete(
                asyncio.wait({asyncgen_task}, timeout=ASYNCGEN_SHUTDOWN_TIMEOUT)
            )
            if still_pending:
                asyncgen_task.cancel()
                log.warning(
                    "remote async-generator shutdown exceeded %.1fs",
                    ASYNCGEN_SHUTDOWN_TIMEOUT,
                )
        except Exception:
            log.debug("remote loop asyncgen shutdown failed", exc_info=True)

        try:
            # Python 3.12 added a timeout to this API.  The installer uses 3.12,
            # so take the fully-drained path there.  On older Python, waiting is
            # unbounded; signal the private executor directly instead.  That is
            # the same operation loop.close() performs, but done explicitly so
            # queued work is cancelled too.
            import inspect

            shutdown_executor = loop.shutdown_default_executor
            supports_timeout = "timeout" in inspect.signature(
                shutdown_executor
            ).parameters
            if supports_timeout:
                loop.run_until_complete(
                    shutdown_executor(timeout=EXECUTOR_SHUTDOWN_TIMEOUT)
                )
            else:
                executor = getattr(loop, "_default_executor", None)
                if executor is not None:
                    import time

                    workers = tuple(getattr(executor, "_threads", ()))
                    executor.shutdown(wait=False, cancel_futures=True)
                    deadline = time.monotonic() + EXECUTOR_SHUTDOWN_TIMEOUT
                    for worker in workers:
                        worker.join(timeout=max(0.0, deadline - time.monotonic()))
                    survivors = [worker for worker in workers if worker.is_alive()]
                    if survivors:
                        log.warning(
                            "remote executor still has %d worker(s) after %.1fs",
                            len(survivors),
                            EXECUTOR_SHUTDOWN_TIMEOUT,
                        )
                    loop._default_executor = None  # type: ignore[attr-defined]
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

    def stop(self, force: bool = False) -> bool:
        """Stop serving, returning whether the server thread really ended.

        The listening socket is gated first, then every active SSE transport is
        aborted on the loop thread before aiohttp gets a chance to perform a
        graceful final write.  The graceful cleanup has its own timeout and an
        independent loop stopper.  Finally the caller joins the thread.

        A failed join is reported as ``False`` and, critically, the live thread
        and loop handles are retained.  They can therefore be inspected or a
        later forced stop can reach them; reporting "stopped" and throwing the
        handles away was the old Task Manager leak.
        """
        with self._lock:
            already_stopping = self._stopping
            self._stopping = True
            thread = self._thread
            loop = self._loop

        self._started = False

        if loop is not None and thread is not None and thread.is_alive():

            def _schedule_cleanup() -> None:
                closing = self._closing
                if closing is not None:
                    closing.set()

                # Socket abort is synchronous and happens before any graceful
                # aiohttp await.  Repeat it after site.stop() below to cover the
                # tiny accept race between the caller setting _stopping and this
                # callback running.
                self._abort_sse()

                if self._cleanup_scheduled:
                    if force:
                        loop.stop()
                    return
                self._cleanup_scheduled = True

                # This callback remains able to stop run_forever even if the
                # cleanup coroutine gets stuck while processing cancellation.
                hard_stop = loop.call_later(LOOP_HARD_STOP_TIMEOUT, loop.stop)

                async def _graceful_cleanup() -> None:
                    if self._site is not None:
                        await self._site.stop()
                    self._abort_sse()
                    if self._runner is not None:
                        await self._runner.cleanup()

                async def _cleanup() -> None:
                    cancelled = False
                    try:
                        await asyncio.wait_for(
                            _graceful_cleanup(), timeout=CLEANUP_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        log.warning(
                            "mobile remote cleanup exceeded %.1fs; forcing loop stop",
                            CLEANUP_TIMEOUT,
                        )
                    except asyncio.CancelledError:
                        cancelled = True
                        raise
                    except Exception:
                        log.debug("remote server cleanup failed", exc_info=True)
                    finally:
                        hard_stop.cancel()
                        # If _close_loop is cancelling this task after the hard
                        # stopper fired, another loop.stop() would interrupt its
                        # bounded run_until_complete task drain.
                        if not cancelled:
                            loop.stop()

                loop.create_task(_cleanup(), name="halcyon-remote-cleanup")

            # Do not queue duplicate graceful cleanups on an idempotent stop.
            # A forced retry is allowed through so it can stop a loop whose
            # first cleanup callback never completed.
            if not already_stopping or force:
                try:
                    loop.call_soon_threadsafe(_schedule_cleanup)
                except RuntimeError:  # loop already closed — join it below
                    pass

        if thread is not None and thread.is_alive():
            thread.join(timeout=STOP_JOIN_TIMEOUT)

        if thread is not None and thread.is_alive():
            log.error(
                "mobile remote thread still alive after %.1fs; retaining its "
                "handles and reporting shutdown failure",
                STOP_JOIN_TIMEOUT,
            )
            return False

        self._clear_stopped_handles()
        log.info("mobile remote stopped (thread terminated)")
        return True

    def _clear_stopped_handles(self) -> bool:
        """Clear lifecycle fields only when no live server thread remains."""
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                return False
            self._thread = None
            self._loop = None
            self._runner = None
            self._site = None
            self._closing = None
            self._cleanup_scheduled = False
            self._sse_tasks.clear()
            self._sse_transports.clear()
        return True

    def _join_thread(self) -> bool:
        """Reap a thread whose loop already unwound (for example, failed bind)."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=STOP_JOIN_TIMEOUT)
        return self._clear_stopped_handles()
