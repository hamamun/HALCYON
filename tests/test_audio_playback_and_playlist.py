"""Tests for playlist management, clear playlist, clear selected, shuffle/repeat logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QCoreApplication

from core.app import AppController
from modes.local.playlist import PlaylistModel, RepeatMode


@pytest.fixture(scope="module")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def playlist_with_tracks(qt_app, tmp_path):
    p1 = tmp_path / "track1.mp3"
    p2 = tmp_path / "track2.mp3"
    p3 = tmp_path / "track3.mp3"
    p4 = tmp_path / "track4.mp3"
    for p in (p1, p2, p3, p4):
        p.write_bytes(b"\0" * 32)

    model = PlaylistModel()
    model.add_paths([str(p1), str(p2), str(p3), str(p4)])
    return model, [str(p1), str(p2), str(p3), str(p4)]


# ---------------------------------------------------------------- Clear Playlist ---
def test_clear_playlist_resets_engine_and_metadata(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(1)
    assert model.current_index() == 1

    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    controller.clearPlaylist()

    assert model.count == 0
    assert model.current_index() == -1
    engine.stop.assert_called_once()
    metadata.load.assert_called_with("")
    lyrics.load.assert_called_with("")


def test_play_pause_when_playlist_empty_does_not_play(qt_app):
    model = PlaylistModel()
    engine = MagicMock()
    from engine.vlc_engine import State
    engine.state = State.Stopped
    engine.currentMedia = ""

    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    # Pressing play on empty playlist
    assert controller.playPause() is False

    # Engine toggle or play should NOT have been called
    engine.toggle.assert_not_called()
    engine.play.assert_not_called()


def test_play_pause_when_stopped_starts_first_track(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks

    engine = MagicMock()
    from engine.vlc_engine import State
    engine.state = State.Stopped

    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    # Connected playRequested signal
    requested = []
    model.playRequested.connect(lambda p, i: requested.append((p, i)))

    assert controller.playPause() is True

    assert model.current_index() == 0
    assert len(requested) == 1
    assert requested[0][1] == 0


# ---------------------------------------------------------------- Clear Selected ---
def test_clear_selected_playing_track_autostarts_next_track(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(1)  # Track 2 is playing (index 1)

    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    requested = []
    model.playRequested.connect(lambda p, i: requested.append((p, i)))

    # Clear selected track 1 (the currently playing track)
    controller.clearSelected([1])

    assert model.count == 3
    # Index 1 in new list is former track 3 (paths[2])
    assert model.current_index() == 1
    assert len(requested) == 1
    assert requested[0][0] == paths[2]


def test_clear_selected_last_track_autostarts_previous_track(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(3)  # Track 4 (index 3, last track) is playing

    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    requested = []
    model.playRequested.connect(lambda p, i: requested.append((p, i)))

    # Clear last track (index 3)
    controller.clearSelected([3])

    assert model.count == 3
    # New playing track should be index 2 (former track 3)
    assert model.current_index() == 2
    assert len(requested) == 1
    assert requested[0][0] == paths[2]


def test_clear_selected_only_track_stops_playback(qt_app, tmp_path):
    p = tmp_path / "single.mp3"
    p.write_bytes(b"\0" * 32)
    model = PlaylistModel()
    model.add_paths([str(p)])
    model.play_index(0)

    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    controller.clearSelected([0])

    assert model.count == 0
    assert model.current_index() == -1
    engine.stop.assert_called_once()
    metadata.load.assert_called_with("")


def test_clear_selected_non_playing_track_keeps_playing_track(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(2)  # Track 3 (index 2) is playing

    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = "local"
    library = MagicMock()
    metadata = MagicMock()
    lyrics = MagicMock()
    equalizer = MagicMock()

    controller = AppController(engine, settings, library, metadata, lyrics, equalizer)
    controller.register_context("local", model)

    # Remove track 0 (index 0)
    controller.clearSelected([0])

    assert model.count == 3
    # Formerly index 2 shifted to index 1, still playing
    assert model.current_index() == 1
    assert model.path_at(1) == paths[2]
    engine.stop.assert_not_called()


# ---------------------------------------------------- Shuffle and Repeat Logic ---
def test_shuffle_repeat_all_no_duplicate_at_cycle_end(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(0)
    model.set_repeat_mode(RepeatMode.All)
    model.toggle_shuffle()

    order_cycle_1 = []
    cur = model.current_index()
    order_cycle_1.append(cur)

    # Play through rest of cycle 1
    for _ in range(len(paths) - 1):
        nxt = model.next_index()
        assert nxt != -1
        model.play_index(nxt)
        order_cycle_1.append(nxt)

    # Total unique tracks in cycle 1
    assert set(order_cycle_1) == {0, 1, 2, 3}

    # Now get the next track for start of cycle 2
    last_track_cycle_1 = order_cycle_1[-1]
    first_track_cycle_2 = model.next_index()

    # CRITICAL VERIFICATION: the first track of cycle 2 MUST NOT be the same as the last track of cycle 1!
    assert first_track_cycle_2 != last_track_cycle_1


def test_shuffle_previous_navigates_backward_in_shuffle_order(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.play_index(0)
    model.set_repeat_mode(RepeatMode.All)
    model.toggle_shuffle()

    # Move forward 2 steps
    nxt1 = model.next_index()
    model.play_index(nxt1)
    nxt2 = model.next_index()
    model.play_index(nxt2)

    # Now move previous
    prev1 = model.previous_index()
    assert prev1 == nxt1
    model.play_index(prev1)

    prev2 = model.previous_index()
    assert prev2 == 0


def test_repeat_one_takes_precedence_over_shuffle(qt_app, playlist_with_tracks):
    model, paths = playlist_with_tracks
    model.set_repeat_mode(RepeatMode.One)
    model.toggle_shuffle()

    model.play_index(1)
    assert model.next_index() == 1
    assert model.previous_index() == 1
