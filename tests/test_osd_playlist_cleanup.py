"""A Resume / Start Over toast must not outlive deleted playlist media.

Opening another item already emits ``Player.mediaChanged`` and retires the old
resume toast.  Removing the last/current item and Clear Playlist are different:
they stop the engine without opening anything, so no mediaChanged arrives.  The
controller therefore publishes ``playlistPlaybackCleared`` from the shared
action path and the shared shell routes it to the existing complete OSD cleanup.

These source-level checks protect the cross-boundary wiring without requiring a
working Qt GUI.  Behavioural coverage for the actual pill lives beside the
other real-QML OSD tests in ``test_osd_layering.py``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "core" / "app.py"
MAIN_QML = ROOT / "ui" / "Main.qml"


def _app_source() -> str:
    return APP_PY.read_text(encoding="utf-8")


def _main_source() -> str:
    return MAIN_QML.read_text(encoding="utf-8")


def test_controller_declares_playlist_playback_cleared_signal() -> None:
    source = _app_source()
    assert "playlistPlaybackCleared = Signal()" in source


def test_last_selected_item_and_clear_playlist_publish_cleanup() -> None:
    source = _app_source()

    clear_selected = source.split("def clearSelected", 1)[1].split(
        "\n    @Slot()\n    def clearPlaylist", 1
    )[0]
    empty_branch = clear_selected.split("if new_count == 0:", 1)[1].split(
        "\n            else:", 1
    )[0]
    assert "self.playlistPlaybackCleared.emit()" in empty_branch, (
        "removing the current/last item must publish the missing cleanup edge"
    )

    clear_playlist = source.split("def clearPlaylist", 1)[1].split(
        "\n    def _current_path", 1
    )[0]
    assert "self.playlistPlaybackCleared.emit()" in clear_playlist, (
        "Clear Playlist must publish the missing cleanup edge"
    )


def test_replacement_and_nonplaying_removals_do_not_publish_empty_player() -> None:
    """Do not erase a replacement media's freshly shown resume toast."""
    source = _app_source()
    clear_selected = source.split("def clearSelected", 1)[1].split(
        "\n    @Slot()\n    def clearPlaylist", 1
    )[0]
    assert clear_selected.count("self.playlistPlaybackCleared.emit()") == 1

    empty_branch, replacement_branch = clear_selected.split(
        "\n            else:", 1
    )
    assert "self.playlistPlaybackCleared.emit()" in empty_branch
    assert "self.playlistPlaybackCleared.emit()" not in replacement_branch


def test_shared_shell_routes_playlist_cleanup_to_complete_osd_clear() -> None:
    source = _main_source()
    assert "function onPlaylistPlaybackCleared()" in source
    handler = source.split("function onPlaylistPlaybackCleared()", 1)[1]
    handler = handler.split("\n    }", 1)[0]
    assert "osdLayer.clear()" in handler, (
        "playlist playback cleanup must stop timers and forget resumePath"
    )


def test_cleanup_is_not_attached_only_to_desktop_playlist_buttons() -> None:
    """The controller signal also covers Delete and mobile-remote actions."""
    source = _main_source()
    action_host = source.split("id: actionHost", 1)[1].split(
        "// ================================================================", 1
    )[0]
    assert "playlistPlaybackCleared" not in action_host
    assert "osdLayer.clear()" not in action_host, (
        "cleanup belongs to the shared controller event, not a QML button"
    )
