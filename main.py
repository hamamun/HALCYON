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


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    configure_logging()
    log = logging.getLogger("halcyon")

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
    from core.settings import Settings
    from engine.equalizer import Equalizer
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

    controller = AppController(
        player, settings, library, metadata, lyrics, equalizer, parent=app
    )
    mode_list = ModeList(app)
    _KEEP_ALIVE.extend(
        [settings, player, library, metadata, lyrics, equalizer, controller, mode_list]
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
    ctx.setContextProperty("Player", player)
    ctx.setContextProperty("Library", library)
    ctx.setContextProperty("Metadata", metadata)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("Equalizer", equalizer)

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

    # --- load the UI -------------------------------------------------------
    qml_engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    if not qml_engine.rootObjects():
        log.error("QML failed to load — see the messages above")
        return 2

    # --- shutdown, in the right order (§9) ---------------------------------
    def on_quit() -> None:
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
    """Pick the video backend, downgrading to RV32 if the shader is missing.

    The I420 path needs ``ui/shaders/yuv420p.frag.qsb``, a build product that is
    gitignored and produced by ``tools/build_shaders.py``. Without it Qt logs a
    wall of ShaderEffect errors and plays perfectly good audio over a black
    rectangle — a genuinely baffling first run.

    RV32 costs more bandwidth (4 bytes/px against 1.5) and no shader, so it is
    the right automatic answer: the user sees a picture and one actionable line
    in the log instead of a black stage and a stack of Qt diagnostics.
    """
    if requested == "rv32":
        return "rv32"

    shader_src = paths.SHADERS / "yuv420p.frag"
    shader_qsb = paths.SHADERS / "yuv420p.frag.qsb"
    # Only second-guess a source checkout. A frozen build serves the shader from
    # qrc:, where there is no .frag on disk to compare against.
    if shader_src.exists() and not shader_qsb.exists():
        log.warning(
            "compiled shader %s is missing — falling back to the RV32 video path. "
            "Run `python tools/build_shaders.py` for the faster I420 path.",
            shader_qsb.name,
        )
        return "rv32"
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
