"""Regression checks for the phone remote's Local screen layout.

The Local screen groups its controls into collapsible cards so a phone-sized
viewport is not dominated by the equalizer and the playlist:

    Transport -> Volume -> Tracks & Subtitles -> Equalizer -> Files -> Playlist

Tracks & Subtitles, the Equalizer and the Equalizer's band sliders start
collapsed; the Playlist starts open.  These tests read the static assets as
text (the same approach as ``test_remote_web_controls``) so they stay fast and
need no browser.
"""

from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parent.parent / "remote" / "static"
INDEX_HTML = STATIC / "index.html"
APP_JS = STATIC / "app.js"
STYLE_CSS = STATIC / "style.css"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _css() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


def _local_screen() -> str:
    """Return just the markup of the Local screen."""
    source = _html()
    start = source.index('id="screen-local"')
    end = source.index('id="screen-m3u"')
    return source[start:end]


# --------------------------------------------------------------------------
# 1. card order: Files directly above Playlist
# --------------------------------------------------------------------------

def test_files_card_sits_directly_above_the_playlist():
    local = _local_screen()

    files = local.index('id="browseBtn"')
    playlist = local.index('id="playlistWrap"')
    assert files < playlist, "Files must come before the Playlist"

    between = local[files:playlist]
    assert 'class="card-title"' not in between, (
        "no other card may sit between Files and the Playlist"
    )


def test_local_transport_keeps_seek_forward_and_fullscreen_controls():
    """Local must expose the same seek/fullscreen actions as desktop playback."""
    local = _local_screen()
    source = _js()

    assert 'id="localSeekBack"' in local
    assert 'id="localSeekFwd"' in local
    assert 'data-cmd="seekFwd"' in local
    assert 'id="localFsBtn"' in local
    assert '$("localFsBtn").addEventListener("click", () => cmd("fullscreen", {}))' in source
    # Native selects have a large intrinsic width on some phone browsers. If
    # flex children cannot shrink, the trailing +10s button is pushed away.
    assert re.search(r"\.row2\s*>\s*\*\s*\{[^}]*min-width:\s*0", _css(), re.S)


def test_local_card_order_is_transport_volume_tracks_eq_files_playlist():
    local = _local_screen()

    anchors = [
        ('data-cmd="playPause"', "Transport"),
        ('id="vol"', "Volume"),
        ('id="trkHead"', "Tracks & Subtitles"),
        ('id="eqToggle"', "Equalizer"),
        ('id="browseBtn"', "Files"),
        ('id="playlistWrap"', "Playlist"),
    ]
    positions = [local.index(marker) for marker, _ in anchors]
    assert positions == sorted(positions), (
        "unexpected Local card order: "
        + str([name for _, name in anchors])
    )


# --------------------------------------------------------------------------
# 2./3./5. collapsible cards and their default state
# --------------------------------------------------------------------------

def test_collapsible_local_sections_exist():
    local = _local_screen()

    for head, body in (
        ("trkHead", "trkBody"),        # Tracks & Subtitles
        ("eqToggle", "eqBody"),        # Equalizer
        ("eqBandsHead", "eqBands"),    # Equalizer bands (nested)
        ("plHead", "playlist"),        # Playlist
    ):
        assert f'id="{head}"' in local, f"missing collapser header #{head}"
        assert f'id="{body}"' in local, f"missing collapsible body #{body}"


def test_tracks_equalizer_and_bands_start_collapsed():
    local = _local_screen()

    for body in ("trkBody", "eqBody", "eqBands"):
        match = re.search(r"<[^>]*id=\"%s\"[^>]*>" % body, local)
        assert match, f"missing #{body}"
        assert " hidden" in match.group(0), (
            f"#{body} must start collapsed (hidden)"
        )


def test_playlist_starts_expanded():
    local = _local_screen()

    match = re.search(r"<[^>]*id=\"playlist\"[^>]*>", local)
    assert match
    assert " hidden" not in match.group(0), "the playlist must start open"


def test_collapsers_are_wired_with_the_shared_helper():
    source = _js()

    assert "function makeCollapser(" in source
    # Tracks & Subtitles, Playlist, Equalizer, Equalizer bands
    assert 'makeCollapser("trkHead", "trkBody", "trkArrow", false)' in source
    assert 'makeCollapser("plHead", "playlist", "plArrow", true)' in source
    assert 'makeCollapser("eqToggle", "eqBody", "eqArrow", false)' in source
    assert 'makeCollapser("eqBandsHead", "eqBands", "eqBandsArrow", false)' in source


def test_collapsers_are_keyboard_and_screen_reader_accessible():
    source = _js()

    assert "aria-expanded" in source
    assert '"Enter"' in source and '" "' in source


