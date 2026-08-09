"""Regression checks for the phone remote's Web media controls."""

from __future__ import annotations

from pathlib import Path


APP_JS = Path(__file__).resolve().parent.parent / "remote" / "static" / "app.js"


def test_web_volume_is_sent_while_slider_is_moving():
    """Web volume must not wait for the range input's final change event."""
    source = APP_JS.read_text(encoding="utf-8")

    assert "requestAnimationFrame" in source
    assert "sendWebVolume(v, false);" in source
    assert "sendWebVolume(Number(e.target.value) / 100, true);" in source


def test_local_remote_volume_is_sent_while_slider_is_moving():
    """Local remote volume must also receive intermediate slider values."""
    source = APP_JS.read_text(encoding="utf-8")

    assert '$(sliderId).addEventListener("input"' in source
    assert "sendPlayerVolume(e.target.value, false);" in source
    assert "sendPlayerVolume(e.target.value, true);" in source
