"""M3U/M3U8 parser tests — Milestone 2.1.

Pure Python: parser.py is deliberately Qt-free so this module runs anywhere,
including machines where PySide6 cannot import.
"""

from __future__ import annotations

from pathlib import Path

from modes.m3u.parser import (
    decode_playlist,
    looks_like_playlist_ref,
    parse_m3u,
    parse_playlist_text,
    parse_pls,
)


BASIC = """\
#EXTM3U
#EXTINF:-1 tvg-id="bbc1.uk" tvg-name="BBC One" tvg-logo="https://img/bbc1.png" tvg-country="UK" group-title="News",BBC One HD
http://cdn.example.com/bbc1/playlist.m3u8
#EXTINF:-1 group-title="Sports",Sky Sports
http://cdn.example.com/sky/index.m3u8?token=abc
"""

MIXED = """\
#EXTM3U
#EXTINF:-1 group-title="Films",Local Movie
videos/movie.mkv
#EXTINF:-1,Broken Entry With No URL
#EXTINF:abc group-title="Bad",Bad Duration
http://example.com/stream/123
not a comment line without extinf
#EXTGRP:FallbackGroup
#EXTINF:-1,Grouped By EXTGRP
http://example.com/tv/55
"""


def test_basic_extinf_attributes() -> None:
    result = parse_m3u(BASIC)
    assert result.skipped == 0
    assert len(result.channels) == 2

    first = result.channels[0]
    assert first.name == "BBC One HD"
    assert first.group == "News"
    assert first.logo == "https://img/bbc1.png"
    assert first.country == "United Kingdom"  # resolver converts "UK" to full name
    assert first.language == "English"         # resolved from country
    assert first.tvg_id == "bbc1.uk"
    assert first.is_remote

    # Query strings must survive intact.
    assert result.channels[1].url.endswith("?token=abc")


def test_malformed_lines_are_skipped_never_fatal() -> None:
    result = parse_m3u(MIXED, base_dir=Path("/lists"))
    names = [c.name for c in result.channels]

    # EXTINF-with-no-URL, bad duration parsed as -1, bare entry, EXTGRP entry.
    assert "Broken Entry With No URL" not in names
    assert result.skipped >= 1

    bare = next(c for c in result.channels
                if c.url.endswith("not a comment line without extinf"))
    assert bare.name  # something derived, never empty

    grouped = next(c for c in result.channels if c.name == "Grouped By EXTGRP")
    assert grouped.group == "FallbackGroup"


def test_relative_path_resolves_against_playlist_folder() -> None:
    result = parse_m3u(MIXED, base_dir=Path("/lists"))
    local = next(c for c in result.channels if c.name == "Local Movie")
    assert local.url == str(Path("/lists/videos/movie.mkv"))
    assert not local.is_remote


def test_title_fallbacks() -> None:
    result = parse_m3u("#EXTM3U\nfilms/The Matrix.mkv\n")
    assert result.channels[0].name == "The Matrix"

    result = parse_m3u("http://example.com/live/channel1\n")
    assert result.channels[0].name == "channel1"

    result = parse_m3u("http://example.com:8080/\n")
    assert result.channels[0].name  # host fallback, non-empty


def test_nested_playlist_references_are_ignored() -> None:
    """Nested skipping applies to LOCAL references — a remote .m3u8 URL is the
    channel itself (HLS), which is what nearly every real IPTV entry looks like."""
    text = (
        "#EXTM3U\n"
        "#EXTINF:-1,HLS channel (remote .m3u8 stays!)\n"
        "http://example.com/master.m3u8\n"
        "local/other.m3u\n"
        "#EXTINF:-1,Real channel\n"
        "http://example.com/ch/1\n"
    )
    result = parse_m3u(text, base_dir=Path("/lists"))
    names = [c.name for c in result.channels]
    assert names == ["HLS channel (remote .m3u8 stays!)", "Real channel"]
    assert result.skipped == 1          # only the local .m3u chain was dropped


def test_hls_master_playlist_yields_no_channels() -> None:
    master = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1280000\n"
        "low/index.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2560000\n"
        "high/index.m3u8\n"
    )
    result = parse_m3u(master)
    assert result.channels == []
    assert result.skipped >= 2


def test_encoding_bom_and_latin1() -> None:
    text = "#EXTM3U\n#EXTINF:-1,Chaîne Française\nhttp://x.example/1\n"
    bom = b"\xef\xbb\xbf" + text.encode("utf-8")
    assert decode_playlist(bom).lstrip("\ufeff").startswith("#EXTM3U")

    latin1 = text.encode("latin-1")
    decoded = decode_playlist(latin1)
    assert "Fran" in decoded  # decodes without raising; UTF-8 path fails over

    result = parse_m3u(decode_playlist(latin1))
    assert len(result.channels) == 1


def test_empty_and_garbage_input() -> None:
    assert parse_m3u("").channels == []
    assert parse_m3u("\n\n\n").channels == []
    assert parse_m3u("garbage without header").channels[0].name == "garbage without header"