def test_collapse_state_is_not_reset_by_snapshots():
    """Snapshots arrive ~3x/sec; renderers must not touch the collapsed flag."""
    source = _js()

    render_eq = source[source.index("function renderEq("):]
    render_eq = render_eq[: render_eq.index("\n}\n")]
    assert ".hidden = " not in render_eq, (
        "renderEq must not force the EQ body/bands open or closed"
    )

    render_pl = source[source.index("function renderPlaylist("):]
    render_pl = render_pl[: render_pl.index("\n}\n")]
    assert ".hidden = " not in render_pl, (
        "renderPlaylist must not force the playlist open or closed"
    )


# --------------------------------------------------------------------------
# 4. equalizer band alignment
# --------------------------------------------------------------------------

def test_equalizer_bands_render_as_fixed_column_rows():
    """Band labels vary in width ("31" vs "16k"); they need their own column."""
    source = _js()

    assert '<div class="eqband-row">' in source
    assert '<span class="eqlabel">' in source
    assert 'class="eqband"' in source
    assert '<span class="val">' in source
    # the old inline-label markup made every slider start at a different x
    assert '<label class="lbl">${esc(label)}' not in source


def test_equalizer_band_row_uses_a_three_column_grid():
    css = _css()

    match = re.search(r"\.eqband-row\s*\{[^}]*\}", css, re.S)
    assert match, "missing .eqband-row rule"
    rule = match.group(0)
    assert "display: grid" in rule
    assert re.search(r"grid-template-columns:\s*34px\s+1fr\s+56px", rule), (
        "label and dB columns must be fixed width so sliders line up"
    )


def test_equalizer_band_label_and_value_columns_are_aligned():
    css = _css()

    label = re.search(r"\.eqband-row \.eqlabel\s*\{[^}]*\}", css, re.S)
    assert label and "text-align: right" in label.group(0)
    assert "tabular-nums" in label.group(0)

    value = re.search(r"\.eqband-row \.val\s*\{[^}]*\}", css, re.S)
    assert value and "text-align: right" in value.group(0)
    assert "tabular-nums" in value.group(0)

    slider = re.search(r"\.eqband-row input\[type=\"range\"\]\s*\{[^}]*\}", css, re.S)
    assert slider and "width: 100%" in slider.group(0), (
        "sliders must fill their grid column so a flat EQ is a straight line"
    )


def test_band_sliders_are_not_rebuilt_while_being_dragged():
    source = _js()

    render_eq = source[source.index("function renderEq("):]
    render_eq = render_eq[: render_eq.index("\n}\n")]
    assert "isDragging" in render_eq


# --------------------------------------------------------------------------
# header affordances that stay usable while collapsed
# --------------------------------------------------------------------------

def test_headers_show_counts_while_collapsed():
    local = _local_screen()
    source = _js()

    assert 'id="eqBandsCount"' in local
    assert 'id="plCount"' in local
    assert '$("eqBandsCount")' in source
    assert '$("plCount")' in source


def test_playlist_header_keeps_shuffle_repeat_and_clear():
    local = _local_screen()

    head = local[local.index('id="playlistHead"'):local.index('id="playlist"')]
    for button in ("shuffleBtn", "repeatBtn", "clearPlBtn"):
        assert f'id="{button}"' in head, (
            f"#{button} must stay on the playlist header row"
        )


def test_playlist_keeps_its_seven_row_scrolling_window():
    css = _css()

    match = re.search(r"#playlist\s*\{[^}]*\}", css, re.S)
    assert match
    assert "calc(7 * 48px)" in match.group(0).replace("calc(7*48px)", "calc(7 * 48px)")
    assert "overflow-y: auto" in match.group(0)


def test_tracks_card_keeps_its_controls():
    local = _local_screen()

    body = local[local.index('id="trkBody"'):]
    body = body[: body.index('id="eqCard"')]
    for control in (
        "audioTrack",
        "subTrack",
        "subDelayMinus",
        "subDelayPlus",
        "subsDownloadBtn",
        "subsFileBtn",
    ):
        assert f'id="{control}"' in body, f"#{control} vanished from Tracks & Subtitles"


def test_db_readouts_are_rounded_for_the_fixed_width_column():
    """VLC returns raw floats (4.800000190734863); unrounded they overflow.

    The dB column is a fixed 56px, so every readout must go through fmtDb()
    or a preset load would wrap the row and undo the alignment fix.
    """
    source = _js()

    assert "function fmtDb(" in source
    assert "Math.round(n * 10) / 10" in source

    # every place a dB string is built must use the formatter
    assert '`<span class="val">${fmtDb(val)} dB</span></div>`' in source
    assert 'textContent = fmtDb(s.value) + " dB"' in source
    assert 'textContent = fmtDb(eq.preamp) + " dB"' in source
    assert 'textContent = fmtDb(e.target.value) + " dB"' in source

    # ...and no raw value is concatenated straight into a dB label
    assert '${val} dB' not in source
    assert 'eq.preamp + " dB"' not in source
    assert 's.value + " dB"' not in source
