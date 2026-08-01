"""Resume, Start Over and the one canonical media key — §P1.5.

The bug these lock down was invisible rather than loud. ``Library`` filed an
entry under the spelling the *engine* produced and looked it up under the
spelling the *playlist* produced:

    playlist -> openPath()   -> resume_position("E:\\Movies\\film.mkv")
    engine   -> mediaChanged -> note_opened("E:/Movies/film.mkv")

Those are the same file and two different dictionary keys, so on Windows every
lookup missed: ``resume_position`` returned 0 for everything, playback never
resumed, ``resumePrompted`` was never emitted (so the toast could never appear)
and ``clear_position`` zeroed nothing. Nothing raised and nothing was logged.

So the tests that matter are the ones that write with one spelling and read with
another — asserting on a single spelling is what let this through.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from core.app import AppController
from core.library import Library, media_key


@pytest.fixture(scope="module")
def _app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def library(_app, tmp_path, monkeypatch):
    """A Library writing into a throwaway profile."""
    monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path))
    from core import paths

    monkeypatch.setattr(paths, "data_file", lambda name: tmp_path / name)
    return Library()


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "film.mkv"
    path.write_bytes(b"")
    return path


# --------------------------------------------------------------- the key ---
def test_media_key_folds_every_spelling_of_one_file(media):
    """URL, native separators and surrounding whitespace are one entry."""
    canonical = media_key(str(media))

    assert media_key(media.as_uri()) == canonical
    assert media_key(str(media).replace("/", os.sep)) == canonical
    assert media_key(f"  {media}  ") == canonical


def test_media_key_folds_a_relative_path_onto_its_absolute_form(media, monkeypatch):
    """The command-line route.

    ``halcyon film.mkv`` reaches the playlist as ``film.mkv`` but reaches the
    library as ``/home/me/film.mkv`` via the engine's MRL. This half of the bug
    reproduces on every platform, which is what makes it the useful guard on
    Linux CI — the separator half below only ever bit Windows.
    """
    monkeypatch.chdir(media.parent)
    assert media_key("film.mkv") == media_key(str(media))
    assert media_key("./film.mkv") == media_key(str(media))


def test_media_key_folds_windows_spellings(monkeypatch):
    """The original Windows failure, reproduced on any platform.

    On Linux ``os.sep`` is ``/`` and ``normcase`` is a no-op, so the real-world
    mismatch — ``E:\\Movies\\Film.mkv`` from the playlist versus
    ``E:/Movies/Film.mkv`` from the engine's MRL — cannot occur natively and a
    test written against real paths passes with or without the fix. Swapping in
    ``ntpath`` exercises the exact folding Windows relies on, so removing
    ``normcase``/``resolve`` from ``media_key`` fails here rather than shipping.
    """
    import ntpath

    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    # resolve() is the other half; stub it so this stays a pure string test
    # rather than depending on an E: drive existing.
    monkeypatch.setattr(
        Path, "resolve", lambda self, strict=False: Path(str(self).replace("\\", "/"))
    )

    from_playlist = media_key("E:\\Movies\\Film.mkv")
    from_engine = media_key("E:/Movies/Film.mkv")
    different_case = media_key("e:\\movies\\film.mkv")

    assert from_playlist == from_engine == different_case


def test_media_key_leaves_stream_urls_alone():
    """Phase 2's HLS URLs are not filesystem paths — resolve() would wreck them."""
    url = "https://example.com/live/channel.m3u8"
    assert media_key(url) == url


def test_media_key_survives_a_missing_file(tmp_path):
    """An unplugged drive must not orphan the history recorded from it."""
    gone = tmp_path / "removed.mkv"
    assert media_key(str(gone)) == media_key(gone.as_uri())


# ------------------------------------------------------------- the round ---
def test_position_saved_by_the_engine_is_found_by_the_playlist(library, media):
    """The exact production round-trip, and the regression that started this.

    Written the way ``_on_media_changed`` writes it (a normalised MRL), read the
    way ``openPath`` reads it (whatever the playlist stored).
    """
    engine_spelling = media_key(media.as_uri())
    playlist_spelling = str(media)

    library.note_opened(engine_spelling)
    library.record_position(engine_spelling, 14 * 60_000 + 27_000, 90 * 60_000)

    assert library.resume_position(playlist_spelling) == 867_000


def test_clear_position_hits_the_entry_the_engine_created(library, media):
    """Start Over must actually forget, not merely appear to."""
    library.note_opened(media.as_uri())
    library.record_position(media.as_uri(), 867_000, 90 * 60_000)

    library.clear_position(str(media))

    assert library.resume_position(str(media)) == 0


def test_one_file_never_becomes_two_recent_rows(library, media):
    library.note_opened(media.as_uri())
    library.note_opened(str(media))
    library.note_opened(str(media).replace("/", os.sep))

    assert len(library.recent) == 1


