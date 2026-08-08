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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Anything QML holds a context-property reference to lives here for the life of
#: the process. Qt parenting already covers this, but a stray Python-side
#: collection is exactly the failure that produces null context properties, and
#: belt-and-braces costs one list.
_KEEP_ALIVE: list = []


def debug_enabled(argv: list[str]) -> bool:
    """``--debug`` on the command line, or ``HALCYON_DEBUG=1`` in the env.

    Two switches because the two callers differ: a launch configuration passes
    an argument, while ``py main.py`` from a terminal is easier to flip with an
    environment variable.
    """
    if any(a in ("--debug", "-d") for a in argv[1:]):
        return True
    return os.environ.get("HALCYON_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


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

    # WebView2 uses COM on the GUI thread.  Initialise pythonnet's bridge before
    # Qt creates any view; failure is deliberately non-fatal because Local/M3U
    # remain usable and WebStage presents the precise unavailable state later.
    if sys.platform == "win32":
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

    # --- shutdown, in the right order (§9) ---------------------------------
    def on_quit() -> None:
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

    return app.exec()


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
        from modes.local.playlist import PlaylistModel

        playlist = PlaylistModel()
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
