"""Local playlist persistence across application sessions."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer

from main import _build_mode_context
from modes.local import SPEC as LOCAL_SPEC
from modes.local.playlist import (
    LOCAL_PLAYLIST_FILENAME,
    SAVE_DEBOUNCE_MS,
    PlaylistModel,
)


def _media_files(
    folder: Path, names=("one.mp3", "two.mkv", "three.flac")
) -> list[Path]:
    files = [folder / name for name in names]
    for path in files:
        path.write_bytes(b"\0" * 32)
    return files


def test_playlist_order_and_current_item_survive_restart(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    files = _media_files(tmp_path)

    first = PlaylistModel(storage_path=store)
    assert first.add_paths([str(path) for path in files]) == 3
    first.play_index(1)
    first.move_row(1, 2)
    first.shutdown()

    second = PlaylistModel(storage_path=store)
    assert [second.path_at(row) for row in range(second.count)] == [
        str(files[0].resolve()),
        str(files[2].resolve()),
        str(files[1].resolve()),
    ]
    assert second.currentIndex == 2
    assert second.path_at(second.currentIndex) == str(files[1].resolve())
    second.shutdown()


def test_restored_playlist_does_not_start_playback(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    media = _media_files(tmp_path, ("quiet-start.mp3",))[0]

    first = PlaylistModel(storage_path=store)
    first.add_paths([str(media)])
    first.play_index(0)
    first.shutdown()

    class _Settings:
        path = tmp_path / "settings.json"

        @staticmethod
        def get_mode(_mode: str, _key: str, default=None):
            return default

        @staticmethod
        def set_mode(_mode: str, _key: str, _value) -> None:
            pass

    class _Controller:
        def __init__(self) -> None:
            self.opened: list[str] = []

        def openPath(self, path: str) -> None:  # noqa: N802 - Qt-facing spelling
            self.opened.append(path)

    controller = _Controller()
    restored = _build_mode_context(LOCAL_SPEC, None, controller, _Settings())
    assert restored.count == 1
    assert restored.currentIndex == 0
    assert controller.opened == []
    restored.shutdown()


def test_unavailable_files_are_skipped_without_forgetting_them(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    files = _media_files(tmp_path, ("online.mp3", "removable.mp3"))

    first = PlaylistModel(storage_path=store)
    first.add_paths([str(path) for path in files])
    first.shutdown()

    files[1].unlink()
    without_drive = PlaylistModel(storage_path=store)
    assert without_drive.count == 1
    assert without_drive.path_at(0) == str(files[0].resolve())
    without_drive.shutdown()

    # Merely launching while a drive is absent must not permanently erase its
    # rows. If it is available on a later launch, the original queue returns.
    files[1].write_bytes(b"\0" * 32)
    reconnected = PlaylistModel(storage_path=store)
    assert [reconnected.path_at(row) for row in range(reconnected.count)] == [
        str(files[0].resolve()),
        str(files[1].resolve()),
    ]
    reconnected.shutdown()


def test_clear_playlist_persists_as_empty(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    media = _media_files(tmp_path, ("clear-me.mp3",))[0]

    first = PlaylistModel(storage_path=store)
    first.add_paths([str(media)])
    first.shutdown()

    second = PlaylistModel(storage_path=store)
    assert second.count == 1
    second.clear()
    second.shutdown()

    third = PlaylistModel(storage_path=store)
    assert third.count == 0
    third.shutdown()

    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["tracks"] == []
    assert saved["currentIndex"] == -1


def test_removal_is_saved_by_debounce_before_normal_shutdown(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    files = _media_files(tmp_path, ("keep.mp3", "remove.mp3"))

    first = PlaylistModel(storage_path=store)
    first.add_paths([str(path) for path in files])
    first.shutdown()

    second = PlaylistModel(storage_path=store)
    assert second.remove_rows([1]) is False
    assert second._save_timer.isActive()
    wait = QEventLoop()
    QTimer.singleShot(SAVE_DEBOUNCE_MS + 100, wait.quit)
    wait.exec()

    # Read the store before shutdown: the timer, not the normal-exit flush,
    # must already have protected the mutation against an abnormal exit.
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert [row["path"] for row in saved["tracks"]] == [str(files[0].resolve())]
    second.shutdown()


def test_restore_skips_malformed_missing_and_unsupported_rows(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    playable = _media_files(tmp_path, ("playable.mp3",))[0]
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not media", encoding="utf-8")
    store.write_text(
        json.dumps(
            {
                "version": 1,
                "currentIndex": float("inf"),
                "currentPath": None,
                "tracks": [
                    None,
                    {"title": "no path"},
                    {"path": str(tmp_path / "missing.mkv")},
                    {"path": str(unsupported)},
                    {"path": str(playable), "duration": float("inf")},
                ],
            }
        ),
        encoding="utf-8",
    )

    model = PlaylistModel(storage_path=store)
    assert model.count == 1
    assert model.path_at(0) == str(playable)
    assert model.currentIndex == -1
    assert model.data(model.index(0), PlaylistModel.DurationRole) == 0
    model.shutdown()


def test_corrupt_playlist_store_is_backed_up_and_does_not_block_startup(
    tmp_path,
) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    store.write_text("{not json", encoding="utf-8")

    model = PlaylistModel(storage_path=store)
    assert model.count == 0
    model.shutdown()

    assert not store.exists()
    assert (tmp_path / "local-playlist.corrupt.json").read_text(
        encoding="utf-8"
    ) == "{not json"


def test_non_utf8_playlist_store_is_treated_as_corrupt(tmp_path) -> None:
    store = tmp_path / LOCAL_PLAYLIST_FILENAME
    store.write_bytes(b"\xff\xfe\xfa")

    model = PlaylistModel(storage_path=store)
    assert model.count == 0
    model.shutdown()

    assert not store.exists()
    assert (tmp_path / "local-playlist.corrupt.json").read_bytes() == b"\xff\xfe\xfa"
