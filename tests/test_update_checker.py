"""Unit tests for core/update_checker.py — §U.

Tests version detection, online HTTP fetching with parsing/fallback, version
comparisons, asynchronous background thread execution, and cancellation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from core.update_checker import (
    VLC_KNOWN_LATEST,
    WEBVIEW2_KNOWN_LATEST,
    UpdateChecker,
)


@pytest.fixture
def app():
    """Ensure a QCoreApplication exists for Qt signals."""
    instance = QCoreApplication.instance()
    if instance is None:
        instance = QCoreApplication([])
    return instance


def test_parse_version_tuple():
    assert UpdateChecker._parse_version_tuple("3.0.21") == (3, 0, 21)
    assert UpdateChecker._parse_version_tuple("1.0.2903.40") == (1, 0, 2903, 40)
    assert UpdateChecker._parse_version_tuple("1.0.2903.40-prerelease") == (1, 0, 2903, 40)
    assert UpdateChecker._parse_version_tuple("3,0,23,0") == (3, 0, 23)
    assert UpdateChecker._parse_version_tuple("3,0,23,0") == UpdateChecker._parse_version_tuple("3.0.23")
    assert UpdateChecker._parse_version_tuple("Not found") == (0,)
    assert UpdateChecker._parse_version_tuple("") == (0,)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3,0,23,0", "3.0.23"),
        ("3.0.23.0", "3.0.23"),
        ("3.0.17.4", "3.0.17.4"),
        ("1.0.4129.50", "1.0.4129.50"),
        ("Not found", "Not found"),
    ],
)
def test_normalize_version(raw, expected):
    assert UpdateChecker._normalize_version(raw) == expected


def test_is_update_available():
    # Newer version available
    assert UpdateChecker._is_update_available("3.0.20", "3.0.21") is True
    assert UpdateChecker._is_update_available("1.0.2903", "1.0.2903.40") is True

    # Same version
    assert UpdateChecker._is_update_available("3.0.21", "3.0.21") is False
    assert UpdateChecker._is_update_available("1.0.2903.40", "1.0.2903.40") is False
    assert UpdateChecker._is_update_available("3,0,23,0", "3.0.23") is False
    assert UpdateChecker._is_update_available("3.0.23", "3,0,23,0") is False
    assert UpdateChecker._is_update_available("3.0.23.0", "3.0.23") is False

    # Current is newer
    assert UpdateChecker._is_update_available("3.0.22", "3.0.21") is False

    # Missing / Unknown current version
    assert UpdateChecker._is_update_available("Not found", "3.0.21") is True
    assert UpdateChecker._is_update_available("Unknown", "3.0.21") is True
    assert UpdateChecker._is_update_available("", "3.0.21") is True


def test_check_result_normalizes_display_versions(app):
    """Current/latest fields sent to QML use one canonical display format."""
    checker = UpdateChecker()

    with patch.object(checker, "_detect_vlc_version", return_value="3,0,23,0"), \
         patch.object(checker, "_detect_webview2_version", return_value="1.0.4129.50.0"), \
         patch.object(checker, "_fetch_online_vlc_version", return_value=("3.0.23", True)), \
         patch.object(checker, "_fetch_online_webview2_version", return_value=("1.0.4129.50", True)):
        checker.checkUpdates()
        if checker._worker_thread:
            checker._worker_thread.join(timeout=2.0)
        app.processEvents()

    result = checker.lastResult
    assert result["anyUpdate"] is False
    assert result["vlc"] == {
        "update": False,
        "current": "3.0.23",
        "latest": "3.0.23",
        "online": True,
    }
    assert result["webview2"] == {
        "update": False,
        "current": "1.0.4129.50",
        "latest": "1.0.4129.50",
        "online": True,
    }


def test_fetch_online_vlc_version_xml(app):
    checker = UpdateChecker()
    xml_data = b"<status><version>3.0.22</version></status>"

    with patch.object(checker, "_fetch_url", return_value=xml_data):
        ver, online = checker._fetch_online_vlc_version()
        assert ver == "3.0.22"
        assert online is True


def test_fetch_online_vlc_version_html(app):
    checker = UpdateChecker()
    html_data = b'<html><body><a href="3.0.19/">3.0.19/</a><a href="3.0.21/">3.0.21/</a><a href="3.0.22/">3.0.22/</a></body></html>'

    with patch.object(checker, "_fetch_url", return_value=html_data):
        ver, online = checker._fetch_online_vlc_version()
        assert ver == "3.0.22"
        assert online is True


def test_fetch_online_vlc_version_fallback(app):
    checker = UpdateChecker()

    with patch.object(checker, "_fetch_url", return_value=None):
        ver, online = checker._fetch_online_vlc_version()
        assert ver == VLC_KNOWN_LATEST
        assert online is False


def test_fetch_online_webview2_version_json(app):
    checker = UpdateChecker()
    nuget_data = json.dumps({
        "versions": ["1.0.2800.0", "1.0.2903.40", "1.0.3000.0-prerelease"]
    }).encode("utf-8")

    with patch.object(checker, "_fetch_url", return_value=nuget_data):
        ver, online = checker._fetch_online_webview2_version()
        assert ver == "1.0.2903.40"
        assert online is True


def test_fetch_online_webview2_version_fallback(app):
    checker = UpdateChecker()

    with patch.object(checker, "_fetch_url", return_value=None):
        ver, online = checker._fetch_online_webview2_version()
        assert ver == WEBVIEW2_KNOWN_LATEST
        assert online is False


def test_async_check_updates(app):
    checker = UpdateChecker()

    started_emitted = False
    results_received = []

    def on_started():
        nonlocal started_emitted
        started_emitted = True

    def on_finished(res):
        results_received.append(res)

    checker.checkStarted.connect(on_started)
    checker.checkFinished.connect(on_finished)

    def slow_vlc():
        time.sleep(0.05)
        return ("3.0.21", False)

    # Mock online fetching to be fast and offline
    with patch.object(checker, "_fetch_online_vlc_version", side_effect=slow_vlc), \
         patch.object(checker, "_fetch_online_webview2_version", return_value=("1.0.2903", False)):
        checker.checkUpdates()
        assert started_emitted is True

        # Wait for background thread to complete
        if checker._worker_thread:
            checker._worker_thread.join(timeout=2.0)

        # Process Qt events
        app.processEvents()

    assert checker.checking is False
    assert len(results_received) == 1
    assert "vlc" in results_received[0]
    assert "webview2" in results_received[0]


def test_cancel_check(app):
    checker = UpdateChecker()

    cancelled_emitted = False
    finished_emitted = False

    def on_cancelled():
        nonlocal cancelled_emitted
        cancelled_emitted = True

    def on_finished(res):
        nonlocal finished_emitted
        finished_emitted = True

    checker.checkCancelled.connect(on_cancelled)
    checker.checkFinished.connect(on_finished)

    # Slow down fetching so we can cancel mid-flight
    def slow_fetch_vlc():
        time.sleep(0.2)
        return ("3.0.21", False)

    with patch.object(checker, "_fetch_online_vlc_version", side_effect=slow_fetch_vlc):
        checker.checkUpdates()
        assert checker.checking is True

        # Cancel immediately
        checker.cancelCheck()
        assert checker.checking is False
        assert cancelled_emitted is True

        if checker._worker_thread:
            checker._worker_thread.join(timeout=2.0)

        app.processEvents()

    # Verify checkFinished was NOT emitted when cancelled
    assert finished_emitted is False
