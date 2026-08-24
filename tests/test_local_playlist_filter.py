"""Local playlist filtering keeps the source queue and playback indices intact."""

from __future__ import annotations

from modes.local.playlist import PlaylistModel


def _media_files(folder, names=("Alpha.mp3", "Beta.mkv", "Gamma.flac")):
    files = [folder / name for name in names]
    for path in files:
        path.write_bytes(b"media")
    return files


def test_local_filter_matches_title_and_path_case_insensitively(tmp_path) -> None:
    files = _media_files(tmp_path)
    model = PlaylistModel()
    assert model.add_paths([str(path) for path in files]) == 3

    view = model.filteredModel
    view.setFilter("BETA")
    assert view.count == 1
    assert view.data(view.index(0, 0), view.SourceIndexRole) == 1

    view.setFilter(str(tmp_path).upper())
    assert view.count == 3
    model.shutdown()


def test_filter_keeps_actions_mapped_to_complete_playlist(tmp_path) -> None:
    files = _media_files(tmp_path)
    model = PlaylistModel()
    model.add_paths([str(path) for path in files])
    view = model.filteredModel
    view.setFilter("beta")

    source_row = view.sourceRowAt(0)
    assert source_row == 1
    model.play_index(source_row)
    assert model.currentIndex == 1
    assert model.path_at(model.currentIndex) == str(files[1].resolve())
    model.shutdown()


def test_filtered_current_index_tracks_playback_without_changing_source_index(tmp_path) -> None:
    files = _media_files(tmp_path)
    model = PlaylistModel()
    model.add_paths([str(path) for path in files])
    view = model.filteredModel
    view.setFilter("gamma")

    model.play_index(2)
    assert model.currentIndex == 2
    assert view.currentIndex == 0

    model.play_index(0)
    assert model.currentIndex == 0
    assert view.currentIndex == -1

    view.setFilter("")
    assert view.currentIndex == 0
    model.shutdown()
