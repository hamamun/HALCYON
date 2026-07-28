"""The gear popover's structure — source-level, like ``test_chrome_behaviour``.

Three reported problems, all of them about a list that grows without bound:

* a file with **50+ embedded subtitles** rendered 50+ rows, so the popover was
  taller than the window and most of the list was off-screen and unreachable;
* the same would happen to audio on a multi-dub release;
* the "Disable" row scrolled away with everything else, so once you had scrolled
  down there was no way back to *off* without scrolling up again.

Plus the selection bug from ``test_track_selection.py``, seen from the QML side:
the popover must bind its highlight to the controller's published selection
rather than sit on its declared ``-1`` default.

Building the real component needs QtGui and a GL driver, which CI does not have
(see ``tests/conftest.py``) — and a layout rule only checked on a developer's
desktop is a rule that rots. So these read the source, exactly as the chrome
tests do.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _section() -> str:
    return _read("ui", "transport", "TrackSection.qml")


def _code(source: str) -> str:
    """Source with ``//`` comments stripped.

    These checks are about what the file *does*. Several of them assert that a
    string is absent, and the comment explaining why it is absent naturally
    contains it — so without this the file's own documentation fails its tests.
    """
    return "\n".join(re.sub(r"//.*$", "", line) for line in source.splitlines())


def _popover() -> str:
    return _read("ui", "transport", "TrackPopover.qml")


# ------------------------------------------------- one control, used twice ---
def test_audio_and_subtitles_use_the_same_control():
    """§B.1 — two TrackSections, not a TrackSection and a lookalike."""
    source = _popover()

    assert source.count("TrackSection {") == 2, (
        "audio and subtitles must be the same component; the scroll and "
        "pinning rules are written once, in TrackSection, and both inherit them"
    )


def test_the_popover_declares_no_track_rows_of_its_own():
    source = _popover()

    assert "ListRow {" not in source, (
        "row rendering belongs to TrackSection — a second implementation here "
        "is how the two sections start behaving differently"
    )


# ----------------------------------------------------------- the scrollbar ---
def test_a_long_track_list_scrolls_inside_the_section():
    source = _section()

    assert "ListView {" in source, "a Repeater cannot scroll; a ListView can"
    assert "ScrollBar.vertical" in source, (
        "50 embedded subtitles must scroll within the section, not push the "
        "popover off the top of the screen"
    )
    assert "clip: true" in source, "rows must not paint outside the scroll area"


def test_the_scroll_threshold_is_five_rows():
    source = _section()

    assert re.search(r"property int maxVisibleRows:\s*5", source), (
        "the agreed threshold is five rows — beyond that the section scrolls"
    )


def test_the_section_height_is_capped_once_it_scrolls():
    source = _section()

    assert "root.maxVisibleRows * root.rowHeight" in source, (
        "past the threshold the height must be a fixed row count, otherwise the "
        "popover keeps growing and the scrollbar is decorative"
    )


def test_the_scrollbar_is_off_for_a_short_list():
    """Five audio tracks should look like five rows, not like a scroll area."""
    source = _section()

    assert "ScrollBar.AlwaysOff" in source
    assert "root.scrolls ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff" in source


def test_flicking_is_disabled_when_there_is_nothing_to_scroll():
    source = _section()

    assert "interactive: root.scrolls" in source, (
        "a non-scrolling list that still swallows wheel events blocks the "
        "popover's own scrolling"
    )


# ------------------------------------------------------- the pinned off row ---
def test_the_off_row_is_outside_the_scroll_area():
    """It must be a sibling of the ListView, not one of its delegates."""
    source = _section()
    before_list = source.split("ListView {", 1)[0]

    assert "root.offTrack" in before_list, (
        "the off row is declared above the ListView so it stays put while the "
        "tracks scroll under it"
    )


def test_the_off_row_is_excluded_from_the_scrolling_model():
    source = _section()

    assert "model: root.realTracks" in source, (
        "the ListView must render realTracks (off row removed), or the pinned "
        "row appears twice"
    )
    assert "tracks[i].off !== true" in source


def test_the_off_row_is_found_by_flag_not_by_label():
    source = _code(_section())

    assert "Disable" not in source, (
        "libVLC localises 'Disable'; the off row is identified by the `off` "
        "flag core/app.py sets from its id (-1)"
    )
    assert "tracks[i].off === true" in source


def test_a_divider_marks_the_pinned_boundary():
    source = _section()

    assert "root.offTrack !== null && root.realTracks.length > 0" in source, (
        "the 'this part does not move' boundary should be visible, not implied"
    )


# --------------------------------------------------------- the highlight ---
def test_the_row_label_reads_current_from_the_row_not_from_parent():
    """ListRow reparents children into an inner Item, so `parent.current` is
    undefined — the label stayed white while the row's accent bar lit up."""
    source = _code(_section())

    assert "parent.current" not in source, (
        "`parent` inside a ListRow's default children is its content Item, "
        "which has no `current` property"
    )
    assert "offRow.current" in source
    assert "trackRow.current" in source


def test_the_bar_binds_the_live_selection_from_the_controller():
    source = _read("ui", "Main.qml")

    assert "App.currentAudioId" in source, (
        "without this the popover keeps its declared default of -1, which is "
        "libVLC's Disable id — so Disable is highlighted while a track plays"
    )
    assert "App.currentSubtitleId" in source


def test_the_transport_bar_forwards_the_selection_to_the_popover():
    source = _read("modes", "local", "LocalTransport.qml")

    assert "currentAudioId: root.currentAudioId" in source
    assert "currentSubtitleId: root.currentSubtitleId" in source


