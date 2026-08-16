#!/usr/bin/env python3
"""Halcyon — every format, one pane of glass.

Bootstrap: build the engine, the shared services and the mode contexts, hand
them to QML, and get out of the way.

Order matters in four places:

* ``QQuickWindow.setGraphicsApi`` must be called **before** ``QGuiApplication``
  exists. Phase 3 needs OpenGL for QtWebEngine to agree with Qt Quick (§P3.2);
  setting it now costs nothing and avoids a "why is the web view blank" day.
* The QML engine is created **first** and parented to the application, so Qt
  destroys it *before* the context objects it points at. Sibling QObjects are
  destroyed in creation order, so creating it first is what stops the
  "Cannot call method 'get' of null" storm on exit.
* Every service is parented to the application. A context property whose only
  reference is a Python local dies when ``main()`` returns, which QML then
  reports as ``null`` from whatever binding re-evaluates last.
* Engine shutdown must run on ``aboutToQuit``, never from a Qt slot that might
  itself be servicing a VLC callback (§9).

**Naming, and why it is load-bearing.** The libVLC facade is bound to ``player``
here, never ``engine``. ``engine`` is the name of a *package* in this repo, and
``import engine.surface`` binds that package to the name ``engine`` in whatever
scope runs it — silently replacing a local of the same name. That is not a
hypothetical: it swapped the VlcEngine instance for a module object, so QML's
``Player`` became ``<module 'engine'>`` and every playback binding failed.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Anything QML holds a context-property reference to lives here for the life of
#: the process. Qt parenting already covers this, but a stray Python-side
#: collection is exactly the failure that produces null context properties, and
#: belt-and-braces costs one list.
_KEEP_ALIVE: list = []

#: Bound on every network request made from QML itself (the ArtworkURL cover
#: images in NowPlayingCard/InfoTab, the mobile-remote QR image in
#: SettingsDialog). Without one, a dead server parks Qt's background
#: pixmap-reader thread forever, and process teardown then deadlocks inside
#: QQuickPixmap's destructor waiting for that thread — the exact hang
#: captured in shutdown-trace.dmp (main thread: QThread::wait under
#: ~QQuickPixmap, observed 2026-08-15).
QML_NET_TIMEOUT_MS = 8_000

#: How long post-``exec()`` teardown may take before the process is force-
#: ended. Everything worth persisting is flushed in ``on_quit`` before this
#: watchdog is even armed, so a forced exit loses nothing — and "window
#: closed but python.exe lingers in Task Manager" becomes impossible by
#: construction, whatever native teardown decides to do next time.
EXIT_WATCHDOG_SECONDS = 10.0


def _arm_exit_watchdog(exit_code: int, seconds: float = EXIT_WATCHDOG_SECONDS) -> None:
    """Last-resort guarantee that closing the window also ends the process.

    All legitimately-slow cleanup lives in ``on_quit`` and runs *before*
    ``exec()`` returns; what happens afterwards — explicit QML engine
    destruction, PySide's exit-time cleanup of the application object, and
    interpreter finalization — has a real history of wedging in a native
    wait while holding the GIL, where no Python-side observer can exist
    (see core/shutdown_trace.py). The watchdog is a daemon timer thread: on
    a healthy exit the process is gone long before the deadline and the
    timer dies with it; on a wedged exit, ``os._exit`` ends the process with
    the intended exit code. Binding ``os._exit`` now means the timer needs
    nothing that interpreter finalization might already have torn down.
    """
    _exit = os._exit

    def _force(code: int) -> None:
        try:
            _exit(code)
        except Exception:
            pass

    try:
        timer = threading.Timer(seconds, _force, args=[exit_code])
        timer.daemon = True
        timer.name = "halcyon-exit-watchdog"
        timer.start()
    except Exception:
        # A watchdog that can break shutdown is worse than none at all.
        pass


def debug_enabled(argv: list[str]) -> bool:
    """``--debug`` on the command line, or ``HALCYON_DEBUG=1`` in the env.

    Two switches because the two callers differ: a launch configuration passes
    an argument, while ``py main.py`` from a terminal is easier to flip with an
    environment variable.
    """
    if any(a in ("--debug", "-d") for a in argv[1:]):
        return True
    return os.environ.get("HALCYON_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def shutdown_trace_enabled(argv: list[str]) -> bool:
    """``--trace-shutdown`` on the command line, or the env equivalent.

    Arms a watchdog that dumps every thread's stack if the process is still
    alive a few seconds after ``aboutToQuit``. Used to pin down the exact
    location of a shutdown hang; inert on every normal run.
    """
    if "--trace-shutdown" in argv[1:]:
        return True
    return os.environ.get("HALCYON_TRACE_SHUTDOWN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def pythonnet_disabled(argv: list[str]) -> bool:
    """``--no-pythonnet`` on the command line, or ``HALCYON_DISABLE_PYTHONNET=1``.

    Diagnostic switch for the shutdown-hang hunt: skips the pythonnet/CLR
    bootstrap entirely, so ``clr.dll``/``mscorlib`` never load into the
    process. If the app then exits cleanly, the .NET-runtime-shutdown race is
    the culprit (suspect #1); if it still hangs, the CLR is exonerated without
    touching the code. Inert on every normal run — Web mode simply reports its
    runtime as unavailable, exactly as if the bootstrap had failed.
    """
    if "--no-pythonnet" in argv[1:]:
        return True
    return os.environ.get("HALCYON_DISABLE_PYTHONNET", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def configure_logging(debug: bool = False) -> None:
    """Set up logging, and in debug mode route *Qt's* messages here too.

    Qt and QML do not use Python's logging. QML warnings — a mistyped property,
    a broken signal handler, a binding loop — go straight to Qt's own message
    handler, which by default writes to stderr in a format nothing else here
    uses, and which is swallowed entirely in some launchers. That is why a
    broken QML connection can look like "nothing happened" with a clean console.

    In debug mode we install a handler that forwards every Qt/QML message into
    the same logger as the Python side, so one stream carries both.
    """
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not debug:
        return

    # Third-party noise stays at INFO — debug is for Halcyon's own modules.
    for noisy in ("urllib3", "requests", "charset_normalizer", "PIL"):
        logging.getLogger(noisy).setLevel(logging.INFO)

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    qt_log = logging.getLogger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message) -> None:
        # file/line are only populated for QML and for debug builds of Qt, but
        # when they are present they are the whole value of the message.
        where = ""
        if getattr(context, "file", None):
            where = f" [{context.file}:{context.line}]"
        qt_log.log(levels.get(mode, logging.INFO), "%s%s", message, where)

    qInstallMessageHandler(handler)

    # Qt keeps most QML diagnostics behind logging categories that are off by
    # default. Binding loops and unqualified lookups are exactly the class of
    # bug that shows up as a silently dead UI, so turn them on.
    os.environ.setdefault(
        "QT_LOGGING_RULES",
        "qt.qml.binding.removal.info=true;qt.qml.diskcache.debug=false",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    debug = debug_enabled(argv)
    configure_logging(debug)
    log = logging.getLogger("halcyon")
    if debug:
        log.debug("debug mode on — Qt/QML messages are routed through logging")

    # Opt-in shutdown hang tracer. Starts an idle daemon thread that only does
    # something if the process is still alive a few seconds after aboutToQuit.
    # No effect at all unless --trace-shutdown (or HALCYON_TRACE_SHUTDOWN=1) is
    # passed. Never touches playback, VLC, or QML.
    shutdown_tracer = None
    if shutdown_trace_enabled(argv):
        from core.shutdown_trace import ShutdownTracer

        shutdown_tracer = ShutdownTracer(ROOT / "shutdown-trace.log")
        shutdown_tracer.start()

    # WebView2 uses COM on the GUI thread.  Initialise pythonnet's bridge before
    # Qt creates any view; failure is deliberately non-fatal because Local/M3U
    # remain usable and WebStage presents the precise unavailable state later.
    # `--no-pythonnet`/HALCYON_DISABLE_PYTHONNET (pythonnet_disabled) is the
    # shutdown-hang isolation switch: with it, the CLR never loads and we learn
    # whether the exit hang is a .NET-vs-Python teardown race.
    if sys.platform == "win32" and not pythonnet_disabled(argv):
        try:
            from modes.web.webview2_runtime import init_pythonnet_com

            if not init_pythonnet_com():
                log.debug("WebView2 bridge was not ready at startup; Web mode will explain why")
        except Exception:
            log.debug("WebView2 bootstrap failed; continuing without Web mode runtime", exc_info=True)

    # --- graphics API, before anything Qt exists ---------------------------
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    if sys.platform == "win32":
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Direct3D11)
    else:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    # --- surface format, before any window exists --------------------------
    # Both the rounded shell and TurboChromeWindow are transparent
    # QQuickWindows.  QSurfaceFormat's global default alone is not sufficient
    # for dynamically-created QML Window instances on the D3D11/RHI path:
    # QQuickWindow can still create a premultiplied-alpha swapchain while its
    # own requested format reports no alpha buffer.  That is the exact mismatch
    # behind "Swapchain says surface has alpha but the window has no
    # alphaBufferSize set" when Turbo creates its chrome overlay.
    #
    # Set QQuickWindow's alpha policy explicitly *before QGuiApplication* so it
    # is copied into the main shell and every later QML Window, including the
    # Turbo overlay.  Keep the QSurfaceFormat default as the platform-level
    # declaration.  The native VLC child is a plain QWindow and overrides its
    # own format to opaque alpha size 0 in turbo_surface.py.
    QQuickWindow.setDefaultAlphaBuffer(True)

    from PySide6.QtGui import QSurfaceFormat

    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface_format)

    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    QCoreApplication.setOrganizationName("Halcyon")
    QCoreApplication.setApplicationName("Halcyon")

    app = QGuiApplication(argv)
    icon_path = ROOT / "assets" / "halcyon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # --- QML engine, created first on purpose ------------------------------
    # Parented to the application and constructed before any service, so Qt's
    # child-destruction order tears the scene down while App/Settings/Modes are
    # still alive.
    qml_engine = QQmlApplicationEngine(app)
    # One import path: the repository root. Qt maps `import Halcyon.Ui` to
    # <import path>/Halcyon/Ui/qmldir, so the module directories under Halcyon/
    # are what make the imports resolve. Adding ui/ or ui/shell/ here does
    # nothing — a directory only provides a module if its *path* spells the URI.
    qml_engine.addImportPath(str(ROOT))
    _KEEP_ALIVE.append(qml_engine)

    # --- network timeouts for QML (root cause of the exit hang) -------------
    # QML Image items (the ArtworkURL covers in NowPlayingCard/InfoTab, the
    # mobile-remote QR image in SettingsDialog) load over the network on Qt's
    # background pixmap-reader thread. A request to a dead or silently-
    # unresponsive server never completes, that thread never exits — and
    # QQuickPixmap's destructor then waits on it forever during PySide's
    # exit-time cleanup: precisely the stack in shutdown-trace.dmp, and the
    # reason the hang was intermittent (it needs an image load airborne at
    # close). A transfer timeout on the engine's QNetworkAccessManager makes
    # every QML-side network load bounded: a stuck request errors out, the
    # reader thread always unwinds, and teardown can always complete. The
    # engine does NOT own the factory, hence _KEEP_ALIVE below.
    from PySide6.QtNetwork import QNetworkAccessManager
    from PySide6.QtQml import QQmlNetworkAccessManagerFactory

    class _TimeoutNetworkAccessManager(QNetworkAccessManager):
        def createRequest(self, op, request, outgoing_data=None):
            try:
                request.setTransferTimeout(QML_NET_TIMEOUT_MS)  # Qt >= 6.5
            except AttributeError:  # pragma: no cover — older Qt: default stays
                pass
            return super().createRequest(op, request, outgoing_data)

    class _TimeoutNamFactory(QQmlNetworkAccessManagerFactory):
        def create(self, parent):
            return _TimeoutNetworkAccessManager(parent)

    _nam_factory = _TimeoutNamFactory()
    qml_engine.setNetworkAccessManagerFactory(_nam_factory)
    _KEEP_ALIVE.append(_nam_factory)

    # --- shared services ---------------------------------------------------
    # NOTE the import style: `from engine.xxx import Yyy`, never a bare
    # `import engine.zzz`, so the name `engine` is never bound in this scope.
    from core import modes as mode_registry
    from core import paths
    from core.app import AppController, ModeList
    from core.library import Library
    from core.lyrics import Lyrics
    from core.metadata import Metadata
    from core.power import PowerGuard
    from core.settings import Settings
    from core.subtitles import SubtitleBackend
    from core.update_checker import UpdateChecker
    from engine.equalizer import Equalizer
    from engine.video_adjust import VideoAdjust
    from engine.vlc_engine import VlcEngine

    paths.seed_defaults()
    settings = Settings(parent=app)

    backend = _resolve_backend(str(settings.get("video.backend", "auto")), paths, log)
    try:
        player = VlcEngine(backend=backend, parent=app)
    except Exception as exc:  # libVLC missing is the common first-run failure
        log.error("could not start libVLC: %s", exc)
        _fatal(
            "libVLC could not be loaded.\n\n"
            "Populate vendor/vlc/ with libvlc.dll, libvlccore.dll and plugins/ "
            "(see README), or install VLC 3.0.21 x64."
        )
        return 1

    player.set_volume(int(settings.get("audio.volume", 80)))
    player.set_muted(bool(settings.get("audio.muted", False)))

    library = Library(parent=app)
    library.bind(player)
    metadata = Metadata(player, parent=app)
    lyrics = Lyrics(parent=app)
    equalizer = Equalizer(player, parent=app)
    video_adjust = VideoAdjust(player, settings, parent=app)
    # Stops Windows blanking the monitor mid-film. Parented to the app and kept
    # in _KEEP_ALIVE like every other service: if it is collected its release()
    # never runs and the wake request outlives the playback that justified it.
    power_guard = PowerGuard(player, parent=app)

    controller = AppController(
        player, settings, library, metadata, lyrics, equalizer, video_adjust, parent=app
    )
    mode_list = ModeList(app)
    subs_backend = SubtitleBackend(settings, controller, parent=app)
    update_checker = UpdateChecker(parent=app)
    _KEEP_ALIVE.extend(
        [
            settings,
            player,
            library,
            metadata,
            lyrics,
            equalizer,
            video_adjust,
            power_guard,
            controller,
            mode_list,
            subs_backend,
            update_checker,
        ]
    )

    # --- QML types ---------------------------------------------------------
    # Registers VideoSurface/PlaneSurface into the Halcyon.Engine module via
    # @QmlElement. Imported for the side effect only — bound to an underscore
    # name so the `engine` package never lands in this namespace.
    from engine import surface as _surface  # noqa: F401

    ctx = qml_engine.rootContext()
    ctx.setContextProperty("App", controller)
    ctx.setContextProperty("Modes", mode_list)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Subs", subs_backend)
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Library", library)
    ctx.setContextProperty("Metadata", metadata)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("Equalizer", equalizer)
    ctx.setContextProperty("VideoAdjust", video_adjust)
    ctx.setContextProperty("UpdateChecker", update_checker)

    # In-app icon mark (the "glass pane" glyph, transparent background). Used by
    # the title bar, the borderless drag strip and Mini Mode. Exposed as a URL
    # so those components stay loadable standalone in qmlscene/tests — each one
    # guards on `typeof AppIcon !== "undefined"`.
    ctx.setContextProperty(
        "AppIcon", QUrl.fromLocalFile(str(ROOT / "assets" / "halcyon-glyph.png"))
    )

    # --- per-mode contexts -------------------------------------------------
    # Each mode gets to publish one object. The shell never names a mode; it
    # iterates the registry (§A.2), so Phases 2 and 3 need no change here.
    for spec in mode_registry.all_modes():
        context_object = _build_mode_context(spec, player, controller, settings)
        if context_object is not None:
            context_object.setParent(app)
            _KEEP_ALIVE.append(context_object)
            controller.register_context(spec.id, context_object)
            ctx.setContextProperty(_context_name(spec.id), context_object)
            if spec.context_property != _context_name(spec.id):
                ctx.setContextProperty(spec.context_property, context_object)

    # --- load the UI -------------------------------------------------------
    # Warnings are logged always, not only in debug. A QML warning means a
    # binding or a signal handler is dead, which the user experiences as a
    # control that does nothing — the single hardest failure to diagnose from a
    # bug report, and free to surface here.
    qml_engine.warnings.connect(
        lambda warnings: [
            logging.getLogger("qml").warning("%s", w.toString()) for w in warnings
        ]
    )
    qml_engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    if not qml_engine.rootObjects():
        log.error("QML failed to load — see the messages above")
        return 2

    # --- mobile remote (Phase R, §R.4) --------------------------------------
    # On by default; the LAST step of startup loading (owner decision
    # 2026-08-08). Never fatal: without aiohttp the app starts exactly as
    # before, with a warning. Stopped FIRST in on_quit() so no command can
    # arrive while the engine is tearing down (§R.4).
    #
    # The bridge is the safety keystone: the server thread only emits queued
    # signals and reads plain dicts; every command runs on the Qt thread here,
    # exactly like a button click (§R.4).
    from remote.bridge import RemoteBridge
    from remote.server import RemoteServer

    remote_bridge = RemoteBridge(
        controller=controller,
        engine=player,
        settings=settings,
        equalizer=equalizer,
        subs=subs_backend,
        parent=app,
    )
    _KEEP_ALIVE.append(remote_bridge)
    # Hand the bridge the mode contexts (Local playlist, M3U, Web browser) so
    # it can drive and mirror each mode — the remote mirrors every mode's
    # control set (§R.2), which is why it is allowed to reach modes.
    for spec in mode_registry.all_modes():
        remote_bridge.register_context(spec.id, controller.context(spec.id))
    ctx.setContextProperty("RemoteBridge", remote_bridge)

    remote = RemoteServer(bridge=remote_bridge, settings=settings)
    _KEEP_ALIVE.append(remote)
    if remote.start():
        log.info("mobile remote serving on %s", remote.base_url)
    else:
        log.info("mobile remote not started")

    # --- taskbar live preview when minimized (Windows DWM) ------------------
    # Soft and Turbo both show live thumb when window is open (DWM default).
    # When minimized Qt pauses render loop, so thumb becomes still. This small
    # Windows-only helper enables DWM iconic bitmaps and supplies a fresh frame
    # from the main player on demand — no second player, no Turbo HWND risk.
    taskbar_preview = None
    try:
        if sys.platform == "win32":
            from core.taskbar_preview import TaskbarLivePreview, is_supported

            if is_supported():
                main_window = qml_engine.rootObjects()[0] if qml_engine.rootObjects() else None
                if main_window is not None:
                    taskbar_preview = TaskbarLivePreview(
                        engine=player, window=main_window, parent=app
                    )
                    _KEEP_ALIVE.append(taskbar_preview)
                    ctx.setContextProperty("TaskbarPreview", taskbar_preview)
                    log.info("taskbar live preview initialized")
    except Exception:
        log.debug("taskbar preview init failed", exc_info=True)

    # --- shutdown, in the right order (§9) ---------------------------------
    def on_quit() -> None:
        # Start the watchdog's grace countdown *before* any cleanup, so a hang
        # inside cleanup itself is captured too.
        if shutdown_tracer is not None:
            shutdown_tracer.arm()

        # Settings first, before anything that could hang.
        #
        # They are flushed again later, inside ``controller.shutdown()`` — but
        # that runs *after* the taskbar preview, the remote server, the remote
        # bridge, the QML context teardown, the power guard and the subtitle
        # backend have all had their turn. Any one of those wedging or raising
        # takes the pending write with it, and writes are debounced by 400 ms,
        # so a setting changed seconds before closing (volume, geometry, the
        # last-used playlist) was exactly the one at risk. Flushing here costs
        # one atomic write of a small JSON file and makes the outcome
        # independent of everything that follows. ``flush()`` is a no-op when
        # nothing is dirty, so the later call stays harmless.
        try:
            settings.flush()
        except Exception:
            log.exception("settings flush failed")

        # Taskbar preview next: it touches the window handle, so it must go
        # before Qt tears the window down.
        try:
            if taskbar_preview is not None:
                taskbar_preview.shutdown()
        except Exception:
            log.debug("taskbar preview shutdown failed", exc_info=True)

        # The remote goes down first: it is the only component that accepts
        # input from outside the process, so once shutdown starts no new
        # command may be accepted (§R.4). Stop the bridge's status poller too
        # so it never reads engine state mid-teardown.
        try:
            remote.stop()
        except Exception:
            log.exception("remote server stop failed")
        try:
            remote_bridge.stop()
        except Exception:
            log.exception("remote bridge stop failed")

        # Break QML's signal bindings while their target QObjects are still
        # alive. Otherwise QQmlApplicationEngine may tear down a Connections
        # object after Player has already been destroyed and Qt prints
        # ``QObject::disconnect: Unexpected nullptr parameter``.
        try:
            qml_engine.rootContext().setContextProperty("Player", None)
        except Exception:
            log.debug("could not clear Player QML context property", exc_info=True)

        # First: let the display sleep again. This is the step that must not be
        # skipped by an exception in either of the two below, because a wake
        # request outliving the process is invisible until the user notices
        # their machine has stopped sleeping.
        try:
            power_guard.release()
        except Exception:
            log.exception("power guard release failed")

        # Subtitle jobs first: they call back into the controller when they
        # land, so they must stop before it (and the engine) goes away.
        try:
            subs_backend.shutdown()
        except Exception:
            log.exception("subtitle backend shutdown failed")

        # Neither half may be skipped because the other threw: a failed
        # controller flush must not leave libVLC's threads running.
        try:
            controller.shutdown()
        except Exception:
            log.exception("controller shutdown failed")
        try:
            player.shutdown()
        except Exception:
            log.exception("engine shutdown failed")

    app.aboutToQuit.connect(on_quit)

    # Files passed on the command line go through the same append path as
    # everything else (§4.1).
    media_args = [a for a in argv[1:] if not a.startswith("-")]
    if media_args:
        controller.addPaths(media_args)

    exit_code = app.exec()

    # --- teardown: explicit, observable, and hard-bounded -------------------
    # If we got here, the Qt event loop returned and every bounded cleanup in
    # on_quit has already run. Two things remain: destroying the QML engine,
    # and PySide's exit-time cleanup of the application object. That latter
    # stage is exactly where shutdown-trace.dmp wedged — main thread parked
    # in QThread::wait under ~QQuickPixmap, blind (no logging) and unbounded.
    #
    # So: arm the exit watchdog FIRST, meaning any wedge anywhere below can
    # only ever delay the process by EXIT_WATCHDOG_SECONDS; then destroy the
    # QML engine explicitly — now, while Python is fully alive and logging
    # still works — instead of leaving the same destruction to interpreter-
    # exit cleanup, where the hang used to be invisible and unkillable.
    _arm_exit_watchdog(exit_code)

    try:
        from shiboken6 import Shiboken

        Shiboken.delete(qml_engine)
        log.info("QML engine destroyed")
    except Exception:
        # The engine then dies as it used to, during interpreter exit — the
        # watchdog above caps the damage either way.
        log.debug("explicit QML engine destruction failed", exc_info=True)

    if shutdown_tracer is not None:
        shutdown_tracer.cancel()
    return exit_code


def _resolve_backend(requested: str, paths, log) -> str:
    """Pick the video backend, downgrading to RV32 only if I420 can't work.

    The I420 path needs ``ui/shaders/yuv420p.frag.qsb``. Rather than demand a
    manual ``tools/build_shaders.py`` run on every fresh clone — the silent
    fallback that used to baffle first runs — :func:`_ensure_shader` compiles it
    on the spot from the bundled ``.frag`` whenever ``pyside6-qsb`` is on the
    PATH. Only when the shader genuinely cannot be produced do we fall back.

    RV32 is now colour-correct (``engine.surface`` reads VLC's host-order RGB
    buffer as ``Format_RGBX8888``, not ``Format_RGB32``), so the fallback is a
    real, working picture rather than a black stage. It just costs more bus
    bandwidth (4 bytes/px vs 1.5) and a CPU YUV→RGB step, so it stays the
    fallback rather than the default.
    """
    requested = _backend_from_env(requested)
    if requested == "rv32":
        return "rv32"

    if _ensure_shader(paths, log):
        return requested  # "auto" or "i420"

    log.warning(
        "compiled shader %s is missing and could not be built — falling back to "
        "the RV32 video path. Install/repair PySide6 (for pyside6-qsb) to enable "
        "the faster I420 path.",
        (paths.SHADERS / "yuv420p.frag.qsb").name,
    )
    return "rv32"


def _ensure_shader(paths, log) -> bool:
    """Make sure the compiled YUV shader is present, building it if possible.

    Returns ``True`` when ``yuv420p.frag.qsb`` is usable. On a source checkout
    we (re)compile it from the bundled ``.frag`` whenever it is missing or stale
    and ``pyside6-qsb`` is available, so first run just works. A frozen build
    ships the shader from qrc: and has no ``.frag`` on disk to compare against,
    so this is a no-op there.
    """
    src = paths.SHADERS / "yuv420p.frag"
    qsb = paths.SHADERS / "yuv420p.frag.qsb"
    if qsb.exists() and (not src.exists() or qsb.stat().st_mtime >= src.stat().st_mtime):
        return True
    if not src.exists():
        return qsb.exists()
    try:
        # Local import: needs the repo root on sys.path (main() inserts it).
        from tools.build_shaders import build_all

        built, failed = build_all()
    except Exception:  # never let a build hiccup block startup
        log.debug("shader build not available", exc_info=True)
        return qsb.exists()
    if failed:
        log.warning(
            "shader build reported %d failure(s); using the RV32 path", failed
        )
    elif built:
        log.info("compiled %d shader(s) for the I420 video path", built)
    return qsb.exists()


def _backend_from_env(requested: str) -> str:
    """``HALCYON_VIDEO_BACKEND`` overrides the settings value (see README).

    Handy for forcing a path to diagnose a rendering problem without editing
    the settings file. Accepts ``auto`` / ``i420`` / ``rv32``; anything else is
    ignored so a typo cannot silently switch paths.
    """
    env = os.environ.get("HALCYON_VIDEO_BACKEND", "").strip().lower()
    if env in ("auto", "i420", "rv32"):
        return env
    return requested


def _context_name(mode_id: str) -> str:
    """``local`` -> ``LocalPlaylist``. Matches what the mode's QML expects."""
    return f"{mode_id.capitalize()}Playlist"


def _build_mode_context(spec, player, controller, settings):
    """Create a mode's context object.

    Local is wired here because Phase 1 owns it. Later modes declare a ``setup``
    callable on their ``ModeSpec`` instead, so this function does not grow
    (§A.3).
    """
    if spec.setup is not None:
        return spec.setup(engine=player, controller=controller, settings=settings)

    if spec.id == "local":
        from modes.local.playlist import LOCAL_PLAYLIST_FILENAME, PlaylistModel

        playlist = PlaylistModel(
            storage_path=settings.path.parent / LOCAL_PLAYLIST_FILENAME
        )
        playlist.playRequested.connect(lambda path, _row: controller.openPath(path))

        # Restore what the user left set, and — the half that was missing —
        # write it back when it changes. Reading a setting nothing ever saves
        # is just a slower way of hard-coding the default.
        playlist.set_repeat_mode(int(settings.get_mode("local", "repeat", 0) or 0))
        if bool(settings.get_mode("local", "shuffle", False)):
            playlist.toggle_shuffle()
        playlist.repeatModeChanged.connect(
            lambda: settings.set_mode("local", "repeat", playlist.repeatMode)
        )
        playlist.shuffleChanged.connect(
            lambda: settings.set_mode("local", "shuffle", playlist.shuffle)
        )
        return playlist

    return None


def _fatal(message: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "Halcyon", message)
    except Exception:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
