#!/usr/bin/env python3
"""Halcyon — every format, one pane of glass.

Bootstrap: build the engine, the shared services and the mode contexts, hand
them to QML, and get out of the way.

Order matters in two places:

* ``QQuickWindow.setGraphicsApi`` must be called **before** ``QGuiApplication``
  exists. Phase 3 needs OpenGL for QtWebEngine to agree with Qt Quick (§P3.2);
  setting it now costs nothing and avoids a "why is the web view blank" day.
* Engine shutdown must run on ``aboutToQuit``, never from a Qt slot that might
  itself be servicing a VLC callback (§9).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    # --- shared services ---------------------------------------------------
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
    settings = Settings()

    backend = settings.get("video.backend", "auto")
    try:
        engine = VlcEngine(backend=backend)
    except Exception as exc:  # libVLC missing is the common first-run failure
        log.error("could not start libVLC: %s", exc)
        _fatal(
            "libVLC could not be loaded.\n\n"
            "Populate vendor/vlc/ with libvlc.dll, libvlccore.dll and plugins/ "
            "(see README), or install VLC 3.0.21 x64."
        )
        return 1

    engine.set_volume(int(settings.get("audio.volume", 80)))
    engine.set_muted(bool(settings.get("audio.muted", False)))

    library = Library()
    library.bind(engine)
    metadata = Metadata(engine)
    lyrics = Lyrics()
    equalizer = Equalizer(engine)

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    mode_list = ModeList()

    # --- QML types ---------------------------------------------------------
    # Importing engine.surface registers VideoSurface/PlaneSurface into the
    # Halcyon.Engine module via @QmlElement.
    import engine.surface  # noqa: F401

    qml_engine = QQmlApplicationEngine()
    # One import path: the repository root. Qt maps `import Halcyon.Ui` to
    # <import path>/Halcyon/Ui/qmldir, so the module directories under Halcyon/
    # are what make the imports resolve. Adding ui/ or ui/shell/ here does
    # nothing — a directory only provides a module if its *path* spells the URI.
    qml_engine.addImportPath(str(ROOT))

    ctx = qml_engine.rootContext()
    ctx.setContextProperty("App", controller)
    ctx.setContextProperty("Modes", mode_list)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("Player", engine)
    ctx.setContextProperty("Library", library)
    ctx.setContextProperty("Metadata", metadata)
    ctx.setContextProperty("Lyrics", lyrics)
    ctx.setContextProperty("Equalizer", equalizer)

    # --- per-mode contexts -------------------------------------------------
    # Each mode gets to publish one object. The shell never names a mode; it
    # iterates the registry (§A.2), so Phases 2 and 3 need no change here.
    for spec in mode_registry.all_modes():
        context_object = _build_mode_context(spec, engine, controller, settings)
        if context_object is not None:
            controller.register_context(spec.id, context_object)
            ctx.setContextProperty(_context_name(spec.id), context_object)

    # --- load the UI -------------------------------------------------------
    qml_engine.load(QUrl.fromLocalFile(str(ROOT / "ui" / "Main.qml")))
    if not qml_engine.rootObjects():
        log.error("QML failed to load — see the messages above")
        return 2

    # --- shutdown, in the right order (§9) ---------------------------------
    def on_quit() -> None:
        controller.shutdown()
        engine.shutdown()

    app.aboutToQuit.connect(on_quit)

    # Files passed on the command line go through the same append path as
    # everything else (§4.1).
    media_args = [a for a in argv[1:] if not a.startswith("-")]
    if media_args:
        controller.addPaths(media_args)

    return app.exec()


def _context_name(mode_id: str) -> str:
    """``local`` -> ``LocalPlaylist``. Matches what the mode's QML expects."""
    return f"{mode_id.capitalize()}Playlist"


def _build_mode_context(spec, engine, controller, settings):
    """Create a mode's context object.

    Local is wired here because Phase 1 owns it. Later modes declare a ``setup``
    callable on their ``ModeSpec`` instead, so this function does not grow
    (§A.3).
    """
    if spec.setup is not None:
        return spec.setup(engine=engine, controller=controller, settings=settings)

    if spec.id == "local":
        from modes.local.playlist import PlaylistModel

        playlist = PlaylistModel()
        playlist.playRequested.connect(lambda path, _row: controller.openPath(path))
        playlist.set_repeat_mode(int(settings.get_mode("local", "repeat", 0) or 0))
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