# ---------------------------------------------------------- download entry ---
def test_the_popover_offers_both_subtitle_sources():
    source = _popover()

    assert "Load subtitle file" not in source or "From file" in source
    assert "From file" in source, "the local-file path must survive"
    assert "Search online" in source, "the download path needs an entry point"


def test_the_search_button_triggers_the_shared_action():
    """§4.1 — the popover triggers, Main.qml implements."""
    source = _popover()

    assert "Actions.searchSubtitlesOnline()" in source
    assert "Subtitles.search" not in source, (
        "the popover must not drive the service directly; the dialog owns that"
    )


def test_the_action_is_declared_and_implemented_once():
    actions = _read("ui", "Actions.qml")
    main = _read("ui", "Main.qml")

    assert "function searchSubtitlesOnline()" in actions
    assert main.count("function searchSubtitlesOnline()") == 1


def test_searching_is_disabled_with_nothing_playing():
    source = _popover()
    button = source.split("Search online", 1)[1]

    assert "Player.currentMedia" in button, (
        "an online search is a search *for the current file*; greying the "
        "button out says so, an empty result list does not"
    )


def test_the_popover_says_when_no_api_key_is_configured():
    source = _popover()

    assert "Subtitles.configured" in source, (
        "otherwise the button opens a dialog whose only message is 'go to "
        "Settings'"
    )


def test_the_popover_closes_before_opening_a_dialog():
    """A flyout left open behind a modal is stuck there — it closes on
    press-outside-parent, and the modal eats the press."""
    source = _popover()

    assert source.count("root.close();") >= 2


# ------------------------------------------------------------- settings ---
def test_settings_owns_the_api_key_and_language():
    source = _read("ui", "panels", "SettingsDialog.qml")

    assert "subs.online.apiKey" in source
    assert "subs.online.language" in source
    assert "subs.online.matchMode" in source


def test_settings_does_not_search():
    """Configuration and action stay apart (§4.1)."""
    source = _read("ui", "panels", "SettingsDialog.qml")

    assert "Subtitles.search" not in source
    assert "Subtitles.download" not in source


def test_the_language_list_comes_from_the_service():
    """One list, so Settings and the search dialog cannot drift apart."""
    settings = _read("ui", "panels", "SettingsDialog.qml")
    dialog = _read("ui", "panels", "SubtitleSearchDialog.qml")

    assert "Subtitles.languages" in settings
    assert "Subtitles.languages" in dialog


def test_settings_scrolls_now_that_it_is_taller():
    source = _read("ui", "panels", "SettingsDialog.qml")

    assert "ScrollView" in source, (
        "the dialog gained a section; on a 768px screen an unscrollable modal "
        "hides its own Done button"
    )


def test_settings_reuses_the_shared_field_and_select_controls():
    """§B.1 — the video-backend combo was inline; a second copy is not allowed."""
    source = _read("ui", "panels", "SettingsDialog.qml")

    assert "SettingSelect {" in source
    assert "SettingField {" in source
    assert "ComboBox {" not in source, (
        "the combo now lives in SettingSelect.qml, once"
    )


def test_the_new_panels_are_registered_as_qml_types():
    qmldir = _read("Halcyon", "Panels", "qmldir")

    for name in ("SettingSelect", "SettingField", "SubtitleSearchDialog"):
        assert name in qmldir, f"{name} is unresolvable without a qmldir entry"


# ------------------------------------------------------------------ icons ---
def test_the_gear_is_not_reused_for_the_track_popover():
    """One glyph must not open two unrelated things.

    The transport bar's popover (speed / audio / subtitles) and the title bar's
    Settings dialog both drew ``Glyphs.settings``. Same icon, same size, two
    entirely different destinations — so the icon taught the user nothing about
    either, and the popover looked like a second Settings button.
    """
    transport = _read("modes", "local", "LocalTransport.qml")

    assert "Glyphs.settings" not in transport, (
        "the gear belongs to Settings; the popover needs its own glyph"
    )
    assert "Glyphs.tracks" in transport


def test_the_title_bar_keeps_the_gear():
    """The change must not have swapped the wrong one."""
    assert "Glyphs.settings" in _read("ui", "shell", "TitleBar.qml")


def test_the_track_glyph_is_distinct_from_the_settings_glyph():
    source = _read("ui", "components", "Glyphs.qml")
    codepoints = dict(
        re.findall(r'property string (\w+):\s*"\\u([0-9A-Fa-f]{4})"', source)
    )

    assert "tracks" in codepoints, "Glyphs.tracks must be defined centrally"
    assert codepoints["tracks"].upper() != codepoints["settings"].upper()


def test_the_track_glyph_survives_the_windows_10_fallback():
    """Segoe Fluent Icons ships with Windows 11; Windows 10 falls back to Segoe
    MDL2 Assets. A codepoint present only in the newer font renders as a blank
    box there, so the popover button would simply vanish."""
    source = _read("ui", "components", "Glyphs.qml")
    codepoints = dict(
        re.findall(r'property string (\w+):\s*"\\u([0-9A-Fa-f]{4})"', source)
    )

    # ED1F "SubtitlesAudio" is documented in both fonts' PUA ED00-EF00 block.
    assert codepoints["tracks"].upper() == "ED1F"


def test_every_glyph_is_a_private_use_codepoint():
    """A stray real character would render in the text font, at the wrong
    weight and size, next to icons that do not."""
    source = _read("ui", "components", "Glyphs.qml")
    codepoints = re.findall(r'property string \w+:\s*"\\u([0-9A-Fa-f]{4})"', source)

    assert codepoints
    for cp in codepoints:
        assert 0xE000 <= int(cp, 16) <= 0xF8FF, f"U+{cp} is outside the icon font's PUA"