def test_looks_like_playlist_ref() -> None:
    assert looks_like_playlist_ref("http://x/a.M3U8?token=1")
    assert looks_like_playlist_ref("/lists/sub.m3u")
    assert not looks_like_playlist_ref("http://x/stream/123")
    assert not looks_like_playlist_ref("film.mkv")


# ------------------------------------------------------------------
# Country & Language resolution tests
# ------------------------------------------------------------------

def test_country_strategy1_explicit_attribute() -> None:
    """Strategy 1: explicit tvg-country attribute."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-country="DE",ARD\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "Germany"


def test_country_strategy1_alternate_attr_names() -> None:
    """Strategy 1: alternative attribute names (country, nation, region)."""
    for attr in ("country", "nation", "region", "tvg-nation", "tvg-region"):
        text = f'#EXTM3U\n#EXTINF:-1 {attr}="FR",TF1\nhttp://x/1\n'
        result = parse_m3u(text)
        assert result.channels[0].country == "France", f"failed for attr {attr}"


def test_country_strategy2_tvg_id_pattern() -> None:
    """Strategy 2: extract country from tvg-id like 'BBC.uk' or 'CNN.us@East'."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-id="BBC.uk",BBC One\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "United Kingdom"

    text = '#EXTM3U\n#EXTINF:-1 tvg-id="CNN.us@East",CNN\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "United States"


def test_country_strategy3_group_title_splitting() -> None:
    """Strategy 3: extract country from group-title like 'UK | Sports'."""
    text = '#EXTM3U\n#EXTINF:-1 group-title="UK | Sports",BBC Sport\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "United Kingdom"

    # Should skip category words (Sports) and find the country code
    text = '#EXTM3U\n#EXTINF:-1 group-title="DE - News",ARD\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "Germany"


def test_country_strategy3_skips_category_words() -> None:
    """Strategy 3 must not mistake 'US' in 'US Sports' as something else,
    but must skip 'Sports' as a non-country word."""
    text = '#EXTM3U\n#EXTINF:-1 group-title="US / Sports",ESPN\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "United States"


def test_country_strategy4_title_pattern() -> None:
    """Strategy 4: extract country from title like '[UK] BBC' or 'UK: CNN'."""
    text = '#EXTM3U\n#EXTINF:-1,[UK] BBC One\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "United Kingdom"

    text = '#EXTM3U\n#EXTINF:-1,DE: ARD\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "Germany"


def test_country_strategy_priority() -> None:
    """Strategy 1 (explicit) wins over strategies 2-4."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-country="FR" tvg-id="BBC.uk" group-title="DE | News",[US] BBC\nhttp://x/1\n'
    result = parse_m3u(text)
    # Explicit tvg-country="FR" wins
    assert result.channels[0].country == "France"


def test_country_empty_when_nothing_matches() -> None:
    """No country data at all → empty string."""
    text = '#EXTM3U\n#EXTINF:-1 group-title="News",Generic Channel\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == ""


def test_language_explicit_attribute() -> None:
    """Explicit tvg-language is used directly."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-language="Arabic",Al Jazeera\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].language == "Arabic"


def test_language_fallback_from_country() -> None:
    """When tvg-language is missing, language is resolved from country."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-country="JP",NHK\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].country == "Japan"
    assert result.channels[0].language == "Japanese"


def test_language_explicit_wins_over_country() -> None:
    """Explicit tvg-language wins over country-based inference."""
    text = '#EXTM3U\n#EXTINF:-1 tvg-country="US" tvg-language="Spanish",Univision\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].language == "Spanish"


def test_language_empty_when_nothing_matches() -> None:
    """No language data at all → empty string."""
    text = '#EXTM3U\n#EXTINF:-1 group-title="Music",Random Stream\nhttp://x/1\n'
    result = parse_m3u(text)
    assert result.channels[0].language == ""


def test_parse_pls_entries_with_titles_and_relative_paths() -> None:
    text = """\
[playlist]
NumberOfEntries=2
File1=streams/news.mp3
Title1=Morning News
Length1=123
File2=https://example.com/live/channel.aac
Version=2
"""

    result = parse_pls(text, base_dir=Path("/lists"))

    assert result.skipped == 0
    assert [c.name for c in result.channels] == ["Morning News", "channel"]
    assert result.channels[0].url == str(Path("/lists/streams/news.mp3"))
    assert result.channels[0].duration == 123
    assert result.channels[1].url == "https://example.com/live/channel.aac"


def test_parse_playlist_text_selects_pls_by_location_suffix() -> None:
    result = parse_playlist_text(
        "File1=song.flac\nTitle1=Song\n",
        base_dir=Path("/music"),
        location="mix.pls",
    )

    assert len(result.channels) == 1
    assert result.channels[0].name == "Song"
    assert result.channels[0].url == str(Path("/music/song.flac"))


def test_local_pls_reference_is_treated_as_nested_playlist() -> None:
    result = parse_m3u("#EXTM3U\nother.pls\n", base_dir=Path("/lists"))

    assert result.channels == []
    assert result.skipped == 1
