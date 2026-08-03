from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from modes.web.bookmarks import BookmarkModel, canonical_url, normalise_url
from modes.web.tabs import MAX_TABS, TabModel
from modes.web.webview2_host import WebContext


def _app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_web_mode_registered_after_m3u() -> None:
    from core import modes

    assert modes.mode_ids() == ["local", "m3u", "web"]
    spec = modes.get("web")
    assert spec.transport_qml == ""
    assert spec.panel_qml == ""
    assert spec.right_dock_enabled is False
    assert spec.osd_enabled is False
    assert spec.media_keys_enabled is False
    assert spec.uses_player is False


def test_tab_model_starts_empty_and_limits_to_15() -> None:
    _app()
    tabs = TabModel()
    reached = []
    tabs.limitReached.connect(lambda: reached.append(True))

    assert tabs.count == 0
    for i in range(MAX_TABS):
        assert tabs.openUrl(f"https://example{i}.com")
    assert tabs.count == MAX_TABS
    assert not tabs.openUrl("https://overflow.example")
    assert reached == [True]


def test_tabs_are_session_only_not_persisted(tmp_path: Path, monkeypatch) -> None:
    _app()
    monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path))
    first = WebContext()
    first.openNewTab("https://example.com")
    assert first.tabs.count == 1

    second = WebContext()
    assert second.tabs.count == 0


def test_bookmarks_persist_and_canonicalise(tmp_path: Path) -> None:
    _app()
    store = tmp_path / "bookmarks.json"
    model = BookmarkModel(store)
    original = model.totalCount
    assert model.addBookmark("Example", "example.com")
    assert model.totalCount == original + 1
    assert model.indexOfUrl("https://example.com/") >= 0

    again = BookmarkModel(store)
    assert again.indexOfUrl("example.com") >= 0


def test_url_normalisation() -> None:
    assert normalise_url("example.com") == "https://example.com"
    assert normalise_url("https://example.com/path") == "https://example.com/path"
    assert "bing.com/search" in normalise_url("halcyon browser")
    assert canonical_url("https://EXAMPLE.com/") == "https://example.com/"


def test_real_browser_state_updates_the_active_tab() -> None:
    _app()
    tabs = TabModel()
    assert tabs.openUrl("https://example.com")
    tab = tabs.active_tab()
    assert tab is not None

    # WebView2 reports titles and final redirect URLs asynchronously. Those
    # updates must change the existing history entry, not create a phantom tab
    # navigation for every redirect.
    tabs.set_web_state(tab, title="Example Domain", url="https://www.example.com/", loading=True)
    assert tabs.activeTitle == "Example Domain"
    assert tabs.activeUrl == "https://www.example.com/"
    assert tab.history == ["https://www.example.com/"]
    assert tab.loading


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _FakeWindow:
    def __init__(self, handles: list[int]) -> None:
        self._handles = list(handles)
        self.visibleChanged = _FakeSignal()

    def winId(self) -> int:  # noqa: N802 - mirrors Qt API
        if len(self._handles) > 1:
            return self._handles.pop(0)
        return self._handles[0]

    def devicePixelRatio(self) -> float:  # noqa: N802 - mirrors Qt API
        return 1.0


class _FakeNativeView:
    def __init__(self, ready: bool = True) -> None:
        self._ready = ready
        self.closed = False
        self.bounds = None
        self.visible = False
        self.navigated = []

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def can_go_back(self) -> bool:
        return False

    @property
    def can_go_forward(self) -> bool:
        return False

    def update_bounds(self, x: int, y: int, width: int, height: int) -> None:
        self.bounds = (x, y, width, height)

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def navigate(self, url: str) -> None:
        self.navigated.append(url)

    def go_back(self) -> None: pass
    def go_forward(self) -> None: pass
    def reload(self) -> None: pass
    def stop(self) -> None: pass

    def close(self) -> None:
        self.closed = True


def test_webview_creation_requeries_hwnd_and_waits_for_valid_handle(monkeypatch) -> None:
    _app()
    from modes.web import webview2_host

    ctx = WebContext()
    ctx._runtime_available = True
    created_for: list[int] = []

    monkeypatch.setattr(webview2_host, "_is_valid_hwnd", lambda hwnd: hwnd == 222)

    def create_webview(parent_hwnd, *_args, **_kwargs):
        created_for.append(parent_hwnd)
        return _FakeNativeView()

    monkeypatch.setattr(webview2_host.webview_integration, "create_webview", create_webview)

    ctx.openNewTab("https://example.com")
    ctx.attachWindow(_FakeWindow([111, 222, 222]))

    assert created_for == []
    assert ctx._webviews == {}

    ctx.setBrowserRect(0, 0, 640, 480, True)

    assert created_for == [222]
    assert ctx.nativeBrowserVisible is True