def test_recent_shows_a_readable_path_not_the_folded_key(library, media):
    """normcase() is for lookups; users must not see lower-cased filenames."""
    library.note_opened(str(media))
    assert library.recent[0]["path"] == str(media)
    assert library.recent[0]["title"] == "film"


# ------------------------------------------------------------ thresholds ---
@pytest.mark.parametrize(
    "position, duration, expected",
    [
        (29_000, 90 * 60_000, 0),          # under 30 s in
        (31_000, 90 * 60_000, 31_000),     # just over
        (89 * 60_000, 90 * 60_000, 0),     # practically finished
        (867_000, 0, 867_000),             # duration unknown yet
    ],
)
def test_resume_thresholds(library, media, position, duration, expected):
    library.note_opened(str(media))
    library.record_position(str(media), position, duration)
    assert library.resume_position(str(media)) == expected


# -------------------------------------------------------------- migration ---
def test_load_merges_entries_written_by_an_older_build(_app, tmp_path, monkeypatch):
    """An existing profile holds both spellings; upgrading must not lose them."""
    import json

    from core import paths

    media = tmp_path / "film.mkv"
    media.write_bytes(b"")
    recent = tmp_path / "recent.json"
    recent.write_text(
        json.dumps(
            {
                "entries": [
                    {"path": str(media), "position": 100, "duration": 90 * 60_000,
                     "opened": 1.0},
                    {"path": media.as_uri(), "position": 867_000,
                     "duration": 90 * 60_000, "opened": 2.0},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "data_file", lambda name: tmp_path / name)

    library = Library()

    assert len(library.recent) == 1
    # The more recently opened of the two wins.
    assert library.resume_position(str(media)) == 867_000


# ------------------------------------------------------------- controller ---
class _Engine(QObject):
    """Enough of VlcEngine for the controller to talk to."""

    mediaChanged = Signal(str)
    endReached = Signal()
    tracksChanged = Signal()
    stateChanged = Signal(int)
    errorOccurred = Signal(str)

    isPlaying = True
    time = 0
    duration = 0
    currentMedia = ""

    def __init__(self) -> None:
        super().__init__()
        self.pending_resume = 0
        self.seeks: list[int] = []

    def open(self, path, start_ms=0):
        self.pending_resume = start_ms
        self.mediaChanged.emit(Path(path).resolve().as_uri())

    def cancel_pending_resume(self):
        self.pending_resume = 0

    def seek(self, ms):
        self.seeks.append(ms)

    def __getattr__(self, name):
        return MagicMock()


@pytest.fixture
def wired(_app, library, media, monkeypatch):
    from core.settings import Settings

    engine = _Engine()
    library.bind(engine)
    controller = AppController(
        engine, Settings(), library, MagicMock(), MagicMock(), MagicMock()
    )
    prompts: list[tuple[str, int]] = []
    controller.resumePrompted.connect(lambda p, ms: prompts.append((p, ms)))
    return controller, engine, library, prompts


def test_openpath_emits_resumeprompted_for_a_playlist_path(wired, media):
    """Without this the toast has nothing to listen to — the original symptom."""
    controller, engine, library, prompts = wired
    playlist_spelling = str(media)

    controller.openPath(playlist_spelling)                 # first watch
    library.record_position(library._current, 867_000, 90 * 60_000)
    controller.openPath(playlist_spelling)                 # come back to it

    assert prompts == [(playlist_spelling, 867_000)]
    assert engine.pending_resume == 867_000


def test_no_prompt_when_resume_is_disabled(wired, media):
    controller, engine, library, prompts = wired
    controller._settings.set("playback.resumeEnabled", False)

    controller.openPath(str(media))
    library.record_position(library._current, 867_000, 90 * 60_000)
    controller.openPath(str(media))

    assert prompts == []
    assert engine.pending_resume == 0


def test_start_over_rewinds_forgets_and_cancels_the_pending_seek(wired, media):
    """All three halves, and the ordering that makes it stick.

    Cancelling last would let the queued resume seek land *after* the seek to
    zero and drag playback straight back to where the user left.
    """
    controller, engine, library, _ = wired

    controller.openPath(str(media))
    library.record_position(library._current, 867_000, 90 * 60_000)
    controller.openPath(str(media))
    assert engine.pending_resume == 867_000

    controller.startOver(str(media))

    assert engine.seeks == [0]
    assert engine.pending_resume == 0
    assert library.resume_position(str(media)) == 0


def test_start_over_survives_a_library_that_throws(wired, media):
    """A failed bookkeeping write must still rewind the picture."""
    controller, engine, _library, _ = wired
    controller._library = MagicMock()
    controller._library.clear_position.side_effect = OSError("disk gone")

    controller.startOver(str(media))

    assert engine.seeks == [0]
