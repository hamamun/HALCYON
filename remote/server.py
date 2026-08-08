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


def available() -> bool:
    """True when aiohttp is installed and the server can actually run."""
    return _AIOHTTP


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

    # ------------------------------------------------------------- state ---
    @property
    def port(self) -> int:
        return self._port

    @property
    def started(self) -> bool:
        return self._started

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
        """SSE stream — pushes each new snapshot to the phone."""
        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await resp.prepare(request)
        last = -1
        try:
            while True:
                if self._bridge is not None:
                    version = self._bridge.store.version()
                    if version != last:
                        last = version
                        payload = json.dumps(
                            self._bridge.store.snapshot(), ensure_ascii=False
                        )
                        await resp.write(f"data: {payload}\n\n".encode("utf-8"))
                await asyncio.sleep(0.4)
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
            pass
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
            return False
        return self._started

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._runner = web.AppRunner(self._build_app())
            self._loop.run_until_complete(self._runner.setup())
            self._site = web.TCPSite(self._runner, BIND_HOST, self._port)
            self._loop.run_until_complete(self._site.start())
            self._port = self._actual_port()
            self._started = True
            if self._bridge is not None:
                setter = getattr(self._bridge, "set_server_url", None)
                if setter is not None:
                    setter(self.base_url)
            log.info("mobile remote listening on %s", self.base_url)
        except Exception:
            log.exception("mobile remote server failed to start")
            self._ready.set()  # never leave start() blocked
            return
        finally:
            self._ready.set()

        try:
            self._loop.run_forever()
        except Exception:  # pragma: no cover — loop failure is fatal anyway
            log.exception("mobile remote server loop ended unexpectedly")
            self._started = False

    def _actual_port(self) -> int:
        try:
            return self._site._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]
        except Exception:
            return self._port

    def stop(self) -> None:
        """Stop serving. Idempotent and safe to call from any thread."""
        if not self._started:
            return
        self._started = False
        loop = self._loop
        if loop is not None:

            def _schedule_cleanup() -> None:
                async def _cleanup() -> None:
                    if self._runner is not None:
                        await self._runner.cleanup()
                    loop.stop()

                loop.create_task(_cleanup())

            try:
                loop.call_soon_threadsafe(_schedule_cleanup)
            except RuntimeError:  # pragma: no cover — loop already closed
                pass

        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._runner = None
        self._site = None
        log.info("mobile remote stopped")
