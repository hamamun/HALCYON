"""The stored side of Video mode — §V.1.

Two promises the settings store has to keep:

1. a fresh profile defaults to ``playback.videoMode = "auto"``;
2. an existing profile written by a version that had the Turbo checkbox loads
   without either legacy key coming back as user-facing state.

These drive the real :class:`core.settings.Settings` against a temporary file
rather than a dict, because the migration hook lives inside ``load()`` and a
test that called the migration function directly would pass with the hook
unwired (``test_video_mode_policy.py`` already covers the function itself).
"""

from __future__ import annotations

import json

import pytest

from core.settings import DEFAULTS, Settings


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


def _write(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
def test_the_default_video_mode_is_auto():
    assert DEFAULTS["playback.videoMode"] == "auto"


def test_a_fresh_profile_reads_auto(settings_path):
    settings = Settings(path=settings_path)
    assert settings.get("playback.videoMode") == "auto"
    assert settings.get_string("playback.videoMode") == "auto"


def test_the_removed_turbo_checkbox_is_not_a_default_any_more():
    assert "playback.turboMode" not in DEFAULTS, (
        "playback.turboMode is a migration input, not a setting Halcyon owns "
        "(§V.1) — shipping it as a default resurrects it in every new profile"
    )


def test_video_backend_survives_as_an_internal_default():
    """The Soft chroma switch (I420/RV32) is still needed; §V only removes it
    from the visible Settings dialog."""
    assert DEFAULTS["video.backend"] == "auto"


# ---------------------------------------------------------------------------
# Migration on load
# ---------------------------------------------------------------------------
def test_an_old_profile_with_turbo_on_loads_as_turbo(settings_path):
    _write(settings_path, {"playback.turboMode": True, "audio.volume": 55})
    settings = Settings(path=settings_path)

    assert settings.get("playback.videoMode") == "turbo"
    assert settings.get("audio.volume") == 55, "migration must not disturb the rest"


def test_an_old_profile_with_turbo_off_loads_as_auto(settings_path):
    _write(settings_path, {"playback.turboMode": False})
    settings = Settings(path=settings_path)

    assert settings.get("playback.videoMode") == "auto"


def test_the_legacy_key_is_gone_from_the_loaded_profile(settings_path):
    _write(settings_path, {"playback.turboMode": True})
    settings = Settings(path=settings_path)

    assert "playback.turboMode" not in settings.as_dict()


def test_the_legacy_key_is_not_written_back_out(settings_path):
    _write(settings_path, {"playback.turboMode": True})
    settings = Settings(path=settings_path)
    settings.flush()

    written = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "playback.turboMode" not in written
    assert written["playback.videoMode"] == "turbo"


def test_a_new_choice_is_not_overridden_by_a_stale_legacy_key(settings_path):
    _write(settings_path, {"playback.turboMode": True, "playback.videoMode": "soft"})
    settings = Settings(path=settings_path)

    assert settings.get("playback.videoMode") == "soft"


def test_a_corrupt_stored_mode_falls_back_to_auto(settings_path):
    _write(settings_path, {"playback.videoMode": "hardware!"})
    settings = Settings(path=settings_path)

    assert settings.get("playback.videoMode") == "auto"


def test_an_old_profile_keeps_its_video_backend(settings_path):
    _write(settings_path, {"video.backend": "rv32", "playback.turboMode": True})
    settings = Settings(path=settings_path)

    assert settings.get("video.backend") == "rv32"
    assert settings.get("playback.videoMode") == "turbo"


def test_a_round_trip_through_settings_keeps_the_choice(settings_path):
    first = Settings(path=settings_path)
    first.set("playback.videoMode", "turbo")
    first.flush()

    second = Settings(path=settings_path)
    assert second.get("playback.videoMode") == "turbo"
