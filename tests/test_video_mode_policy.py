"""The Local video-mode policy — §0.5.1 / §V.2.

Pure decision logic: selection + mode capability + media geometry -> the route
the engine is asked for. No Qt, no libVLC, no display, so the rule that decides
whether a 4K60 file gets hardware output is checkable everywhere.

The one rule that matters more than the others is the *direction of doubt*:
anything unknown, unreadable or not allowed resolves to Soft. Soft always works;
a wrong Turbo guess is a black picture and a fallback.
"""

from __future__ import annotations

import pytest

from core import video_mode as vm


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------
def test_the_dropdown_offers_exactly_auto_soft_turbo_in_that_order():
    assert vm.MODES == ("auto", "soft", "turbo")
    assert [vm.LABELS[m] for m in vm.MODES] == ["Auto", "Soft", "Turbo"]


def test_only_soft_and_turbo_are_routes_the_engine_can_be_asked_for():
    """"auto" is a selection, never an output. Handing it to the engine would
    mean two places decide the same thing."""
    assert vm.EFFECTIVE_MODES == ("soft", "turbo")
    assert vm.AUTO not in vm.EFFECTIVE_MODES


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("auto", "auto"),
        ("Soft", "soft"),
        ("  TURBO ", "turbo"),
        ("", "auto"),
        (None, "auto"),
        ("hardware", "auto"),   # a typo must not silently switch paths
        (17, "auto"),
    ],
)
def test_normalise_never_produces_an_invalid_mode(raw, expected):
    assert vm.normalise(raw) == expected


# ---------------------------------------------------------------------------
# What "demanding" means (§V.2 — the 3840x2160@60 reference case)
# ---------------------------------------------------------------------------
def test_the_reference_case_is_demanding():
    assert vm.is_demanding(3840, 2160, 60) is True


@pytest.mark.parametrize(
    "width, height, fps",
    [
        (1920, 1080, 24),      # the ordinary case
        (1920, 1080, 60),      # ordinary, just smooth
        (1280, 720, 30),
        (2560, 1440, 24),      # 1440p is comfortable at film rates
    ],
)
def test_ordinary_media_is_not_demanding(width, height, fps):
    assert vm.is_demanding(width, height, fps) is False


def test_high_frame_rate_1440p_is_demanding():
    """Pixel count alone is not the cost; 1440p60 is roughly 4K24's load."""
    assert vm.is_demanding(2560, 1440, 60) is True
    assert vm.is_demanding(2560, 1440, 50) is True


def test_4k_is_demanding_at_any_frame_rate():
    assert vm.is_demanding(3840, 2160, 24) is True
    assert vm.is_demanding(3840, 2160, None) is True


def test_letterboxed_and_slightly_off_4k_still_counts():
    """A 2.39:1 film is 3840x1608 in a 4K container — same decode cost."""
    assert vm.is_demanding(3840, 2076, 60) is True


@pytest.mark.parametrize(
    "width, height, fps",
    [
        (None, None, None),
        (0, 0, 60),
        ("", "", ""),
        ("wide", "tall", "fast"),
        (-3840, -2160, 60),
        (float("nan"), float("nan"), 60),
    ],
)
def test_unknown_geometry_is_never_demanding(width, height, fps):
    """The safe direction. Unknown must mean Soft, not "probably fine"."""
    assert vm.is_demanding(width, height, fps) is False


# ---------------------------------------------------------------------------
# resolve() — the whole §V.2 table
# ---------------------------------------------------------------------------
def test_resolution_strings_parse_both_glyphs():
    """Info rows use ×; some libVLC builds / locales emit a plain x."""
    from core.app import _parse_resolution

    assert _parse_resolution("3840\u00d72160") == (3840.0, 2160.0)
    assert _parse_resolution("3840x2160") == (3840.0, 2160.0)
    assert _parse_resolution("3840 x 2160") == (3840.0, 2160.0)
    assert _parse_resolution("") == (0.0, 0.0)
    assert _parse_resolution("unknown") == (0.0, 0.0)


def test_local_auto_picks_turbo_for_demanding_media():
    assert vm.resolve("auto", turbo_allowed=True, width=3840, height=2160, fps=60) == "turbo"


def test_local_auto_picks_soft_for_ordinary_media():
    assert vm.resolve("auto", turbo_allowed=True, width=1920, height=1080, fps=24) == "soft"


def test_local_auto_picks_soft_when_metadata_is_unavailable():
    """§V.2: "chooses Soft for ordinary Local media where possible" — and an
    unmeasurable file is not evidence for Turbo."""
    assert vm.resolve("auto", turbo_allowed=True) == "soft"


