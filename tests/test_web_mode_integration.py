"""Integration tests for Phase 3 — Web mode registration and capability rules (§P3.3, §P3.6)."""

from __future__ import annotations

from unittest.mock import MagicMock

from core import modes
from core.app import AppController
from modes.web import SPEC, build_web_context
from modes.web.browser import BrowserContext


def test_web_mode_registration_in_registry():
    """Verify Web mode is registered as the third mode in REGISTRY (§P3.3)."""
    ids = modes.mode_ids()
    assert ids == ["local", "m3u", "web"]
    web_spec = modes.get("web")
    assert web_spec.id == "web"
    assert web_spec.title == "Web"


def test_web_mode_spec_flags():
    """Verify ModeSpec capability flags for Web mode (§P3.1, §P3.3)."""
    assert SPEC.panel_enabled is False, "Web mode hides left dock entirely"
    assert SPEC.keep_stage_alive is True, "Web mode stage parked on switch"
    assert SPEC.uses_player is False, "Web mode does not drive libVLC"
    assert SPEC.transport_qml == "", "No bottom bar in Web mode"
    assert SPEC.osd_enabled is False, "No media OSD in Web mode"
    assert SPEC.right_dock_enabled is False, "No right Info/EQ dock in Web mode"
    assert SPEC.media_keys_enabled is False, "Media hotkeys inert in Web mode"


def test_web_mode_setup_hook_returns_browser_context():
    """Setup hook must return BrowserContext published as modeContext_web (§P3.3)."""
    ctx = build_web_context(None, None, None)
    assert isinstance(ctx, BrowserContext)


def test_web_page_title_flows_through_mode_neutral_window_title_protocol():
    mock_engine = MagicMock()
    mock_settings = MagicMock()
    mock_settings.get.return_value = "local"
    app = AppController(
        mock_engine, mock_settings, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    browser = BrowserContext()
    app.register_context("web", browser)
    browser.navigateActive("example.com")
    app.setActiveMode("web")

    assert app.modeWindowTitle == "https://example.com"
    browser._on_host_title(browser.activeTab["id"], "Example")
    assert app.modeWindowTitle == "Example"


def test_web_mode_switch_stops_player_one_tuner():
    """Switching to Web mode must stop video playback cleanly (§P3.3 one-tuner rule)."""
    mock_engine = MagicMock()
    mock_engine.state = 3  # Playing
    mock_settings = MagicMock()
    mock_settings.get.return_value = "local"
    mock_library = MagicMock()
    mock_metadata = MagicMock()
    mock_lyrics = MagicMock()
    mock_eq = MagicMock()

    app = AppController(
        mock_engine, mock_settings, mock_library, mock_metadata, mock_lyrics, mock_eq
    )
    app.setActiveMode("web")

    mock_engine.stop.assert_called_once()
    mock_metadata.load.assert_called_with("")
    mock_lyrics.load.assert_called_with("")


def test_switch_away_from_web_mode_pauses_web_media():
    """Switching away from Web mode must pause web media (§P3.3 one-tuner rule)."""
    mock_engine = MagicMock()
    mock_settings = MagicMock()
    mock_settings.get.return_value = "web"
    app = AppController(
        mock_engine, mock_settings, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    browser = BrowserContext(controller=app)
    browser.pauseMedia = MagicMock()
    app.register_context("web", browser)
    assert app.activeMode == "web"

    app.setActiveMode("local")
    browser.pauseMedia.assert_called_once()
