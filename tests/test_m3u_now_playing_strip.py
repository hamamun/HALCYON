"""The two M3U panel fixes, held where they can be held head-lessly.

Covered here
------------
**Flat mode has no group header.** The visible half of that bug lives in
``M3UPanel.qml`` — a ``ListView`` given an empty ``section.property`` still
sees one section (the empty string) covering every row, and with
``labelPositioning: CurrentLabelAtStart`` it pins one header for it at the top
of the viewport. The fix is to hand back a *null* section delegate in flat
mode, which no test can execute here (QML needs a GPU-capable Qt Quick
environment CI does not have; that half is held by review and ``qmllint``).
What *is* testable is the model contract the QML fix depends on, and this file
pins it: in ``GROUPING_NONE`` every row's ``groupKey`` is empty, every row
reports itself expanded, the accordion is inert, and none of the
"Unknown"/"Ungrouped" placeholder keys the header used to display are produced.
If any of those regressed, the QML would grow a header back.

**The pinned "now playing" strip.** The strip is QML, but everything it binds
to is model surface, and that is what decides whether it behaves: it must keep
showing a channel that the filter has hidden, that failed to play, and that a
grouping change has re-sorted; it must show nothing before anything is chosen;
and clicking it must open the playing channel's group and say which row to
scroll to without re-playing the stream.

Also here: the "group containing the playing channel stays open, other groups
collapsed, until the user closes it" rule, checked across a filter change and
a grouping change (``_rebuild_view(preserve_expanded=...)``).
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
        Channel(name="TF1", url="http://x/4", group="Entertainment", country="France",
                language="fr"),
        Channel(name="France 24", url="http://x/5", group="News", country="France", language="fr"),
    ]


def _model(grouping: str = GROUPING_CATEGORY) -> ChannelModel:
    model = ChannelModel()
    model.set_channels(_sample_channels())
    model.setGrouping(grouping)
    return model


def _group_keys(model: ChannelModel) -> list[str]:
    return [model.data(model.index(row), model.GroupKeyRole) for row in range(model.count)]


# ---------------------------------------------------------------------------
# Fix 1 — no group header in "No group" mode
# ---------------------------------------------------------------------------
def test_flat_mode_produces_no_group_key_for_any_row() -> None:
    """Every row's section string is empty, so the view has nothing to label.

    This is the model-side half of the header fix. The panel's header text came
    from the section string, with "Unknown"/"Ungrouped" substituted when it was
    empty — so a non-empty key here in flat mode would put a *named* header
    back on screen even after the delegate fix.
    """
    model = _model(GROUPING_NONE)

    assert model.count == 5
    assert _group_keys(model) == ["", "", "", "", ""]
    # Specifically none of the placeholder keys the grouped modes invent.
    assert "Unknown" not in _group_keys(model)
    assert "Ungrouped" not in _group_keys(model)


def test_flat_mode_has_no_expanded_group_and_an_inert_accordion() -> None:
    """Nothing is collapsible in flat mode, so nothing can be collapsed."""
    model = _model(GROUPING_NONE)

    assert model.expandedGroup == ""
    for row in range(model.count):
        assert model.data(model.index(row), model.IsGroupExpandedRole) is True

    # A header click cannot reach the model in flat mode, but if one ever did
    # it must not hide the list behind a group nobody can re-open.
    model.toggleGroup("")
    model.toggleGroup("News")
    assert model.expandedGroup == ""
    for row in range(model.count):
        assert model.data(model.index(row), model.IsGroupExpandedRole) is True


def test_switching_to_flat_and_back_restores_the_grouped_sections() -> None:
    """The acceptance path: category -> none -> category -> country."""
    model = _model(GROUPING_CATEGORY)
    assert set(_group_keys(model)) == {"News", "Entertainment"}

    model.setGrouping(GROUPING_NONE)
    assert set(_group_keys(model)) == {""}
    assert model.expandedGroup == ""

    model.setGrouping(GROUPING_CATEGORY)
    assert set(_group_keys(model)) == {"News", "Entertainment"}
    assert model.expandedGroup in {"News", "Entertainment"}

    model.setGrouping(GROUPING_COUNTRY)
    assert set(_group_keys(model)) == {"UK", "USA", "France"}
    assert model.expandedGroup in {"UK", "USA", "France"}

    # ...and the accordion still works after the round trip.
    model.toggleGroup("UK")
    assert model.expandedGroup == "UK"
    for row in range(model.count):
        idx = model.index(row)
        assert model.data(idx, model.IsGroupExpandedRole) == (
            model.data(idx, model.CountryRole) == "UK"
        )


def test_flat_mode_leaves_the_view_unsorted_and_complete() -> None:
    """Flat mode is the plain list: original order, every channel, no grouping
    pass. (The grouped modes re-sort; this one must not.)"""
    model = _model(GROUPING_NONE)

    assert [model.data(model.index(r), model.NameRole) for r in range(model.count)] == [
        c.name for c in _sample_channels()
    ]


# ---------------------------------------------------------------------------
# Fix 2 — the pinned "now playing" strip
# ---------------------------------------------------------------------------
def test_strip_is_empty_before_anything_is_played() -> None:
    """The muted-placeholder state: `hasCurrent` is what the panel binds to."""
    model = _model()

    assert model.hasCurrent is False
    assert model.currentName == ""
    assert model.currentGroup == ""
    assert model.currentUrl == ""
    assert model.currentLogo == ""


def test_strip_shows_the_played_channel() -> None:
    model = _model(GROUPING_NONE)

    assert model.play_index(1) is True
    assert model.hasCurrent is True
    assert model.currentName == "BBC News"
    assert model.currentGroup == "News"
    assert model.currentUrl == "http://x/2"


def test_strip_keeps_the_channel_when_the_stream_never_plays(tmp_path) -> None:
    """A broken/offline channel still shows: the strip reflects the *selection*.

    The engine here raises on open, exactly as a dead stream URL does, and the
    context turns that into its stream-error toast. The strip's data must be
    completely unmoved by it — nothing in this path consults the engine.
    """
    engine = _FailingEngine()
    context = M3UContext(engine, _Controller(), _Settings(tmp_path / "settings.json"))
    model = context.channels
    model.set_channels(_sample_channels())
    model.setGrouping(GROUPING_NONE)

    context.play_index(2)

    assert engine.attempted == ["http://x/3"]
    assert model.hasCurrent is True
    assert model.currentName == "CNN US"
    assert model.currentUrl == "http://x/3"


def test_strip_survives_a_filter_that_hides_the_playing_channel() -> None:
    """`currentIndex` legitimately goes to -1 here; the strip must not follow it.

    This is why the strip binds to `currentName`/`hasCurrent` and not to the
    index — a filter that excludes the playing row would otherwise blank it.
    """
    model = _model(GROUPING_NONE)
    model.play_index(0)                      # BBC One

    model.setFilter("france")
    assert model.currentIndex == -1          # not in the filtered view
    assert model.hasCurrent is True          # ...but still what is playing
    assert model.currentName == "BBC One"

    model.setFilter("")
    assert model.currentIndex == 0
    assert model.currentName == "BBC One"


def test_strip_survives_a_grouping_change() -> None:
    model = _model(GROUPING_CATEGORY)
    model.play_index(model.count - 1)
    playing = model.currentName

    for grouping in (GROUPING_COUNTRY, GROUPING_LANGUAGE, GROUPING_NONE, GROUPING_CATEGORY):
        model.setGrouping(grouping)
        assert model.hasCurrent is True
        assert model.currentName == playing


def test_strip_notifies_only_when_the_selection_actually_changes() -> None:
    """`currentChannelChanged` is the strip's repaint trigger.

    It must fire when another channel is played, and must *not* fire for the
    view churn (filter, grouping) that moves `currentIndex` around — otherwise
    the strip re-requests its logo on every keystroke in the filter box.
    """
    model = _model(GROUPING_CATEGORY)
    fired = []
    model.currentChannelChanged.connect(lambda: fired.append(model.currentName))

    model.play_index(0)
    assert len(fired) == 1

    model.setFilter("bbc")
    model.setGrouping(GROUPING_COUNTRY)
    model.setFilter("")
    assert len(fired) == 1, "view rebuilds must not look like a selection change"

    model.play_index(1)
    assert len(fired) == 2


def test_strip_logo_is_filtered_by_the_same_rules_as_the_rows() -> None:
    """The strip does not go through the panel's logo queue (PR #176), so the
    "can this URL ever load / has it failed before" filtering has to reach it
    some other way: it asks the model, which applies `display_logo`."""
    model = ChannelModel()
    model.set_channels([
        Channel(name="Vector", url="http://x/1", group="News", logo="http://logos/a.svg"),
        Channel(name="Dead", url="http://x/2", group="News", logo="http://logos/b.png"),
        Channel(name="Good", url="http://x/3", group="News", logo="http://logos/c.png"),
        Channel(name="Bare", url="http://x/4", group="News", logo=""),
    ])
    model.setGrouping(GROUPING_NONE)
    model.set_logo_gate({"http://logos/b.png"}.__contains__)

    model.play_index(0)
    assert model.currentLogo == "", "an SVG can never decode in this build"
    model.play_index(1)
    assert model.currentLogo == "", "a URL that already failed is not asked for again"
    model.play_index(2)
    assert model.currentLogo == "http://logos/c.png"
    model.play_index(3)
    assert model.currentLogo == ""


def test_strip_survives_a_playlist_reload_that_keeps_the_channel() -> None:
    """Channels are re-parsed objects after a reload; identity is the URL."""
    model = _model(GROUPING_NONE)
    model.play_index(1)

    model.set_channels(_sample_channels())   # same playlist, all new objects

    assert model.hasCurrent is True
    assert model.currentName == "BBC News"


def test_clearing_the_playlist_empties_the_strip() -> None:
    model = _model(GROUPING_NONE)
    model.play_index(1)

    model.clear()

    assert model.hasCurrent is False
    assert model.currentName == ""


# --------------------------- clicking the strip ----------------------------
def test_reveal_current_returns_the_row_to_scroll_to() -> None:
    model = _model(GROUPING_NONE)
    model.play_index(3)

    assert model.revealCurrent() == 3
    assert model.currentIndex == 3


def test_reveal_current_expands_a_collapsed_group() -> None:
    """Clicking the strip after shutting the accordion re-opens the right group."""
    model = _model(GROUPING_COUNTRY)
    model.play_index(model.count - 1)
    playing_group = model.data(model.index(model.currentIndex), model.GroupKeyRole)
    assert model.expandedGroup == playing_group

    model.toggleGroup(playing_group)          # user collapses it
    assert model.expandedGroup == ""

    row = model.revealCurrent()
    assert model.expandedGroup == playing_group
    assert row == model.currentIndex
    assert model.data(model.index(row), model.IsGroupExpandedRole) is True


def test_reveal_current_never_replays_the_stream() -> None:
    """It is a "show me where it is" action, not a "play it again" one."""
    opened: list[str] = []
    model = _model(GROUPING_COUNTRY)
    model._play = opened.append

    model.play_index(0)
    assert len(opened) == 1
    model.toggleGroup(model.expandedGroup)

    model.revealCurrent()
    assert len(opened) == 1, "revealCurrent must not open a URL"


def test_reveal_current_reports_nothing_to_scroll_to_when_filtered_out() -> None:
    """-1 tells the panel to leave the list exactly where it is."""
    model = _model(GROUPING_NONE)
    model.play_index(0)
    model.setFilter("france")

    assert model.revealCurrent() == -1


def test_reveal_current_is_safe_with_no_selection() -> None:
    model = _model()
    assert model.revealCurrent() == -1


# ---------------------------------------------------------------------------
# The playing channel's group stays open across rebuilds
# ---------------------------------------------------------------------------
def test_playing_group_stays_open_across_a_filter_change() -> None:
    model = _model(GROUPING_COUNTRY)
    model.play_index([model.data(model.index(r), model.NameRole)
                      for r in range(model.count)].index("CNN US"))
    assert model.expandedGroup == "USA"

    # A filter that keeps the playing channel keeps its group open...
    model.setFilter("cnn")
    assert model.expandedGroup == "USA"

    # ...and one that hides it falls back to a group with rows in it, rather
    # than leaving every header shut over a list nobody can see.
    model.setFilter("bbc")
    assert model.expandedGroup == "UK"
    assert model.groupCount("UK") == 2

    # Clearing the filter brings the playing channel back into view, and its
    # group with it.
    model.setFilter("")
    assert model.expandedGroup == "USA"


def test_playing_group_stays_open_across_a_grouping_change() -> None:
    """Same channel, different way of grouping it: its new group is the open
    one, and every other group is shut."""
    model = _model(GROUPING_CATEGORY)
    model.play_index([model.data(model.index(r), model.NameRole)
                      for r in range(model.count)].index("TF1"))
    assert model.expandedGroup == "Entertainment"

    model.setGrouping(GROUPING_COUNTRY)
    assert model.expandedGroup == "France"

    model.setGrouping(GROUPING_LANGUAGE)
    assert model.expandedGroup == "fr"

    for row in range(model.count):
        idx = model.index(row)
        assert model.data(idx, model.IsGroupExpandedRole) == (
            model.data(idx, model.LanguageRole) == "fr"
        )


def test_a_group_the_user_collapsed_stays_collapsed_through_a_filter_change() -> None:
    """"...until the user collapses it themselves."

    A rebuild that re-opened the playing channel's group here would undo a
    deliberate click, which is the annoying half of this behaviour.
    """
    model = _model(GROUPING_COUNTRY)
    model.play_index(0)
    open_group = model.expandedGroup
    assert open_group

    model.toggleGroup(open_group)
    assert model.expandedGroup == ""

    model.setFilter("e")                     # matches something in every group
    assert model.expandedGroup == "", "a filter is not permission to re-open it"
    model.setFilter("")
    assert model.expandedGroup == ""

    # Playing something re-opens a group, as it should: that is a fresh choice.
    model.play_index(0)
    assert model.expandedGroup != ""


def test_a_grouping_change_starts_the_accordion_afresh() -> None:
    """Collapsed-ness does not carry across a grouping change: the groups it
    referred to no longer exist."""
    model = _model(GROUPING_COUNTRY)
    model.play_index(0)
    model.toggleGroup(model.expandedGroup)
    assert model.expandedGroup == ""

    model.setGrouping(GROUPING_LANGUAGE)
    assert model.expandedGroup != ""


def test_favourites_only_toggle_also_respects_a_user_collapse() -> None:
    model = _model(GROUPING_COUNTRY)
    model.set_favourites({"http://x/1", "http://x/4"})
    model.play_index(0)
    model.toggleGroup(model.expandedGroup)
    assert model.expandedGroup == ""

    model.setFavouritesOnly(True)
    assert model.expandedGroup == ""
    model.setFavouritesOnly(False)
    assert model.expandedGroup == ""


# --------------------------------------------------------------- helpers --
class _FailingEngine(QObject):
    """An engine whose every open() fails, like a dead stream URL."""

    errorOccurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.attempted: list[str] = []

    def open(self, url: str) -> None:
        self.attempted.append(url)
        self.errorOccurred.emit("Could not play this channel.")


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

    def set_mode(self, _mode: str, _key: str, _value) -> None:
        pass
