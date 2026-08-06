"""End-to-end tests for the Clear Browsing Data flow (§4.1).

Guards the exact failure the owner hit on Windows: clicking "Clear browsing
data" in the bookmarks dropdown printed

    QML BookmarksDropdown: Window.window does only support types deriving
    from Item

to the terminal and nothing opened.  BookmarksDropdown is a popup *Window*,
so ``root.Window.window`` is invalid there; the dialog must be opened with
the main-window anchor and owner remembered from ``openFor()``.

These tests instantiate the real QML (AddressBar → BookmarksDropdown →
ClearBrowsingDataDialog) without Windows/WebView2 and verify:
  * the click path actually opens the dialog window (parented to the main
    window) and no QML error is emitted while doing so;
  * the dialog matches the §4.1 spec: five time ranges defaulting to
    "Last 24 hours", the eight options with exactly three pre-ticked
    (history, cookies, cache), danger cues on destructive rows;
  * Clear maps the ticked boxes and time range onto the backend call;
  * the cache-size probe and the live "will be cleared" line.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtTest import QTest

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtCore import Qt, QMetaObject
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem, QQuickWindow

from modes.web import webview2_runtime
from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext

CLEAR_BUTTON_TEXT = "Clear browsing data"


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
def _build_bar(gui_app, tmp_path: Path):
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "AddressBar.qml"))
    )
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    bar = component.create()
    assert bar is not None, "\n".join(e.toString() for e in component.errors())
    bar._refs = (engine, component, browser)
    return bar, browser


def _build_dialog(gui_app, tmp_path: Path, browser: BrowserContext | None = None):
    engine = QQmlEngine()
    engine.addImportPath(str(ROOT))
    if browser is None:
        browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    engine.rootContext().setContextProperty("modeContext_web", browser)
    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "ClearBrowsingDataDialog.qml"))
    )
    assert not component.isError(), "\n".join(e.toString() for e in component.errors())
    dialog = component.create()
    assert dialog is not None, "\n".join(e.toString() for e in component.errors())
    dialog._refs = (engine, component, browser)
    dialog.setProperty("browser", browser)
    return dialog, browser


def _show_in_window(gui_app, bar: QQuickItem, browser: BrowserContext) -> QQuickWindow:
    window = QQuickWindow()
    bar.setParentItem(window.contentItem())
    bar.setProperty("browser", browser)
    bar.setProperty("width", 900)
    bar.setProperty("height", 48)
    window.resize(1000, 700)
    window.show()
    QTest.qWait(50)
    return window


def _children_matching(root: QObject, class_fragment: str) -> list[QObject]:
    return [
        o
        for o in root.findChildren(QObject)
        if class_fragment in o.metaObject().className()
    ]


def _child_matching(root: QObject, class_fragment: str) -> QObject:
    matches = _children_matching(root, class_fragment)
    assert matches, f"no child matching {class_fragment!r}"
    return matches[0]


def _button_with(root: QObject, prop: str, value: str) -> QObject:
    for fragment in ("IconButton", "TextButton", "AbstractButton"):
        for obj in _children_matching(root, fragment):
            if str(obj.property(prop) or "") == value:
                return obj
    raise AssertionError(f"no button with {prop}={value!r}")


def _checkbox_rows(dialog: QObject) -> dict[str, QObject]:
    rows = {}
    for row in _children_matching(dialog, "CheckBoxRow"):
        rows[str(row.property("optionId"))] = row
    return rows


def _freed_space_text(dialog: QObject) -> QObject | None:
    for obj in _children_matching(dialog, "QQuickText"):
        text = str(obj.property("text") or "")
        if "will be cleared" in text:
            return obj
    return None


# ---------------------------------------------------------------------------
# the click path — regression for the dialog that never opened
# ---------------------------------------------------------------------------
def test_clear_button_in_dropdown_opens_the_dialog(gui_app, tmp_path: Path):
    from PySide6.QtCore import qInstallMessageHandler

    bar, browser = _build_bar(gui_app, tmp_path)
    assert browser.addBookmark("Example", "https://example.com")
    window = _show_in_window(gui_app, bar, browser)

    qml_errors: list[str] = []

    def _collect(mode, context, message):  # noqa: ANN001 - Qt signature
        text = str(message)
        if "does only support types" in text or "Window.window" in text:
            qml_errors.append(text)

    previous_handler = qInstallMessageHandler(_collect)
    try:
        # Step 1 — open the bookmarks dropdown from the ⋯ menu button.
        menu_button = _button_with(bar, "tooltip", "Bookmarks")
        menu_button.clicked.emit()
        QTest.qWait(120)

        dropdown = _child_matching(bar, "BookmarksDropdown")
        assert dropdown.property("visible") is True, "bookmarks dropdown did not open"

        # Step 2 — click 'Clear browsing data' inside the dropdown.
        clear_button = _button_with(bar, "text", CLEAR_BUTTON_TEXT)
        clear_button.clicked.emit()
        QTest.qWait(300)
    finally:
        qInstallMessageHandler(previous_handler)

    assert not qml_errors, "QML errors while opening the dialog:\n" + "\n".join(qml_errors)
    assert dropdown.property("visible") is False, "dropdown should close when Clear opens"

    dialog = _child_matching(bar, "ClearBrowsingDataDialog")
    assert dialog.property("visible") is True, (
        "Clear Browsing Data dialog did not open — the owner reported exactly "
        "this: the button printed a terminal error and nothing happened"
    )
    # The dialog must hang off the MAIN window, never the hidden dropdown popup.
    transient_parent = dialog.property("transientParent")
    assert transient_parent == window, "dialog must be transient-parented to the main window"

    bar.deleteLater()


# ---------------------------------------------------------------------------
# the §4.1 spec: time ranges, options, defaults, danger cues
# ---------------------------------------------------------------------------
SPEC_TIME_RANGES = ["Last hour", "Last 24 hours", "Last 7 days", "Last 4 weeks", "All time"]
SPEC_OPTIONS = {
    "browsingHistory": ("Browsing history", True, False),
    "downloadHistory": ("Download history", False, False),
    "cookies": ("Cookies and site data", True, True),
    "cache": ("Cached images and files", True, False),
    "passwords": ("Passwords", False, True),
    "autofill": ("Autofill form data", False, True),
    "sitePermissions": ("Site permissions", False, False),
    "serviceWorkers": ("Service workers and offline data", False, False),
}


def test_dialog_matches_spec(gui_app, tmp_path: Path):
    dialog, _browser = _build_dialog(gui_app, tmp_path)

    ranges = dialog.property("timeRanges").toVariant()
    assert [str(r["label"]) for r in ranges] == SPEC_TIME_RANGES
    assert [int(r["minutes"]) for r in ranges] == [60, 1440, 10080, 40320, 0]
    assert int(dialog.property("selectedRangeIndex")) == 1, "default must be 'Last 24 hours'"

    rows = _checkbox_rows(dialog)
    assert set(rows) == set(SPEC_OPTIONS), f"expected the eight spec options, got {set(rows)}"
    for option_id, (label, default_tick, destructive) in SPEC_OPTIONS.items():
        row = rows[option_id]
        assert str(row.property("label")) == label
        assert bool(row.property("checked")) is default_tick, (
            f"{option_id}: default tick must be {default_tick}"
        )
        assert bool(row.property("destructive")) is destructive
        if destructive:
            assert str(row.property("warning")), f"{option_id} needs a danger-cue warning line"
        else:
            assert str(row.property("warning")) == ""

    dialog.deleteLater()


def test_clear_maps_ticked_options_and_time_range(gui_app, tmp_path: Path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        webview2_runtime,
        "clear_browsing_data",
        lambda options, window: captured.update(options=list(options), window=window),
    )

    dialog, _browser = _build_dialog(gui_app, tmp_path)
    rows = _checkbox_rows(dialog)

    # Deviate from defaults: drop cookies, add passwords, keep history + cache.
    rows["cookies"].setProperty("checked", False)
    rows["passwords"].setProperty("checked", True)
    dialog.setProperty("selectedRangeIndex", 4)  # "All time"

    dialog.setProperty("visible", True)  # onVisibleChanged probes cache size
    assert QMetaObject.invokeMethod(dialog, "clearData")
    QTest.qWait(30)

    assert captured["options"] == ["browsingHistory", "cache", "passwords"]
    assert captured["window"] is None, "'All time' must clear with window=None"
    assert dialog.property("visible") is False, "dialog hides itself after Clear"

    dialog.deleteLater()


# ---------------------------------------------------------------------------
# freed-space line + cache probe
# ---------------------------------------------------------------------------
def _make_fake_profile(base: Path) -> Path:
    profile = base / "webview2_data"
    (profile / "Default" / "Cache" / "Cache_Data").mkdir(parents=True)
    (profile / "Default" / "Code Cache").mkdir(parents=True)
    (profile / "Default" / "Service Worker" / "CacheStorage" / "https_example.com").mkdir(
        parents=True
    )
    (profile / "Local Storage").mkdir(parents=True)

    def _write(rel: str, size: int) -> None:
        path = profile / rel
        path.write_bytes(b"x" * size)

    _write("Default/Cache/Cache_Data/f_000001", 100)
    _write("Default/Cache/Cache_Data/f_000002", 200)
    _write("Default/Code Cache/js.bin", 40)
    _write("Default/Service Worker/CacheStorage/https_example.com/index", 25)
    _write("Default/Service Worker/CacheStorage/https_example.com/body", 35)
    # Not a cache — must never count.
    _write("Local Storage/site.json", 999)
    return profile


def test_cache_size_probe_sums_only_cache_dirs(tmp_path: Path, monkeypatch):
    profile = _make_fake_profile(tmp_path)
    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: profile)
    assert webview2_runtime.get_cache_size_bytes() == 400

    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: tmp_path / "missing")
    assert webview2_runtime.get_cache_size_bytes() == 0


def test_browser_context_cache_size_bytes(gui_app, tmp_path: Path, monkeypatch):
    profile = _make_fake_profile(tmp_path)
    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: profile)
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    assert browser.cacheSizeBytes() == 400


def test_freed_space_line_follows_the_cache_checkbox(gui_app, tmp_path: Path, monkeypatch):
    profile = _make_fake_profile(tmp_path)
    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: profile)

    dialog, browser = _build_dialog(gui_app, tmp_path)
    assert browser.cacheSizeBytes() == 400, "probe sanity"

    dialog.setProperty("visible", True)  # triggers refreshCacheSize()
    QTest.qWait(30)
    assert float(dialog.property("cacheBytes")) == 400

    freed = _freed_space_text(dialog)
    assert freed is not None, "dialog needs the 'will be cleared' line"
    assert freed.property("visible") is True, "cache is pre-ticked, so the line shows"
    assert "400" not in str(freed.property("text"))  # formatted, not raw bytes
    assert "less than 1 MB" in str(freed.property("text"))

    rows = _checkbox_rows(dialog)
    rows["cache"].setProperty("checked", False)
    QTest.qWait(30)
    assert freed.property("visible") is False, "unticking cache hides the estimate"

    rows["cache"].setProperty("checked", True)
    QTest.qWait(30)
    assert freed.property("visible") is True, "re-ticking cache restores the estimate"

    dialog.deleteLater()