def test_not_ready_webview_slot_is_dropped_so_later_sync_retries(monkeypatch) -> None:
    _app()
    from modes.web import webview2_host

    ctx = WebContext()
    ctx._runtime_available = True
    first = _FakeNativeView(ready=False)
    second = _FakeNativeView(ready=True)
    views = [first, second]
    created_for: list[int] = []

    monkeypatch.setattr(webview2_host, "_is_valid_hwnd", lambda hwnd: True)

    def create_webview(parent_hwnd, *_args, **_kwargs):
        created_for.append(parent_hwnd)
        return views.pop(0)

    monkeypatch.setattr(webview2_host.webview_integration, "create_webview", create_webview)

    ctx.openNewTab("https://example.com")
    ctx.attachWindow(_FakeWindow([333, 333, 333]))

    assert created_for == [333]
    assert first.closed is True
    assert ctx._webviews == {}
    assert ctx.nativeBrowserVisible is False

    ctx.setBrowserRect(0, 0, 640, 480, True)

    assert created_for == [333, 333]
    assert second.closed is False
    assert ctx.nativeBrowserVisible is True


def test_hwnd_change_closes_old_native_view_and_recreates(monkeypatch) -> None:
    _app()
    from modes.web import webview2_host

    ctx = WebContext()
    ctx._runtime_available = True
    views = [_FakeNativeView(), _FakeNativeView()]
    created_for: list[int] = []

    monkeypatch.setattr(webview2_host, "_is_valid_hwnd", lambda hwnd: True)

    def create_webview(parent_hwnd, *_args, **_kwargs):
        created_for.append(parent_hwnd)
        return views[len(created_for) - 1]

    monkeypatch.setattr(webview2_host.webview_integration, "create_webview", create_webview)

    ctx.openNewTab("https://example.com")
    ctx.attachWindow(_FakeWindow([100, 200, 200]))
    ctx.setBrowserRect(0, 0, 640, 480, True)

    assert created_for == [100, 200]
    assert views[0].closed is True
    assert views[1].closed is False
    assert ctx.nativeBrowserVisible is True


def test_webview2_oserrored_controller_creation_retries_with_fresh_environment(monkeypatch, tmp_path) -> None:
    _app()
    from modes.web import webview2_windows

    class FakeCoreWebView2:
        source = "about:blank"
        document_title = ""
        can_go_back = False
        can_go_forward = False

        def __init__(self) -> None:
            self.navigations = []

        def add_navigation_started(self, _callback): return "started"
        def add_navigation_completed(self, _callback): return "completed"
        def add_source_changed(self, _callback): return "source"
        def add_document_title_changed(self, _callback): return "title"
        def remove_navigation_started(self, _token) -> None: pass
        def remove_navigation_completed(self, _token) -> None: pass
        def remove_source_changed(self, _token) -> None: pass
        def remove_document_title_changed(self, _token) -> None: pass
        def navigate(self, url: str) -> None: self.navigations.append(url)
        def navigate_to_string(self, _html: str) -> None: pass
        def go_back(self) -> None: pass
        def go_forward(self) -> None: pass
        def reload(self) -> None: pass
        def stop(self) -> None: pass

    class FakeController:
        def __init__(self) -> None:
            self.core_webview2 = FakeCoreWebView2()
            self.closed = False
            self.default_background_color = None
            self.bounds = None
            self.is_visible = False

        def close(self) -> None:
            self.closed = True

    class FakeEnvironment:
        def __init__(self, name: str) -> None:
            self.name = name

        def create_core_webview2_controller_async(self, parent):
            attempts.append((self.name, parent))
            if len(attempts) == 1:
                raise OSError(1400, "Invalid window handle")
            return FakeController()

    class FakeEnvironmentFactory:
        @staticmethod
        def create_with_options_async(*_args):
            environments.append(FakeEnvironment(f"env{len(environments) + 1}"))
            return environments[-1]

    class FakeWindowReference:
        @staticmethod
        def create_from_window_handle(hwnd: int):
            parents.append(hwnd)
            return f"parent:{hwnd}"

    attempts: list[tuple[str, str]] = []
    environments: list[FakeEnvironment] = []
    parents: list[int] = []

    monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(webview2_windows, "IS_WINDOWS", True)
    monkeypatch.setattr(webview2_windows, "WEBVIEW2_AVAILABLE", True)
    monkeypatch.setattr(webview2_windows, "CoreWebView2Environment", FakeEnvironmentFactory, raising=False)
    monkeypatch.setattr(webview2_windows, "CoreWebView2ControllerWindowReference", FakeWindowReference, raising=False)
    monkeypatch.setattr(webview2_windows.WebView, "_environment", None)
    monkeypatch.setattr(webview2_windows.WebView, "_await_result", staticmethod(lambda op: op))

    view = webview2_windows.WebView(123, "https://example.com")

    assert view.is_ready is True
    assert [env.name for env in environments] == ["env1", "env2"]
    assert attempts == [("env1", "parent:123"), ("env2", "parent:123")]
    assert parents == [123, 123]
