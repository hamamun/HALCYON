"""Drive browser — §R.2 Local chip → Files. Pure filesystem logic."""

from __future__ import annotations

import os

import pytest

from remote import drives


def test_list_drives_shape():
    drives_list = drives.list_drives()
    assert isinstance(drives_list, list)
    assert drives_list, "at least the root must be listed"
    for d in drives_list:
        assert "name" in d and "path" in d
        assert d["path"].replace("\\", "/").startswith("/") or ":" in d["path"]


def test_list_dir_filters_media(tmp_path):
    (tmp_path / "Movies").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hiddenfile.mp4").write_bytes(b"x")
    (tmp_path / "movie.mp4").write_bytes(b"x")
    (tmp_path / "song.flac").write_bytes(b"x")
    (tmp_path / "subs.srt").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "archive.zip").write_bytes(b"x")

    listing = drives.list_dir(str(tmp_path))

    assert listing["path"].endswith(str(tmp_path).replace("\\", "/"))
    folders = [f["name"] for f in listing["folders"]]
    assert "Movies" in folders
    assert ".hidden" not in folders

    files = {f["name"]: f["kind"] for f in listing["files"]}
    assert files.get("movie.mp4") == drives.KIND_VIDEO
    assert files.get("song.flac") == drives.KIND_AUDIO
    assert files.get("subs.srt") == drives.KIND_SUBTITLE
    assert "notes.txt" not in files
    assert "archive.zip" not in files
    assert ".hiddenfile.mp4" not in files


def test_list_dir_forward_slashes(tmp_path):
    listing = drives.list_dir(str(tmp_path))
    assert "\\" not in listing["path"]


def test_list_dir_missing_raises():
    with pytest.raises(ValueError):
        drives.list_dir("/definitely/not/here/12345")


def test_list_dir_on_file_raises(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        drives.list_dir(str(f))


def test_list_dir_parent(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    listing = drives.list_dir(str(sub))
    # parent should point at tmp_path (normalised)
    assert listing["parent"] == str(tmp_path).replace("\\", "/")


def test_kind_for():
    assert drives.kind_for("x.MKV") == drives.KIND_VIDEO
    assert drives.kind_for("y.flac") == drives.KIND_AUDIO
    assert drives.kind_for("z.srt") == drives.KIND_SUBTITLE
    assert drives.kind_for("z.txt") is None
    assert drives.is_media("a.mp4") is True
    assert drives.is_media("b.pdf") is False
