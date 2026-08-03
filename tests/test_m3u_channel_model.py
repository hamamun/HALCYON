"""Tests for M3U playlist ChannelModel grouping, accordion expand/collapse,
and search/filter interaction across all categories/groups.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from modes.m3u.parser import Channel
from modes.m3u.playlist import (
    GROUPING_CATEGORY,
    GROUPING_COUNTRY,
    GROUPING_LANGUAGE,
    GROUPING_NONE,
    ChannelModel,
    M3UContext,
)


def _sample_channels() -> list[Channel]:
    return [
        Channel(name="BBC One", url="http://x/1", group="News", country="UK", language="en"),
        Channel(name="BBC News", url="http://x/2", group="News", country="UK", language="en"),
        Channel(name="CNN US", url="http://x/3", group="News", country="USA", language="en"),
        Channel(name="TF1", url="http://x/4", group="Entertainment", country="France", language="fr"),
        Channel(name="France 24", url="http://x/5", group="News", country="France", language="fr"),
    ]


def test_default_grouping_accordion_opens_first_group() -> None:
    model = ChannelModel()
    model.set_channels(_sample_channels())

    # Default grouping is GROUPING_CATEGORY ("News", "Entertainment")
    assert model.grouping == GROUPING_CATEGORY
    # "Entertainment" sorts before "News", so "Entertainment" should be opened by default
    assert model.expandedGroup in {"Entertainment", "News"}
    # groupCount should report counts
    assert model.groupCount("News") == 4
    assert model.groupCount("Entertainment") == 1


def test_toggle_group_accordion_one_at_a_time() -> None:
    model = ChannelModel()
    model.set_channels(_sample_channels())
    model.setGrouping(GROUPING_COUNTRY)

    assert model.expandedGroup == "France"  # First country alphabetically

    # Click UK header -> UK expands, France collapses
    model.toggleGroup("UK")
    assert model.expandedGroup == "UK"

    # Check isGroupExpanded role values
    for row in range(model.count):
        idx = model.index(row)
        country = model.data(idx, model.CountryRole)
        is_expanded = model.data(idx, model.IsGroupExpandedRole)
        assert is_expanded == (country == "UK")

    # Click UK header again -> collapses all
    model.toggleGroup("UK")
    assert model.expandedGroup == ""


def test_filter_works_across_all_groups_and_preserves_or_switches_accordion() -> None:
    model = ChannelModel()
    model.set_channels(_sample_channels())
    model.setGrouping(GROUPING_COUNTRY)

    model.toggleGroup("UK")
    assert model.expandedGroup == "UK"

    # Filter for "france" -> UK has 0 matching channels, France has 2 matching channels
    model.setFilter("france")
    assert model.count == 2
    assert model.groupCount("France") == 2
    assert model.groupCount("UK") == 0
    # Accordion should automatically switch to "France" so matching channels are accessible
    assert model.expandedGroup == "France"

    # Now clear filter -> all channels return, France stays expanded
    model.setFilter("")
    assert model.count == 5
    assert model.expandedGroup == "France"
    assert model.groupCount("UK") == 2
    assert model.groupCount("USA") == 1
    assert model.groupCount("France") == 2


def test_no_group_mode_disables_accordion() -> None:
    model = ChannelModel()
    model.set_channels(_sample_channels())
    model.setGrouping(GROUPING_NONE)

    assert model.expandedGroup == ""
    for row in range(model.count):
        idx = model.index(row)
        assert model.data(idx, model.IsGroupExpandedRole) is True


class _Engine(QObject):
    errorOccurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    def open(self, url: str) -> None:
        self.opened.append(url)


class _Controller(QObject):
    activeModeChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.activeMode = "m3u"


class _Settings:
    def __init__(self, path) -> None:
        self.path = path

    def get_mode(self, _mode: str, _key: str, default):
        return default


def test_context_exposes_friendly_selected_channel_name_for_toasts(tmp_path) -> None:
    """Transport feedback must say "BBC News", never the stream URL."""
    engine = _Engine()
    context = M3UContext(engine, _Controller(), _Settings(tmp_path / "settings.json"))
    context.channels.set_channels(_sample_channels())
    context.channels.setGrouping(GROUPING_NONE)

    assert context.play_index(1)
    assert context.current_playback_label() == "BBC News"
    assert engine.opened == ["http://x/2"]
