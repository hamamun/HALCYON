"""Channel logos: what is never requested, and what is never requested twice.

The bug these guard against is a request storm. A public IPTV playlist is
thousands of other people's logo URLs, a large fraction of them dead, and the
panel used to ask for all of them — every time it was opened. Servers answered
with "excessive load detected", HTTP/2 resets and timeouts, and the next visit
did exactly the same thing again because Qt caches successes but never
failures.

Three defences, all tested here:

* URLs that cannot possibly decode are refused without a request;
* URLs that failed once are remembered, across sessions;
* the model hands the panel an empty logo for both, so the row draws its globe
  fallback and asks for nothing.

The fourth defence — at most six requests in flight, and none at all for rows
in a collapsed group — lives in ``M3UPanel.qml`` and is not reachable from a
head-less test.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal

from modes.m3u.logo_cache import MAX_ENTRIES, LogoFailureStore, is_loadable_logo
from modes.m3u.parser import Channel
from modes.m3u.playlist import GROUPING_NONE, ChannelModel, M3UContext


# --------------------------------------------------------------- inspection --
def test_svg_logos_are_refused_without_a_request() -> None:
    """Qt has no SVG image plugin in this build: the bytes can only be wasted."""
    assert not is_loadable_logo("https://www.aparatchi.com/images/chanells-logo/4kurd.svg")
    assert not is_loadable_logo("https://example.com/logo.SVGZ")


def test_image_share_pages_are_refused() -> None:
    """``ibb.co/BH6CZx3K`` is an HTML page; the image lives on ``i.ibb.co``."""
    assert not is_loadable_logo("https://ibb.co/BH6CZx3K")
    assert not is_loadable_logo("https://imgur.com/aBcDeFg")
    # ...but a direct file on the same host is fine, and so is the CDN host.
    assert is_loadable_logo("https://i.ibb.co/BH6CZx3K/logo.png")
    assert is_loadable_logo("https://imgur.com/aBcDeFg.png")


def test_extensionless_and_proxied_logos_are_allowed() -> None:
    """Conservative on purpose: plenty of working logos carry no extension."""
    assert is_loadable_logo("https://i0.wp.com/fmcosmos.com/wp-content/uploads/x.png")
    assert is_loadable_logo("https://cdn.example.com/logo?id=42")
    assert not is_loadable_logo("")
    assert not is_loadable_logo("   ")


# ------------------------------------------------------------------- store --
def test_failures_persist_across_sessions(tmp_path) -> None:
    path = tmp_path / "m3u-logo-failures.json"
    store = LogoFailureStore(path)

    assert store.add("https://example.com/dead.png") is True
    assert store.add("https://example.com/dead.png") is False  # already known
    assert store.contains("https://example.com/dead.png")
    store.save()

    reloaded = LogoFailureStore(path)
    assert reloaded.contains("https://example.com/dead.png")
    assert not reloaded.contains("https://example.com/alive.png")


def test_store_is_capped_and_evicts_the_oldest(tmp_path) -> None:
    store = LogoFailureStore(tmp_path / "logos.json")
    for i in range(MAX_ENTRIES + 10):
        store.add(f"https://example.com/{i}.png")

    assert len(store) == MAX_ENTRIES
    assert not store.contains("https://example.com/0.png")       # evicted
    assert store.contains(f"https://example.com/{MAX_ENTRIES + 9}.png")


def test_corrupt_store_starts_empty_rather_than_raising(tmp_path) -> None:
    path = tmp_path / "logos.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(LogoFailureStore(path)) == 0


def test_clear_gives_every_logo_another_chance(tmp_path) -> None:
    path = tmp_path / "logos.json"
    store = LogoFailureStore(path)
    store.add("https://example.com/dead.png")
    store.clear()

    assert not store.contains("https://example.com/dead.png")
    assert json.loads(path.read_text(encoding="utf-8")) == []


# ------------------------------------------------------------------- model --
def _channels() -> list[Channel]:
    return [
        Channel(name="Good", url="http://x/1", logo="https://cdn/good.png"),
        Channel(name="Dead", url="http://x/2", logo="https://cdn/dead.png"),
        Channel(name="Svg", url="http://x/3", logo="https://cdn/vector.svg"),
        Channel(name="None", url="http://x/4", logo=""),
    ]


def test_model_blanks_logos_the_panel_must_not_request() -> None:
    model = ChannelModel()
    model.setGrouping(GROUPING_NONE)
    model.set_channels(_channels())
    model.set_logo_gate({"https://cdn/dead.png"}.__contains__)

    logos = [model.data(model.index(row), model.LogoRole) for row in range(model.count)]
    assert logos == ["https://cdn/good.png", "", "", ""]


def test_model_without_a_gate_still_filters_the_impossible() -> None:
    """A head-less model (tests, tools) must not need the store wired up."""
    model = ChannelModel()
    model.setGrouping(GROUPING_NONE)
    model.set_channels(_channels())

    logos = [model.data(model.index(row), model.LogoRole) for row in range(model.count)]
    assert logos == ["https://cdn/good.png", "https://cdn/dead.png", "", ""]


def test_a_raising_gate_never_blanks_the_list() -> None:
    def broken(_url: str) -> bool:
        raise RuntimeError("store exploded")

    model = ChannelModel()
    model.setGrouping(GROUPING_NONE)
    model.set_channels(_channels())
    model.set_logo_gate(broken)

    assert model.data(model.index(0), model.LogoRole) == "https://cdn/good.png"


# ----------------------------------------------------------------- context --
class _Engine(QObject):
    errorOccurred = Signal(str)
    currentMedia = ""

    def stop(self) -> None:
        pass

    def open(self, _url: str) -> None:
        pass


class _Controller(QObject):
    activeModeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.activeMode = "m3u"

    def stop(self) -> None:
        pass


class _Settings:
    def __init__(self, path) -> None:
        self.path = path
        self.values: dict[tuple[str, str], object] = {}
        self.flushes = 0

    def get_mode(self, mode: str, key: str, default=None):
        return self.values.get((mode, key), default)

    def set_mode(self, mode: str, key: str, value) -> None:
        self.values[(mode, key)] = value

    def flush(self) -> None:
        self.flushes += 1


def test_reported_failures_are_remembered_for_the_next_session(tmp_path) -> None:
    settings = _Settings(tmp_path / "settings.json")
    context = M3UContext(_Engine(), _Controller(), settings)
    context.channels.setGrouping(GROUPING_NONE)
    context.channels.set_channels(_channels())

    # The panel reports what its Image element could not load.
    context.noteLogoFailed("https://cdn/good.png")
    context.shutdown()   # batched writes are flushed here

    reborn = M3UContext(_Engine(), _Controller(), _Settings(tmp_path / "settings.json"))
    reborn.channels.setGrouping(GROUPING_NONE)
    reborn.channels.set_channels(_channels())
    assert reborn.channels.data(reborn.channels.index(0), reborn.channels.LogoRole) == ""


def test_noting_an_empty_url_is_harmless(tmp_path) -> None:
    context = M3UContext(_Engine(), _Controller(), _Settings(tmp_path / "settings.json"))
    context.noteLogoFailed("")
    context.noteLogoFailed("   ")
    context.shutdown()
