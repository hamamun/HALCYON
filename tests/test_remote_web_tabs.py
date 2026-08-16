"""Remote web section: tab switching, collapsible bookmarks, seek bar order.

The tab/bookmark/media markup lives in the static bundle, so the UI parts are
asserted against the shipped HTML/CSS/JS. The command plumbing is asserted
against the bridge's dispatch table using a fake browser context.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remote.bridge import RemoteBridge


STATIC = Path(__file__).resolve().parent.parent / "remote" / "static"
INDEX = STATIC / "index.html"
APP_JS = STATIC / "app.js"
STYLE = STATIC / "style.css"


# --------------------------------------------------------------- fake context


class FakeBrowserContext:
    """Mimics the slots/properties of BrowserContext used by the remote."""

    MAX_TABS = 15

    def __init__(self, count: int = 4):
        self._tabs = [
            {"id": f"t{i}", "title": f"Tab {i}", "url": f"https://e.test/{i}",
             "loading": False, "canGoBack": False, "canGoForward": False,
             "internal": False}
            for i in range(count)
        ]
        self.activeTabIndex = 0
        self.calls: list[tuple] = []

    @property
    def tabs(self):
        return list(self._tabs)

    @property
    def tabCount(self):
        return len(self._tabs)

    @property
    def isAtMaxTabs(self):
        return len(self._tabs) >= self.MAX_TABS

    def setActiveTab(self, index):
        self.calls.append(("setActiveTab", index))
        self.activeTabIndex = index

    def closeTab(self, index):
        self.calls.append(("closeTab", index))
        self._tabs.pop(index)
        return True

    def addTab(self, url=""):
        self.calls.append(("addTab", url))
        self._tabs.append({"id": "new", "title": url or "New Tab", "url": url})
        return True


class FakeControllerLike:
    def __init__(self, mode="local"):
        self.activeMode = mode

    def setActiveMode(self, mode):
        self.activeMode = mode


@pytest.fixture
def bridge_with_web():
    bridge = RemoteBridge.__new__(RemoteBridge)      # no Qt init needed
    ctx = FakeBrowserContext()
    bridge._contexts = {"web": ctx}
    bridge._controller = FakeControllerLike()
    bridge._closed = False
    return bridge, ctx


# ----------------------------------------------------- 1. tab switching (cmds)


def test_select_tab_by_id_switches_active_tab(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_selectTab({"id": "t2", "index": 2})
    assert ("setActiveTab", 2) in ctx.calls


def test_select_tab_prefers_id_over_stale_index(bridge_with_web):
    """Index may be stale if a tab closed between snapshot and tap."""
    bridge, ctx = bridge_with_web
    bridge._cmd_web_selectTab({"id": "t3", "index": 0})
    assert ("setActiveTab", 3) in ctx.calls


def test_select_tab_falls_back_to_index_without_id(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_selectTab({"index": 1})
    assert ("setActiveTab", 1) in ctx.calls


def test_select_tab_ignores_unknown_id(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_selectTab({"id": "gone"})
    assert ctx.calls == []


def test_select_tab_activates_web_mode_on_pc(bridge_with_web):
    bridge, _ = bridge_with_web
    bridge._controller.activeMode = "local"
    bridge._cmd_web_selectTab({"id": "t1"})
    assert bridge._controller.activeMode == "web"


def test_close_tab_from_phone(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_closeTab({"id": "t1", "index": 1})
    assert ("closeTab", 1) in ctx.calls
    assert [t["id"] for t in ctx.tabs] == ["t0", "t2", "t3"]


def test_close_tab_ignores_bad_index(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_closeTab({"index": -1})
    assert ctx.calls == []


def test_new_tab_from_phone(bridge_with_web):
    bridge, ctx = bridge_with_web
    bridge._cmd_web_newTab({})
    assert ("addTab", "") in ctx.calls


def test_tab_commands_are_safe_without_web_context():
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._contexts = {}
    bridge._controller = None
    bridge._closed = False
    bridge._cmd_web_selectTab({"id": "t0"})
    bridge._cmd_web_closeTab({"index": 0})
    bridge._cmd_web_newTab({})       # must not raise


def test_snapshot_exposes_tab_index_and_max_flag(bridge_with_web):
    bridge, ctx = bridge_with_web
    ctx.activeTabIndex = 2
    snap = bridge._web_snapshot()
    assert snap["activeTabIndex"] == 2
    assert snap["atMaxTabs"] is False
    assert len(snap["tabs"]) == 4
    assert snap["tabCount"] == 4


def test_snapshot_defaults_when_web_mode_absent():
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._contexts = {}
    snap = bridge._web_snapshot()
    assert snap["activeTabIndex"] == -1
    assert snap["atMaxTabs"] is False
    assert snap["tabs"] == []


# ------------------------------------------------------ 1. tab switching (UI)


def test_active_page_card_renders_a_tab_list():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="webTabs"' in html
    assert 'id="webNewTabBtn"' in html


def test_tab_rows_send_select_and_close_commands():
    js = APP_JS.read_text(encoding="utf-8")
    assert "web.selectTab" in js
    assert "web.closeTab" in js
    assert "web.newTab" in js
    assert "data-tab-sel" in js
    assert "data-tab-close" in js


def test_close_button_does_not_also_switch_tab():
    """The ✕ sits inside the tappable row, so its handler must stop bubbling."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "e.stopPropagation();" in js
    assert 'e.target.closest("[data-tab-close]")' in js


