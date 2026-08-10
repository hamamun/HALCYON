"""Regression checks for Web being a browser-only mode, not an empty player UI."""

from __future__ import annotations

from pathlib import Path

from core.app import ModeList

ROOT = Path(__file__).resolve().parent.parent


def test_mode_spec_exports_the_two_generic_web_shell_capabilities():
    """A ModeSpec flag is useless unless QML receives it in Modes.spec()."""
    web = ModeList().spec("web")
    assert web["panelEnabled"] is False
    assert web["keepStageAlive"] is True


def test_main_gates_left_panel_and_ctrl_l_by_mode_capability():
    source = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")

    assert "function leftPanelAvailable()" in source
    assert "modeSpec.panelEnabled" in source
    assert "if (!window.leftPanelAvailable()) return;" in source
    assert "window.leftPanelOpen && window.leftPanelAvailable()" in source
    assert "source: window.leftPanelAvailable() && window.modeSpec" in source


def test_web_has_no_transport_loader_or_bottom_inset():
    source = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")

    assert "readonly property bool hasTransport:" in source
    assert "active: body.hasTransport" in source
    assert "visible: body.hasTransport && opacity > 0" in source
    assert "visible: window.usesPlayer() && window.fullscreen" in source


def test_stage_parks_only_opt_in_mode_and_notifies_native_web_stage():
    source = (ROOT / "ui" / "shell" / "Stage.qml").read_text(encoding="utf-8")

    assert "modelData.keepStageAlive && wasActivated" in source
    assert "stageLoader.item.stageActive = active" in source
    assert "visible: isCurrent" in source


def test_web_stage_attaches_real_page_area_and_has_no_hardcoded_missing_runtime():
    source = (ROOT / "modes" / "web" / "WebStage.qml").read_text(encoding="utf-8")

    assert "browser.attachToWindow(hostWindow)" in source
    assert "var viewportItem = contentFullscreen ? webStage : pageArea" in source
    assert "browser.setViewport(" in source
    assert "browser.setStageActive(stageActive)" in source
    assert "stageActive: webStage.stageActive" in source
    assert "setHostWindowFullscreen(true)" in source
    assert "visible: !webStage.contentFullscreen" in source
    assert "property bool isRuntimeMissing: true" not in source
    assert "WebView2 is not available" in source


def test_browser_popups_are_native_windows_and_manager_supports_drag_reorder():
    popup = (ROOT / "modes" / "web" / "BrowserPopup.qml").read_text(encoding="utf-8")
    manager = (ROOT / "modes" / "web" / "BookmarksManagerTab.qml").read_text(encoding="utf-8")

    assert "property bool stageActive: true" in popup
    assert "onStageActiveChanged: if (!stageActive) hidePopup()" in popup
    assert "!stageActive || !anchorItem.visible" in popup
    assert "acceptsFocus" in popup
    # Focus-taking popups (bookmark dialogs) stay native Qt.Popup windows;
    # autocomplete-style popups (suggestions) are tooltip-style so they can
    # never steal typing focus from the address bar.
    assert "? Qt.Popup | Qt.FramelessWindowHint" in popup
    assert "Qt.ToolTip | Qt.FramelessWindowHint" in popup
    assert "mapToGlobal" in popup
    assert "DragHandler" in manager
    assert "reorderBookmarks(fromIndex, targetIndex)" in manager


def test_window_title_uses_generic_active_mode_title_protocol():
    source = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")
    controller = (ROOT / "core" / "app.py").read_text(encoding="utf-8")

    assert "App.modeWindowTitle" in source
    assert "def modeWindowTitle" in controller
    assert "windowTitleChanged" in controller


def test_browser_context_creates_and_initializes_hosts_for_external_tabs():
    source = (ROOT / "modes" / "web" / "browser.py").read_text(encoding="utf-8")

    assert "tab.host = self._host_factory" in source
    assert "host.init_controller(self._parent_hwnd, environment)" in source
    assert "host.newWindowRequested.connect(self.onPopupRequested)" in source
    assert "fullscreenChanged" in source
    assert "def _on_host_fullscreen" in source
    assert "host.set_visible(should_show and host.isReady)" in source
