"""Tests for the rewritten Clear Browsing Data flow (§4.1).

The rewrite removed the time-range dropdown entirely: every clear is
"all time" via WebView2's one-argument ``ClearBrowsingDataAsync(kinds)``.
The profile comes from a LIVE tab's ``CoreWebView2.Profile`` — the
environment has no profile, which is why the old code silently cleared
nothing.

These tests verify:
  * the click path still opens the dialog from the bookmarks dropdown;
  * the dialog layout: 8 checkbox rows, Cancel + Clear, NO dropdown;
  * the Clear button maps the ticked rows onto the browser slot;
  * the browser slot pulls the profile from a live tab and calls the
    runtime all-time clear with exactly the ticked options;
  * the runtime combines option ids into one flag mask, calls
    ClearBrowsingDataAsync once, and wipes cache folders when ticked;
  * the cache-size probe and the live "will be cleared" line.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import GUI_AVAILABLE, ROOT

pytestmark = pytest.mark.skipif(
    not GUI_AVAILABLE, reason="QtGui/QML unavailable in this environment"
)

if GUI_AVAILABLE:
    from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
    from PySide6.QtTest import QTest

from modes.web import webview2_runtime
from modes.web.bookmarks import BookmarksStore
from modes.web.browser import BrowserContext

CLEAR_BUTTON_TEXT = "Clear browsing data"


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
def _build_bar(gui_app, tmp_path: Path):
    from PySide6.QtQml import QQmlComponent, QQmlEngine

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
    from PySide6.QtQml import QQmlComponent, QQmlEngine

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


def _show_in_window(gui_app, bar, browser):
    # The AddressBar is an Item; host it in a real window via QQuickView so
    # popups have a proper Window.window to anchor to, exactly like the app.
    from PySide6.QtQuick import QQuickView

    view = QQuickView()
    view.engine().addImportPath(str(ROOT))
    view.rootContext().setContextProperty("modeContext_web", browser)
    view.setSource(QUrl.fromLocalFile(str(ROOT / "modes" / "web" / "AddressBar.qml")))
    assert view.rootObject() is not None, "AddressBar did not build inside QQuickView"
    view.resize(1000, 700)
    view.show()
    QTest.qWait(50)
    return view, view.rootObject()


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


def _attach_fake_live_tab(browser: BrowserContext):
    """Give the browser one tab whose host exposes a fake WebView2 profile."""
    browser.addTab("https://example.com")
    tab = browser._tabs[0]
    tab.host = SimpleNamespace(webview=SimpleNamespace(Profile=SimpleNamespace(name="fake")))
    return tab.host.webview.Profile


# ---------------------------------------------------------------------------
# the click path — regression for the dialog that never opened
# ---------------------------------------------------------------------------
def test_clear_button_in_dropdown_opens_the_dialog(gui_app, tmp_path: Path):
    bar, browser = _build_bar(gui_app, tmp_path)
    assert browser.addBookmark("Example", "https://example.com")
    _view, bar = _show_in_window(gui_app, bar, browser)

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
    assert dialog.property("visible") is True, "Clear Browsing Data dialog did not open"

    bar.deleteLater()


# ---------------------------------------------------------------------------
# layout: 8 checkbox rows, Cancel + Clear buttons, NO time-range dropdown
# ---------------------------------------------------------------------------
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


def test_dialog_layout_has_eight_checkboxes_no_dropdown(gui_app, tmp_path: Path):
    dialog, _browser = _build_dialog(gui_app, tmp_path)

    rows = _checkbox_rows(dialog)
    assert set(rows) == set(SPEC_OPTIONS), f"expected the eight options, got {set(rows)}"
    for option_id, (label, default_tick, destructive) in SPEC_OPTIONS.items():
        row = rows[option_id]
        assert str(row.property("label")) == label
        assert bool(row.property("checked")) is default_tick
        assert bool(row.property("destructive")) is destructive

    # No time-range dropdown in the rewritten dialog.
    assert not _children_matching(dialog, "ComboBox"), "dialog must have no dropdown"
    assert dialog.property("timeRanges") is None, "old timeRanges property must be gone"

    # Both footer buttons exist.
    assert _button_with(dialog, "text", "Cancel")
    assert _button_with(dialog, "text", "Clear")

    dialog.deleteLater()


# ---------------------------------------------------------------------------
# Clear maps the ticked rows onto the browser slot (all time, no minutes)
# ---------------------------------------------------------------------------
def test_clear_maps_ticked_options_to_browser_slot(gui_app, tmp_path: Path, monkeypatch):
    captured: dict = {}

    def fake_clear(profile, options, *, wipe_folders=True):  # noqa: ARG001
        captured["profile"] = profile
        captured["options"] = list(options)

    monkeypatch.setattr(webview2_runtime, "clear_browsing_data_all", fake_clear)

    dialog, browser = _build_dialog(gui_app, tmp_path)
    profile = _attach_fake_live_tab(browser)

    rows = _checkbox_rows(dialog)
    # Deviate from defaults: drop cookies, add passwords, keep history + cache.
    rows["cookies"].setProperty("checked", False)
    rows["passwords"].setProperty("checked", True)

    dialog.setProperty("visible", True)  # triggers onVisibleChanged -> cache probe
    assert dialog.property("cacheBytes") is not None

    from PySide6.QtCore import QMetaObject

    assert QMetaObject.invokeMethod(dialog, "clearData")
    QTest.qWait(30)

    assert captured["profile"] is profile, "slot must pass the live tab's profile"
    assert captured["options"] == ["browsingHistory", "cache", "passwords"]
    assert dialog.property("visible") is False, "dialog hides itself after Clear"

    dialog.deleteLater()


# ---------------------------------------------------------------------------
# browser slot: profile comes from a live tab; none available -> no call
# ---------------------------------------------------------------------------
def test_browser_slot_pulls_profile_from_live_tab(gui_app, tmp_path: Path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        webview2_runtime,
        "clear_browsing_data_all",
        lambda profile, options, *, wipe_folders=True: captured.update(
            profile=profile, options=list(options)
        ),
    )

    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    assert browser._live_profile() is None, "no tabs -> no profile"

    profile = _attach_fake_live_tab(browser)
    assert browser._live_profile() is profile

    browser.clearBrowsingDataAll(["cache", "cookies"])
    assert captured["profile"] is profile
    assert captured["options"] == ["cache", "cookies"]


def test_browser_slot_without_live_tab_does_not_call_runtime(
    gui_app, tmp_path: Path, monkeypatch
):
    called = []
    monkeypatch.setattr(
        webview2_runtime,
        "clear_browsing_data_all",
        lambda *a, **k: called.append(a),
    )
    browser = BrowserContext(bookmarks=BookmarksStore(path=tmp_path / "bookmarks.json"))
    browser.clearBrowsingDataAll(["cache"])
    assert called == [], "no live profile -> must not call the runtime"


# ---------------------------------------------------------------------------
# runtime: one all-time SDK call with combined flags + cache folder wipe
# ---------------------------------------------------------------------------
class _FakeProfile:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def ClearBrowsingDataAsync(self, kinds: int):
        self.calls.append(int(kinds))
        return "task"


def _monkeypatch_kinds(monkeypatch):
    """Pin the flag table so tests can assert exact bit masks (official values)."""
    monkeypatch.setattr(webview2_runtime, "_kind_flags", lambda: {
        "browsingHistory": 4096,
        "downloadHistory": 512,
        "cookies": 64 | 32,
        "cache": 256,
        "passwords": 2048,
        "autofill": 1024,
        "sitePermissions": 8192,
        "serviceWorkers": 32768,
    })


def test_kind_flags_match_official_webview2_enum_values():
    """The flag table must equal Microsoft's documented enum values.

    This holds in BOTH branches: with the real bridge (Windows) and with the
    fallback table (this sandbox).  If either drifts from the SDK, clearing
    would silently hit the wrong data kinds.
    """
    flags = webview2_runtime._kind_flags()
    assert flags["browsingHistory"] == 4096      # BrowsingHistory
    assert flags["downloadHistory"] == 512       # DownloadHistory
    assert flags["cookies"] == 64 | 32           # Cookies | AllDomStorage
    assert flags["cache"] == 256                 # DiskCache
    assert flags["passwords"] == 2048            # PasswordAutosave
    assert flags["autofill"] == 1024             # GeneralAutofill
    assert flags["sitePermissions"] == 8192      # Settings (site permissions)
    assert flags["serviceWorkers"] == 32768      # ServiceWorkers


def test_runtime_clear_calls_sdk_once_with_combined_flags(monkeypatch):
    _monkeypatch_kinds(monkeypatch)
    monkeypatch.setattr(webview2_runtime, "_wait_for_task", lambda task, timeout_s=25: None)
    wiped = []
    monkeypatch.setattr(webview2_runtime, "_delete_cache_directories", lambda: wiped.append(1))

    profile = _FakeProfile()
    ok = webview2_runtime.clear_browsing_data_all(
        profile, ["browsingHistory", "cookies", "cache", "passwords"]
    )

    assert ok is True
    expected = 4096 | (64 | 32) | 256 | 2048  # official enum values
    assert profile.calls == [expected], "one call, flags OR-ed together"
    assert wiped == [1], "cache ticked -> folders wiped after the SDK call"


def test_runtime_clear_skips_folder_wipe_when_cache_not_ticked(monkeypatch):
    _monkeypatch_kinds(monkeypatch)
    monkeypatch.setattr(webview2_runtime, "_wait_for_task", lambda task, timeout_s=25: None)
    wiped = []
    monkeypatch.setattr(webview2_runtime, "_delete_cache_directories", lambda: wiped.append(1))

    profile = _FakeProfile()
    ok = webview2_runtime.clear_browsing_data_all(profile, ["passwords"])

    assert ok is True
    assert profile.calls == [2048]
    assert wiped == [], "no cache row -> no folder wipe"


def test_runtime_clear_returns_false_for_no_profile_or_empty_options(monkeypatch):
    called = []
    monkeypatch.setattr(
        webview2_runtime, "_wait_for_task", lambda task, timeout_s=25: called.append(1)
    )
    assert webview2_runtime.clear_browsing_data_all(None, ["cache"]) is False
    assert webview2_runtime.clear_browsing_data_all(_FakeProfile(), []) is False
    assert called == [], "no SDK call must be made"


def test_runtime_clear_survives_sdk_failure_and_still_wipes_cache(monkeypatch):
    _monkeypatch_kinds(monkeypatch)
    wiped = []
    monkeypatch.setattr(webview2_runtime, "_delete_cache_directories", lambda: wiped.append(1))

    class _BrokenProfile:
        def ClearBrowsingDataAsync(self, kinds):  # noqa: ARG002
            raise RuntimeError("sdk exploded")

    ok = webview2_runtime.clear_browsing_data_all(_BrokenProfile(), ["cache"])
    assert ok is False
    assert wiped == [1], "cache wipe is independent of the SDK call"


# ---------------------------------------------------------------------------
# full chain: QML checkboxes -> browser slot -> runtime -> one SDK call
# ---------------------------------------------------------------------------
def test_full_chain_qml_to_sdk_call(gui_app, tmp_path: Path, monkeypatch):
    """The whole path in one test: ticked rows in the QML end up as exactly
    one ClearBrowsingDataAsync call with the OR-ed official flags."""
    _monkeypatch_kinds(monkeypatch)
    monkeypatch.setattr(webview2_runtime, "_wait_for_task", lambda task, timeout_s=25: None)
    wiped = []
    monkeypatch.setattr(webview2_runtime, "_delete_cache_directories", lambda: wiped.append(1))

    class _P:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def ClearBrowsingDataAsync(self, kinds: int):
            self.calls.append(int(kinds))
            return "task"

    from PySide6.QtCore import QMetaObject

    dialog, browser = _build_dialog(gui_app, tmp_path)
    browser.addTab("https://example.com")
    browser._tabs[0].host = SimpleNamespace(webview=SimpleNamespace(Profile=_P()))
    fake_profile = browser._tabs[0].host.webview.Profile

    rows = _checkbox_rows(dialog)
    # Defaults are history + cookies + cache ticked.  Untick cookies, tick
    # passwords -> expected kinds: BrowsingHistory | DiskCache | PasswordAutosave.
    rows["cookies"].setProperty("checked", False)
    rows["passwords"].setProperty("checked", True)

    dialog.setProperty("visible", True)
    assert QMetaObject.invokeMethod(dialog, "clearData")
    QTest.qWait(30)

    assert fake_profile.calls == [4096 | 256 | 2048]
    assert wiped == [1], "cache ticked -> folder wipe ran after the SDK call"


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


def test_delete_cache_directories_removes_cache_folders(tmp_path: Path, monkeypatch):
    profile = _make_fake_profile(tmp_path)
    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: profile)

    webview2_runtime._delete_cache_directories()

    assert not (profile / "Default" / "Code Cache").exists()
    assert not (profile / "Default" / "Service Worker" / "CacheStorage").exists()
    # Local Storage is not a cache — never touched.
    assert (profile / "Local Storage" / "site.json").exists()
    assert webview2_runtime.get_cache_size_bytes() == 0


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
    assert "less than 1 MB" in str(freed.property("text"))

    rows = _checkbox_rows(dialog)
    rows["cache"].setProperty("checked", False)
    QTest.qWait(30)
    assert freed.property("visible") is False, "unticking cache hides the estimate"

    rows["cache"].setProperty("checked", True)
    QTest.qWait(30)
    assert freed.property("visible") is True, "re-ticking cache restores the estimate"

    dialog.deleteLater()


# ---------------------------------------------------------------------------
# END-TO-END: real QML + real button click + real slot + real runtime,
# against a faithful fake of the WebView2 SDK (official enum values).
# ---------------------------------------------------------------------------
def _install_fake_webview2_sdk(monkeypatch):
    """Register a realistic Microsoft.Web.WebView2.Core in sys.modules.

    Mirrors the real SDK: CoreWebView2BrowsingDataKinds with Microsoft's
    documented member values.  Lets the runtime's REAL try-branch (not the
    fallback table) run end-to-end.
    """
    import enum
    import sys
    import types

    class CoreWebView2BrowsingDataKinds(enum.IntFlag):
        FileSystems = 1
        IndexedDb = 2
        LocalStorage = 4
        WebSql = 8
        CacheStorage = 16
        AllDomStorage = 32
        Cookies = 64
        AllSite = 128
        DiskCache = 256
        DownloadHistory = 512
        GeneralAutofill = 1024
        PasswordAutosave = 2048
        BrowsingHistory = 4096
        Settings = 8192
        AllProfile = 16384
        ServiceWorkers = 32768

    core = types.ModuleType("Microsoft.Web.WebView2.Core")
    core.CoreWebView2BrowsingDataKinds = CoreWebView2BrowsingDataKinds

    def _ensure(pkg_name, parent=None):
        mod = sys.modules.get(pkg_name)
        if mod is None:
            mod = types.ModuleType(pkg_name)
            sys.modules[pkg_name] = mod
        if parent is not None:
            leaf = pkg_name.rsplit(".", 1)[-1]
            setattr(parent, leaf, mod)
        return mod

    m = _ensure("Microsoft")
    w = _ensure("Microsoft.Web", m)
    v = _ensure("Microsoft.Web.WebView2", w)
    _ensure("Microsoft.Web.WebView2.Core", v)

    return CoreWebView2BrowsingDataKinds


class _E2EProfile:
    """Faithful stand-in for CoreWebView2Profile: records ClearBrowsingDataAsync."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def ClearBrowsingDataAsync(self, kinds):
        self.calls.append(int(kinds))
        return "fake-task"


