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
