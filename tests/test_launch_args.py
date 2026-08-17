"""Installer/shell launch argument parsing."""

from __future__ import annotations

from core.launch import (
    ACTION_ACTIVATE,
    ACTION_PLAY,
    ACTION_QUEUE,
    LaunchRequest,
    is_playlist_path,
    parse_launch_request,
    split_media_and_playlists,
)


def test_plain_file_argument_means_play() -> None:
    request = parse_launch_request(["Halcyon.exe", r"D:\Movies\film.mkv"])

    assert request.action == ACTION_PLAY
    assert request.paths == [r"D:\Movies\film.mkv"]


def test_context_menu_queue_argument() -> None:
    request = parse_launch_request(["Halcyon.exe", "--queue", r"D:\Music\song.flac"])

    assert request.action == ACTION_QUEUE
    assert request.paths == [r"D:\Music\song.flac"]


def test_equals_form_and_diagnostic_flags_are_supported() -> None:
    request = parse_launch_request([
        "Halcyon.exe",
        "--debug",
        "--play=C:/Videos/trailer.mp4",
        "--trace-shutdown",
    ])

    assert request.action == ACTION_PLAY
    assert request.paths == ["C:/Videos/trailer.mp4"]


def test_no_media_arguments_only_activates_existing_window() -> None:
    request = parse_launch_request(["Halcyon.exe", "--debug"])

    assert request.action == ACTION_ACTIVATE
    assert request.paths == []


def test_playlist_split_includes_pls() -> None:
    media, playlists = split_media_and_playlists([
        "movie.mp4",
        "channels.m3u",
        "radio.pls",
        "folder",
    ])

    assert media == ["movie.mp4", "folder"]
    assert playlists == ["channels.m3u", "radio.pls"]
    assert is_playlist_path("live.m3u8")
    assert is_playlist_path("radio.pls")


def test_launch_request_payload_roundtrip_cleans_unknown_action() -> None:
    request = LaunchRequest.from_payload({"action": "bad", "paths": ["x.mp4"]})

    assert request.action == ACTION_PLAY
    assert request.paths == ["x.mp4"]