def test_end_to_end_click_clear_in_real_dialog(gui_app, tmp_path: Path, monkeypatch):
    """The whole flow as a user drives it.

    Real SDK enum (official values) -> real dialog -> real Clear button click
    -> real browser slot -> real runtime -> ONE ClearBrowsingDataAsync call
    with the exact OR-ed official flags -> cache folders physically wiped ->
    size probe re-reads disk -> reopening the dialog shows 0 MB.
    """
    import sys as _sys

    K = _install_fake_webview2_sdk(monkeypatch)
    # Pumping Qt events is the only production step we cannot run headless;
    # the .NET task completion is what it waits for.
    monkeypatch.setattr(webview2_runtime, "_wait_for_task", lambda task, timeout_s=25: None)

    # Real profile on disk with cache + non-cache files, exactly like
    # %LOCALAPPDATA%/Halcyon/webview2_data after browsing.
    profile_dir = _make_fake_profile(tmp_path)
    monkeypatch.setattr(webview2_runtime, "get_user_data_dir", lambda: profile_dir)
    assert webview2_runtime.get_cache_size_bytes() == 400

    # Real dialog + real browser; attach the tab exactly as production does
    # (addTab -> _navigate_tab -> host with .webview, and webview.Profile is
    # the documented live source).
    dialog, browser = _build_dialog(gui_app, tmp_path)
    browser.addTab("https://example.com")
    tab = browser._tabs[0]
    fake_profile = _E2EProfile()
    tab.host = SimpleNamespace(webview=SimpleNamespace(Profile=fake_profile))

    dialog.setProperty("visible", True)
    QTest.qWait(30)
    assert float(dialog.property("cacheBytes")) == 400

    # Defaults: history + cookies + cache ticked.  Add passwords too.
    rows = _checkbox_rows(dialog)
    rows["passwords"].setProperty("checked", True)

    # The REAL Clear button (not invokeMethod): user click path.
    clear_button = _button_with(dialog, "text", "Clear")
    clear_button.clicked.emit()
    QTest.qWait(50)

    # 1) exactly one SDK call with the OR of the official enum values
    expected = int(K.BrowsingHistory | K.Cookies | K.AllDomStorage | K.DiskCache | K.PasswordAutosave)
    assert fake_profile.calls == [expected], f"got {fake_profile.calls}, want [{expected}]"

    # 2) dialog hides itself after clearing
    assert dialog.property("visible") is False

    # 3) cache folders physically gone; non-cache data untouched
    assert not (profile_dir / "Default" / "Code Cache").exists()
    assert not (profile_dir / "Default" / "Cache" / "Cache_Data" / "f_000001").exists()
    assert (profile_dir / "Local Storage" / "site.json").exists(), "non-cache must survive"

    # 4) disk re-probe now reports 0 — no stale 170 MB
    assert webview2_runtime.get_cache_size_bytes() == 0
    assert browser.cacheSizeBytes() == 0

    # 5) reopening the dialog re-probes and shows the real post-clear size:
    #    0 MB, not a stale 170 MB — and the line literally says "0 MB".
    dialog.setProperty("visible", True)
    QTest.qWait(30)
    assert float(dialog.property("cacheBytes")) == 0
    freed = _freed_space_text(dialog)
    assert freed is not None
    assert freed.property("visible") is True, "line stays while cache row is ticked"
    assert "0 MB will be cleared" in str(freed.property("text"))

    dialog.deleteLater()
    for name in list(_sys.modules):
        if name == "Microsoft" or name.startswith("Microsoft."):
            del _sys.modules[name]