def test_forced_soft_is_soft_even_for_demanding_media():
    assert vm.resolve("soft", turbo_allowed=True, width=3840, height=2160, fps=60) == "soft"


def test_forced_turbo_is_turbo_even_for_ordinary_media():
    assert vm.resolve("turbo", turbo_allowed=True, width=640, height=480, fps=24) == "turbo"


@pytest.mark.parametrize("selected", ["auto", "soft", "turbo"])
def test_a_mode_that_may_not_use_turbo_always_gets_soft(selected):
    """M3U's rule (§V.2): always Soft *regardless of the stored Local
    preference*, including a stored "turbo"."""
    assert vm.resolve(
        selected, turbo_allowed=False, width=3840, height=2160, fps=60
    ) == "soft"


def test_turbo_is_opt_in_by_default():
    """Omitting the capability must not hand a caller the native route."""
    assert vm.resolve("turbo", width=3840, height=2160, fps=60) == "soft"


# ---------------------------------------------------------------------------
# has_video — audio-only media (§V.2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("selected", ["auto", "soft", "turbo"])
def test_audio_only_media_is_always_soft(selected):
    """No video track means no pixels to hand a native child window, so even
    an explicit Turbo selection resolves to Soft."""
    assert vm.resolve(
        selected, turbo_allowed=True, has_video=False,
        width=3840, height=2160, fps=60,
    ) == "soft"


def test_a_video_track_leaves_the_normal_rules_alone():
    assert vm.resolve(
        "auto", turbo_allowed=True, has_video=True,
        width=3840, height=2160, fps=60,
    ) == "turbo"
    assert vm.resolve(
        "auto", turbo_allowed=True, has_video=True,
        width=1280, height=720, fps=24,
    ) == "soft"


def test_an_unknown_track_list_is_not_treated_as_audio_only():
    """Unknown (None) is the normal first state of every open. Treating it as
    Soft would make an explicit Turbo choice open Soft and re-open Turbo a
    moment later — a visible blip on every single file."""
    assert vm.resolve("turbo", turbo_allowed=True, has_video=None) == "turbo"
    assert vm.resolve(
        "auto", turbo_allowed=True, has_video=None,
        width=3840, height=2160, fps=60,
    ) == "turbo"


def test_has_video_defaults_to_unknown():
    """Existing callers that never pass it keep their behaviour."""
    assert vm.resolve(
        "turbo", turbo_allowed=True, width=640, height=480
    ) == "turbo"


# ---------------------------------------------------------------------------
# Legacy migration (§V.1 — "may be migrated or ignored", never user-facing)
# ---------------------------------------------------------------------------
def test_a_profile_with_turbo_on_migrates_to_turbo():
    data = {"playback.turboMode": True}
    vm.migrate_legacy(data)
    assert data["playback.videoMode"] == "turbo"


def test_a_profile_with_turbo_off_gets_the_new_default():
    """False was the old default, not a choice of Soft — Auto is the honest
    reading, and Auto resolves ordinary media to Soft anyway."""
    data = {"playback.turboMode": False}
    vm.migrate_legacy(data)
    assert "playback.videoMode" not in data


def test_the_legacy_key_never_survives_migration():
    for value in (True, False, "true", None):
        data = {"playback.turboMode": value}
        vm.migrate_legacy(data)
        assert "playback.turboMode" not in data, (
            "the removed Turbo checkbox must not stay in the profile — it is "
            "the input to a migration, not state"
        )


def test_an_explicit_new_choice_beats_a_stale_legacy_key():
    data = {"playback.turboMode": True, "playback.videoMode": "soft"}
    vm.migrate_legacy(data)
    assert data["playback.videoMode"] == "soft", (
        "the user chose Soft in the new dropdown; a leftover checkbox value "
        "must not override it"
    )


def test_migration_repairs_a_corrupt_new_value():
    data = {"playback.videoMode": "HARDWARE"}
    vm.migrate_legacy(data)
    assert data["playback.videoMode"] == "auto"


def test_video_backend_is_not_migrated_or_removed():
    """It selects the Soft chroma (I420/RV32) and still does, internally. §V
    removes it from the visible Settings, not from the engine."""
    data = {"video.backend": "rv32"}
    vm.migrate_legacy(data)
    assert data["video.backend"] == "rv32"


def test_migration_of_an_untouched_profile_changes_nothing():
    data = {"ui.theme": "dark"}
    assert vm.migrate_legacy(data) == {"ui.theme": "dark"}
