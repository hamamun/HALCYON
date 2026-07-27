"""Adding files must actually reach the queue — the Milestone 1.5 regression.

Three separate bugs conspired to make "click Add, pick a file, nothing appears"
the first thing anyone saw. Each one alone was enough to break it, so each gets
its own test here.

1. ``main.py`` bound the libVLC facade to a local named ``engine`` and then ran
   ``import engine.surface``, which rebinds that name to the *package*. QML's
   ``Player`` became a module.
2. ``PlaylistModel.count`` was a ``Slot``, so ``visible: model.count() > 0`` was
   a one-shot call rather than a binding — the list stayed hidden even once the
   model held tracks.
3. Paths arrived from ``FileDialog`` as percent-encoded URLs and were cleaned
   with ``.replace("file://", "")``, which leaves ``/E:/drvie%20personal/...``
   — a path that exists nowhere, silently dropped.

No Qt GUI, no libVLC, no display: these run anywhere.
"""

from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication, QUrl

from core import paths
from modes.local.playlist import PlaylistModel

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def media_dir(tmp_path):
    """A directory whose name contains a space, like the reported ``E:\\drvie
    personal``. The space is the whole point: it is what gets percent-encoded."""
    d = tmp_path / "drvie personal"
    d.mkdir()
    for name in ("movie one.mkv", "song two.mp3"):
        (d / name).write_bytes(b"\0" * 32)
    return d


# --------------------------------------------------------------- path fixes ---
@pytest.mark.parametrize(
    "raw,expected_suffix",
    [
        ("file:///C:/media/a%20b/clip.mkv", "C:/media/a b/clip.mkv"),
        ("file:///C:/media/plain.mkv", "C:/media/plain.mkv"),
        (r"C:\media\a b\clip.mkv", r"C:\media\a b\clip.mkv"),
        ("/home/user/clip.mkv", "/home/user/clip.mkv"),
    ],
)
def test_normalise_path_decodes_and_strips(raw, expected_suffix):
    assert paths.normalise_path(raw) == expected_suffix


def test_normalise_path_is_idempotent():
    once = paths.normalise_path("file:///C:/a%20b/c.mkv")
    assert paths.normalise_path(once) == once


def test_normalise_path_keeps_unc_host():
    assert "server" in paths.normalise_path("file://server/share/x.mkv")


# ------------------------------------------------------------ the add path ---
@pytest.mark.parametrize("encoded", [False, True])
def test_add_paths_accepts_file_dialog_urls(qt_app, media_dir, encoded):
    """The exact handoff: URL strings straight from FileDialog.selectedFiles.

    Run twice, because the two renderings of the same QUrl differ exactly where
    this bug lived. ``toString()`` leaves the space literal; ``toEncoded()``
    gives ``%20``. QML hands over whichever the platform produced, so both have
    to survive the trip.
    """
    model = PlaylistModel()
    files = sorted(media_dir.iterdir())
    if encoded:
        urls = [bytes(QUrl.fromLocalFile(str(p)).toEncoded()).decode() for p in files]
        assert "%20" in urls[0], "this variant must exercise percent-decoding"
    else:
        urls = [QUrl.fromLocalFile(str(p)).toString() for p in files]
        assert " " in urls[0], "this variant must exercise a literal space"
    assert urls[0].startswith("file://")

    assert model.add_paths(urls) == 2
    assert model.count == 2
    for row in range(model.rowCount()):
        stored = model.data(model.index(row, 0), PlaylistModel.PathRole)
        assert os.path.exists(stored), f"stored path does not exist: {stored}"
    model.shutdown()


def test_add_paths_accepts_plain_paths(qt_app, media_dir):
    model = PlaylistModel()
    assert model.add_paths([str(p) for p in sorted(media_dir.iterdir())]) == 2
    model.shutdown()


def test_add_paths_recurses_a_folder(qt_app, media_dir):
    nested = media_dir / "season 1"
    nested.mkdir()
    (nested / "ep 1.mkv").write_bytes(b"\0" * 16)

    model = PlaylistModel()
    added = model.add_paths([QUrl.fromLocalFile(str(media_dir)).toString()])
    assert added == 3
    model.shutdown()


def test_add_paths_ignores_missing_and_empty(qt_app):
    model = PlaylistModel()
    assert model.add_paths(["", "   ", "/definitely/not/here.mkv"]) == 0
    assert model.count == 0
    model.shutdown()


# ------------------------------------------------- QML-visible reactivity ---
def test_count_is_a_notifying_property(qt_app, media_dir):
    """`count` must be a Property with a notify signal.

    As a Slot it is still *callable* from QML, so the bug is invisible in review
    — but `visible: model.count > 0` never re-evaluates and the panel stays on
    its empty state forever.
    """
    model = PlaylistModel()
    meta = model.metaObject()
    idx = meta.indexOfProperty("count")
    assert idx >= 0, "count must be a QML property, not only a slot"
    assert meta.property(idx).hasNotifySignal(), "count must notify on change"

    seen: list[int] = []
    model.countChanged.connect(lambda: seen.append(model.count))
    model.add_paths([str(next(iter(sorted(media_dir.iterdir()))))])
    assert seen == [1]
    model.shutdown()


@pytest.mark.parametrize("name", ["count", "currentIndex", "repeatMode", "shuffle"])
def test_qml_facing_state_is_bindable(qt_app, name):
    # Hold the model in a local: a temporary would be collected while its
    # QMetaObject is still being read, which segfaults rather than failing.
    model = PlaylistModel()
    meta = model.metaObject()
    idx = meta.indexOfProperty(name)
    assert idx >= 0, f"{name} must be exposed as a property for QML bindings"
    assert meta.property(idx).hasNotifySignal(), f"{name} must have a notify signal"
    model.shutdown()


def test_repeat_and_shuffle_round_trip(qt_app):
    model = PlaylistModel()
    assert model.repeatMode == 0
    model.cycle_repeat()
    assert model.repeatMode == 1
    model.set_repeat_mode(2)
    assert model.repeatMode == 2

    assert model.shuffle is False
    model.toggle_shuffle()
    assert model.shuffle is True
    model.shutdown()


# ------------------------------------------------------- the shadowing bug ---
def test_main_never_binds_the_engine_package_to_a_local():
    """`import engine.<mod>` must not run where a local named `engine` lives.

    This is the root cause of the original report and it fails silently: the
    name simply starts pointing at a module, so `Player` in QML becomes
    `<module 'engine'>` and `engine.shutdown()` raises AttributeError at exit.
    A plain-text check is enough and needs no Qt.
    """
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    offences = []
    for node in ast.walk(tree):
        # `import engine.surface` binds the top-level name `engine`.
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "engine" and alias.asname is None:
                    offences.append(f"line {node.lineno}: import {alias.name}")
    assert not offences, (
        "main.py must use `from engine.x import Y` (or an `as` alias); "
        "a bare `import engine.x` rebinds the name `engine`: " + "; ".join(offences)
    )


def test_main_assigns_the_player_to_a_non_colliding_name():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "engine = VlcEngine(" not in source, (
        "the VlcEngine instance must not be bound to the name `engine` — "
        "that is the name of a package in this repository"
    )
    assert "player = VlcEngine(" in source