def test_tab_list_scrolls_after_four_rows():
    css = STYLE.read_text(encoding="utf-8")
    assert ".tablist" in css
    assert "max-height: calc(4 * 48px)" in css
    assert "overflow-y: auto" in css


# --------------------------------------------- 2. collapsible bookmarks (UI)


def test_bookmarks_card_is_collapsible():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="bmHead"' in html
    assert 'id="bmBody"' in html
    assert 'id="bmArrow"' in html


def test_bookmarks_start_collapsed():
    html = INDEX.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert '<div id="bmBody" hidden>' in html         # collapsed in markup
    assert "setBookmarksOpen(false);" in js           # and on load
    assert "let WEB_BM_OPEN = false;" in js


def test_bookmarks_scroll_after_three_rows():
    css = STYLE.read_text(encoding="utf-8")
    assert ".bmlist" in css
    assert "max-height: calc(3 * 48px)" in css


def test_bookmark_actions_survive_the_collapse():
    js = APP_JS.read_text(encoding="utf-8")
    for action in ("web.bookmarkAdd", "web.bookmarkRemove", "web.openInNewTab"):
        assert action in js


# ------------------------------------------- 3. seek bar above play/pause (UI)


def test_web_seek_bar_sits_above_the_transport_buttons():
    """Seek must not neighbour the volume slider — fingers hit the wrong one."""
    html = INDEX.read_text(encoding="utf-8")
    body = html.split('id="webMediaBody"', 1)[1].split("</section>", 1)[0]

    seek = body.index('id="wmSeek"')
    play = body.index('id="wmPlay"')
    vol = body.index('id="wmVol"')

    assert seek < play < vol, "order must be seek -> play/pause -> volume"


def test_web_media_rows_are_all_present():
    html = INDEX.read_text(encoding="utf-8")
    body = html.split('id="webMediaBody"', 1)[1].split("</section>", 1)[0]
    assert 'class="seekrow' in body
    assert 'class="transport"' in body
    assert 'class="volrow"' in body
    for el in ("wmBack", "wmPlay", "wmFwd", "wmCur", "wmDur", "wmVol", "wmMute", "wmFs"):
        assert f'id="{el}"' in body


def test_local_screen_seek_layout_is_untouched():
    """Only the Web media card changed; Local transport keeps its old order."""
    html = INDEX.read_text(encoding="utf-8")
    local = html.split('id="screen-local"', 1)[1].split("</section>", 1)[0]
    assert local.index('data-cmd="playPause"') < local.index('id="seek"')
