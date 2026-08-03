"""Regression checks for M3U's filter clear affordance and transport feedback.

These are deliberately mostly headless: the behaviour is assembled across the
M3U profile, the generic action host and the shared field, so pinning that
contract should not require a video-capable QML scene.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from core.app import AppController, ModeList
from modes import local, m3u

ROOT = Path(__file__).resolve().parent.parent


def _controller(active_mode: str, context):
    """A minimal controller whose active context follows the normal protocol."""
    engine = MagicMock()
    settings = MagicMock()
    settings.get.return_value = active_mode
    controller = AppController(
        engine,
        settings,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    controller.register_context(active_mode, context)
    return controller


class _NamedChannelContext:
    """Small stand-in for the M3U context's generic playback protocol."""

    def __init__(self, accepted: bool = True, label: str = "BBC News") -> None:
        self.accepted = accepted
        self.label = label
        self.next_calls = 0
        self.previous_calls = 0

    def play_next(self) -> bool:
        self.next_calls += 1
        return self.accepted

    def play_previous(self) -> bool:
        self.previous_calls += 1
        return self.accepted

    def current_playback_label(self) -> str:
        return self.label


def test_m3u_enables_toasts_without_enabling_local_right_dock() -> None:
    """Transport feedback and the Info/EQ dock are independent capabilities."""
    assert m3u.SPEC.osd_enabled is True
    assert m3u.SPEC.right_dock_enabled is False
    assert local.SPEC.osd_enabled is True
    assert local.SPEC.right_dock_enabled is True

    qml_spec = ModeList().spec("m3u")
    assert qml_spec["osdEnabled"] is True
    assert qml_spec["rightDockEnabled"] is False


def test_controller_reports_channel_navigation_and_friendly_name() -> None:
    context = _NamedChannelContext()
    controller = _controller("m3u", context)

    assert controller.next() is True
    assert context.next_calls == 1
    assert controller.previous() is True
    assert context.previous_calls == 1
    assert controller.currentPlaybackLabel() == "BBC News"


def test_controller_stays_quiet_when_navigation_is_not_accepted() -> None:
    context = _NamedChannelContext(accepted=False)
    controller = _controller("m3u", context)

    assert controller.next() is False
    assert controller.previous() is False


def test_m3u_filter_uses_shared_one_click_clear_control() -> None:
    panel = (ROOT / "modes" / "m3u" / "M3UPanel.qml").read_text(encoding="utf-8")
    field = (ROOT / "ui" / "components" / "GlassField.qml").read_text(encoding="utf-8")
    playlist = (ROOT / "modes" / "m3u" / "playlist.py").read_text(encoding="utf-8")

    assert "clearable: true" in panel
    assert 'clearTooltip: "Clear filter"' in panel
    assert "property bool clearable: false" in field
    assert "root.text = \"\";" in field
    assert "Glyphs.cancel" in field
    assert "def current_playback_label(self) -> str:" in playlist


def test_action_host_has_text_toasts_for_requested_m3u_controls() -> None:
    main = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")

    # Play/pause, next/previous, volume/mute and fullscreen all route through
    # one host, so buttons and their matching hotkeys receive the same feedback.
    for text in (
        '"Playing"',
        '"Paused"',
        '"Next"',
        '"Previous"',
        '"Volume "',
        '"Muted"',
        '"Unmuted"',
        '"Fullscreen"',
        '"Exit fullscreen"',
    ):
        assert text in main
