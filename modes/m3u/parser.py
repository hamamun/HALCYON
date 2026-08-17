"""M3U/M3U8/PLS playlist parsing — Milestone 2.1 (§P2.4).

Pure Python, deliberately Qt-free, so the parser is unit-testable without a
display (and on any box): bytes in, channels out.

What this understands:

* the ``#EXTM3U`` header line
* ``#EXTINF`` with a duration and the common ``tvg-*`` attributes
  (``tvg-id``, ``tvg-name``, ``tvg-logo``, ``tvg-country``,
  ``tvg-language``) plus ``group-title``
* ``#EXTGRP`` as a fallback group
* Winamp-style ``.pls`` files: ``FileN=``, ``TitleN=`` and ``LengthN=``
* plain entries without an ``#EXTINF`` (the URL's file name becomes the title)
* local paths — absolute, ``~``-relative and playlist-relative — and remote
  ``http(s)://`` entries, left untouched
* UTF-8 with or without BOM, Latin-1 fallback (a lot of IPTV lists are not
  UTF-8, however loudly they claim to be)
* malformed lines: skipped and counted, never fatal
* nested playlist references (``.m3u`` / ``.m3u8`` / ``.pls`` URLs, including
  HLS master playlists): explicitly ignored and counted — a playlist is a
  document you load, not a channel you play
* **country resolution** — when ``tvg-country`` is missing, the parser tries
  four fallback strategies (tvg-id pattern, group-title splitting, title
  pattern) to extract an ISO country code and maps it to a readable name.
* **language resolution** — when ``tvg-language`` is missing, the parser
  falls back to the resolved country's primary language.

Remote playlists are fetched with the standard library only (§P2.4 — no new
dependency).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

#: Fetch guard rails for remote playlists (§P2.4: failure must never hang or
#: crash the panel).
FETCH_TIMEOUT_S = 20
FETCH_MAX_BYTES = 32 * 1024 * 1024  # 32 MB — generous for a text playlist
USER_AGENT = "Halcyon/0.2 (+https://github.com/hamamun/HALCYON)"

_EXTINF_RE = re.compile(r"^#EXTINF\s*:\s*(-?\d+(?:\.\d+)?)?\s*(.*?),(.*)$", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z0-9\-_]+)\s*=\s*"([^"]*)"')
#: HLS variant directives — a master playlist's stream list, not a channel.
_HLS_VARIANT_RE = re.compile(r"^#EXT-X-(STREAM-INF|MEDIA)\b", re.IGNORECASE)
_PLAYLIST_EXT = {".m3u", ".m3u8", ".pls"}
_PLS_ENTRY_RE = re.compile(r"^(file|title|length)(\d+)\s*=\s*(.*)$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Country resolution lookup tables
# ---------------------------------------------------------------------------

#: ISO 3166-1 alpha-2 country codes → readable names.  Used by the country
#: resolver to turn a 2-letter code into something human-friendly.
_ISO2_COUNTRY_NAMES: dict[str, str] = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AD": "Andorra",
    "AO": "Angola", "AR": "Argentina", "AM": "Armenia", "AU": "Australia",
    "AT": "Austria", "AZ": "Azerbaijan", "BS": "Bahamas", "BH": "Bahrain",
    "BD": "Bangladesh", "BY": "Belarus", "BE": "Belgium", "BZ": "Belize",
    "BJ": "Benin", "BO": "Bolivia", "BA": "Bosnia", "BW": "Botswana",
    "BR": "Brazil", "BN": "Brunei", "BG": "Bulgaria", "BF": "Burkina Faso",
    "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "CR": "Costa Rica", "HR": "Croatia",
    "CU": "Cuba", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark",
    "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt",
    "SV": "El Salvador", "GQ": "Equatorial Guinea", "EE": "Estonia",
    "ET": "Ethiopia", "FI": "Finland", "FR": "France", "GA": "Gabon",
    "GM": "Gambia", "GE": "Georgia", "DE": "Germany", "GH": "Ghana",
    "GR": "Greece", "GT": "Guatemala", "GN": "Guinea", "HT": "Haiti",
    "HN": "Honduras", "HK": "Hong Kong", "HU": "Hungary", "IS": "Iceland",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IQ": "Iraq",
    "IE": "Ireland", "IL": "Israel", "IT": "Italy", "JM": "Jamaica",
    "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan", "KE": "Kenya",
    "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos", "LV": "Latvia",
    "LB": "Lebanon", "LY": "Libya", "LI": "Liechtenstein", "LT": "Lithuania",
    "LU": "Luxembourg", "MK": "North Macedonia", "MY": "Malaysia",
    "ML": "Mali", "MT": "Malta", "MX": "Mexico", "MD": "Moldova",
    "MC": "Monaco", "MN": "Mongolia", "ME": "Montenegro", "MA": "Morocco",
    "MZ": "Mozambique", "MM": "Myanmar", "NA": "Namibia", "NP": "Nepal",
    "NL": "Netherlands", "NZ": "New Zealand", "NI": "Nicaragua", "NE": "Niger",
    "NG": "Nigeria", "KP": "North Korea", "NO": "Norway", "OM": "Oman",
    "PK": "Pakistan", "PA": "Panama", "PY": "Paraguay", "PE": "Peru",
    "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "QA": "Qatar",
    "RO": "Romania", "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia",
    "SN": "Senegal", "RS": "Serbia", "SG": "Singapore", "SK": "Slovakia",
    "SI": "Slovenia", "SO": "Somalia", "ZA": "South Africa", "KR": "South Korea",
    "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan", "SE": "Sweden",
    "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan", "TJ": "Tajikistan",
    "TZ": "Tanzania", "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey",
    "TM": "Turkmenistan", "UG": "Uganda", "UA": "Ukraine",
    "AE": "United Arab Emirates", "GB": "United Kingdom", "UK": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia",
    "ZW": "Zimbabwe", "INT": "International",
}

#: Words that appear in group-title segments but are NOT country codes.
#: The country resolver skips these when splitting group-title by delimiters.
_M3U_CATEGORY_HINTS: frozenset[str] = frozenset({
    "SPORTS", "SPORT", "NEWS", "MOVIES", "MOVIE", "MUSIC", "KIDS", "CHILDREN",
    "ENTERTAINMENT", "ENT", "DOCUMENTARY", "DOCS", "COMEDY", "DRAMA", "FILMS",
    "GENERAL", "LIFESTYLE", "FOOD", "TRAVEL", "SCIENCE", "TECH", "TECHNOLOGY",
    "MOVIES", "SERIES", "ANIME", "CARTOON", "RELIGION", "CLASSIC", "CLASSICS",
    "LOCAL", "NATIONAL", "REGIONAL", "WORLD", "INTERNATIONAL", "LATINO",
    "LATIN", "HD", "SD", "FHD", "4K", "UHD", "VIP", "PREMIUM", "ADULT",
    "XXX", "LIVE", "RADIO", "VOD", "CATCHUP", "EPG", "TV", "TV SHOWS",
    "SHOPPING", "WEATHER", "AUTO", "BUSINESS", "FINANCE", "EDUCATION",
    "FASHION", "HISTORY", "NATURE", "OUTDOOR", "GAMING", "ANIMATION",
    "CULTURE", "ARTS", "RELIGIOUS", "SPIRITUAL", "MOTORS", "FOOTBALL",
    "CRICKET", "TENNIS", "GOLF", "RUGBY", "BOXING", "MMA", "UFC",
})

#: ISO 3166-1 alpha-2 → primary language (ISO 639-1 name, capitalised).
#: Used by the language resolver as a fallback when ``tvg-language`` is absent.
_COUNTRY_TO_LANGUAGE: dict[str, str] = {
    "AF": "Pashto", "AL": "Albanian", "DZ": "Arabic", "AD": "Catalan",
    "AO": "Portuguese", "AR": "Spanish", "AM": "Armenian", "AU": "English",
    "AT": "German", "AZ": "Azerbaijani", "BS": "English", "BH": "Arabic",
    "BD": "Bengali", "BY": "Belarusian", "BE": "Dutch", "BZ": "English",
    "BJ": "French", "BO": "Spanish", "BA": "Bosnian", "BW": "English",
    "BR": "Portuguese", "BN": "Malay", "BG": "Bulgarian", "BF": "French",
    "KH": "Khmer", "CM": "French", "CA": "English", "CL": "Spanish",
    "CN": "Chinese", "CO": "Spanish", "CR": "Spanish", "HR": "Croatian",
    "CU": "Spanish", "CY": "Greek", "CZ": "Czech", "DK": "Danish",
    "DO": "Spanish", "EC": "Spanish", "EG": "Arabic", "SV": "Spanish",
    "GQ": "Spanish", "EE": "Estonian", "ET": "Amharic", "FI": "Finnish",
    "FR": "French", "GA": "French", "GM": "English", "GE": "Georgian",
    "DE": "German", "GH": "English", "GR": "Greek", "GT": "Spanish",
    "GN": "French", "HT": "French", "HN": "Spanish", "HK": "Chinese",
    "HU": "Hungarian", "IS": "Icelandic", "IN": "Hindi", "ID": "Indonesian",
    "IR": "Persian", "IQ": "Arabic", "IE": "English", "IL": "Hebrew",
    "IT": "Italian", "JM": "English", "JP": "Japanese", "JO": "Arabic",
    "KZ": "Kazakh", "KE": "Swahili", "KW": "Arabic", "KG": "Kyrgyz",
    "LA": "Lao", "LV": "Latvian", "LB": "Arabic", "LY": "Arabic",
    "LI": "German", "LT": "Lithuanian", "LU": "French", "MK": "Macedonian",
    "MY": "Malay", "ML": "French", "MT": "Maltese", "MX": "Spanish",
    "MD": "Romanian", "MC": "French", "MN": "Mongolian", "ME": "Montenegrin",
    "MA": "Arabic", "MZ": "Portuguese", "MM": "Burmese", "NA": "English",
    "NP": "Nepali", "NL": "Dutch", "NZ": "English", "NI": "Spanish",
    "NE": "French", "NG": "English", "KP": "Korean", "NO": "Norwegian",
    "OM": "Arabic", "PK": "Urdu", "PA": "Spanish", "PY": "Spanish",
    "PE": "Spanish", "PH": "Filipino", "PL": "Polish", "PT": "Portuguese",
    "QA": "Arabic", "RO": "Romanian", "RU": "Russian", "RW": "Kinyarwanda",
    "SA": "Arabic", "SN": "French", "RS": "Serbian", "SG": "English",
    "SK": "Slovak", "SI": "Slovene", "SO": "Somali", "ZA": "English",
    "KR": "Korean", "ES": "Spanish", "LK": "Sinhala", "SD": "Arabic",
    "SE": "Swedish", "CH": "German", "SY": "Arabic", "TW": "Chinese",
    "TJ": "Tajik", "TZ": "Swahili", "TH": "Thai", "TN": "Arabic",
    "TR": "Turkish", "TM": "Turkmen", "UG": "English", "UA": "Ukrainian",
    "AE": "Arabic", "GB": "English", "UK": "English", "US": "English",
    "UY": "Spanish", "UZ": "Uzbek", "VE": "Spanish", "VN": "Vietnamese",
    "YE": "Arabic", "ZM": "English", "ZW": "English",
}

# ---------------------------------------------------------------------------
# Country attribute names (strategy 1) — all the variants we recognise.
# The parser collects whichever of these is present.
# ---------------------------------------------------------------------------
_COUNTRY_ATTR_NAMES: tuple[str, ...] = (
    "tvg-country", "country", "nation", "tvg-nation", "region", "tvg-region",
)

# Regex helpers for country extraction from tvg-id and title.
_TVG_ID_COUNTRY_RE = re.compile(r"[.@]([A-Za-z]{2})(?:[@\s]|$)")
_TITLE_BRACKET_COUNTRY_RE = re.compile(r"^\[([A-Za-z]{2})\]")
_TITLE_PREFIX_COUNTRY_RE = re.compile(r"^([A-Za-z]{2})\s*[:\-–—]\s*")
_GROUP_SPLIT_RE = re.compile(r"\s*[|/;,–—\-]\s*")


def _normalise_country_code(code: str) -> str:
    """Turn a 2-letter ISO code into a readable name.  Returns the uppercase
    code as-is when it's not in our lookup table."""
    upper = code.upper().strip()
    if not upper or len(upper) > 3:
        return ""
    return _ISO2_COUNTRY_NAMES.get(upper, upper)


def _resolve_country(
    name: str,
    tvg_id: str,
    group: str,
    raw_country: str,
) -> str:
    """Four-strategy country resolution (tried in order):

    1. Explicit country attributes (already collected as *raw_country*)
    2. ``tvg-id`` pattern — e.g. ``BBC.uk`` → United Kingdom
    3. ``group-title`` splitting — e.g. ``UK | Sports`` → United Kingdom
    4. Channel title pattern — e.g. ``[UK] BBC`` or ``UK: CNN``

    Returns a readable country name, or ``""`` when nothing matches.
    """
    # Strategy 1: explicit attribute
    if raw_country.strip():
        val = raw_country.strip()
        # Could be a 2-letter code or already a name
        if len(val) <= 3 and val.isalpha():
            return _normalise_country_code(val)
        return val

    # Strategy 2: tvg-id pattern (e.g. "bbc1.uk", "CNN.us@East")
    if tvg_id:
        m = _TVG_ID_COUNTRY_RE.search(tvg_id)
        if m:
            code = m.group(1).upper()
            if code in _ISO2_COUNTRY_NAMES:
                return _ISO2_COUNTRY_NAMES[code]

    # Strategy 3: group-title splitting
    if group:
        parts = _GROUP_SPLIT_RE.split(group)
        for part in parts:
            stripped = part.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if upper in _M3U_CATEGORY_HINTS:
                continue
            if len(stripped) == 2 and stripped.isalpha():
                code = stripped.upper()
                if code in _ISO2_COUNTRY_NAMES:
                    return _ISO2_COUNTRY_NAMES[code]

    # Strategy 4: title pattern (e.g. "[UK] BBC" or "UK: CNN")
    if name:
        m = _TITLE_BRACKET_COUNTRY_RE.match(name)
        if m:
            code = m.group(1).upper()
            if code in _ISO2_COUNTRY_NAMES:
                return _ISO2_COUNTRY_NAMES[code]
        m = _TITLE_PREFIX_COUNTRY_RE.match(name)
        if m:
            code = m.group(1).upper()
            if code in _ISO2_COUNTRY_NAMES:
                return _ISO2_COUNTRY_NAMES[code]

    return ""


def _resolve_language(
    raw_language: str,
    resolved_country: str,
) -> str:
    """Resolve the channel's language:

    1. Explicit ``tvg-language`` attribute if present
    2. Reverse-lookup from the resolved country (e.g. "Germany" → "German")

    Returns ``""`` when nothing matches.
    """
    if raw_language.strip():
        return raw_language.strip()
    if resolved_country:
        # Try exact match first
        lang = _COUNTRY_TO_LANGUAGE.get(resolved_country)
        if lang:
            return lang
        # Try matching by ISO code (e.g. country might be "DE" or "Germany")
        for code, lang_name in _COUNTRY_TO_LANGUAGE.items():
            if (code.upper() == resolved_country.upper()
                    or _ISO2_COUNTRY_NAMES.get(code.upper(), "") == resolved_country):
                return lang_name
    return ""


@dataclass
class Channel:
    """One playable entry. Everything except ``name`` and ``url`` is optional
    metadata — real-world playlists are stingy with it."""

    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    country: str = ""
    language: str = ""
    duration: float = -1.0

    @property
    def is_remote(self) -> bool:
        return self.url.startswith(("http://", "https://"))


@dataclass
class ParseResult:
    channels: list[Channel]
    #: Entries dropped as malformed (bad line, EXTINF with no URL) or ignored
    #: (nested playlist references). Surfaced in the UI as "N skipped".
    skipped: int = 0


def decode_playlist(data: bytes) -> str:
    """Best-effort text decode: UTF-8 with BOM first, strict UTF-8, then the
    Latin-1 floor — which never fails, since every byte is a character."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def looks_like_playlist_ref(url: str) -> bool:
    """True when an entry points at another playlist rather than at media."""
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return any(path.endswith(ext) for ext in _PLAYLIST_EXT)


def _attrs(raw: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in _ATTR_RE.finditer(raw)}


def _title_from_url(url: str) -> str:
    """A human label for entries that carry no EXTINF title: the file name
    without extension; the path tail as-is when it carries no dot; the host
    when a stream URL has no path at all."""
    path = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if is_url(url):
        after_scheme = path.split("//", 1)[-1]
        if "/" not in after_scheme:                      # host only, no path
            return after_scheme.split(":", 1)[0] or url
    tail = path.rsplit("/", 1)[-1] if "/" in path else path
    if "." in tail:
        stem = tail.rpartition(".")[0]
        if stem:
            return stem
    return tail or url


def _resolve_entry_url(url: str, base_dir: Path | None) -> str:
    """Playlist-relative local paths resolve against the playlist's own folder
    (§2.1: relative and absolute paths). Remote URLs pass through untouched."""
    if is_url(url):
        return url
    candidate = Path(url).expanduser()
    if candidate.is_absolute() or base_dir is None:
        return str(candidate)
    return str(base_dir / candidate)


def parse_m3u(text: str, base_dir: Path | None = None) -> ParseResult:
    """Parse playlist *text* into channels. ``base_dir`` is the folder a local
    playlist file lives in, used to resolve relative entry paths."""
    channels: list[Channel] = []
    skipped = 0

    pending: dict | None = None  # the last EXTINF seen, waiting for its URL
    pending_group = ""           # EXTGRP is a fallback for the next entry only

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF"):
            if pending is not None:
                skipped += 1   # an EXTINF that never received its URL
                pending = None
            match = _EXTINF_RE.match(line)
            if not match:
                skipped += 1
                pending = None
                continue
            duration_s, attrs_raw, title = match.groups()
            attrs = _attrs(attrs_raw)
            try:
                duration = float(duration_s) if duration_s else -1.0
            except ValueError:
                duration = -1.0
            # EXTGRP survives until its entry's URL arrives — it is the
            # fallback for THIS next entry, cleared once the entry exists.
            # Collect all country-related attributes for the resolver.
            raw_country = ""
            for attr_name in _COUNTRY_ATTR_NAMES:
                val = attrs.get(attr_name, "")
                if val.strip():
                    raw_country = val
                    break
            pending = {
                "name": (title or "").strip()
                        or attrs.get("tvg-name", ""),
                "group": attrs.get("group-title", ""),
                "logo": attrs.get("tvg-logo", ""),
                "tvg_id": attrs.get("tvg-id", ""),
                "raw_country": raw_country,
                "raw_language": attrs.get("tvg-language", ""),
                "duration": duration,
            }
            continue

        if line.startswith("#EXTGRP"):
            pending_group = line.partition(":")[2].strip()
            continue

        if _HLS_VARIANT_RE.match(line):
            # Inside a master HLS playlist: its variant URLs are streams of one
            # video, not channels. The nested-playlist check below drops them.
            skipped += 1
            continue

        if line.startswith("#"):
            # Unknown directive (#EXT-X-*, #PLAYLIST, #EXTVLCOPT...) — harmless.
            continue

        # A URL/path line belongs to the pending EXTINF, if any.
        url = _resolve_entry_url(line, base_dir)
        # Nested-playlist skip (§2.1): LOCAL references only. A remote .m3u8
        # URL is almost always the channel itself (HLS) — dropping those would
        # erase nearly every real IPTV list.
        if not is_url(url) and looks_like_playlist_ref(url):
            skipped += 1
            pending = None
            pending_group = ""
            continue

        if pending is None:
            channel = Channel(name=_title_from_url(line), url=url)
        else:
            # Resolve country (4 strategies) then language (fallback from country).
            resolved_country = _resolve_country(
                name=pending["name"],
                tvg_id=pending["tvg_id"],
                group=pending["group"],
                raw_country=pending["raw_country"],
            )
            resolved_language = _resolve_language(
                raw_language=pending["raw_language"],
                resolved_country=resolved_country,
            )
            channel = Channel(
                name=pending["name"] or _title_from_url(line),
                url=url,
                group=pending["group"] or pending_group,
                logo=pending["logo"],
                tvg_id=pending["tvg_id"],
                country=resolved_country,
                language=resolved_language,
                duration=pending["duration"],
            )
        channels.append(channel)
        pending = None
        pending_group = ""

    if pending is not None:
        # File ended on an EXTINF that never got a URL — malformed.
        skipped += 1

    return ParseResult(channels=channels, skipped=skipped)


def parse_pls(text: str, base_dir: Path | None = None) -> ParseResult:
    """Parse a Winamp/Shoutcast ``.pls`` playlist into channels.

    PLS is an INI-like format, but real files are often loose about section
    names, ordering and missing ``NumberOfEntries``.  We therefore collect every
    ``FileN`` entry we see, attach optional ``TitleN``/``LengthN`` metadata, and
    skip entries with no playable file/URL instead of failing the whole list.
    """
    entries: dict[int, dict[str, str]] = {}
    malformed = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        if "=" not in line:
            malformed += 1
            continue
        match = _PLS_ENTRY_RE.match(line)
        if not match:
            # NumberOfEntries, Version and other harmless keys.
            continue
        key, index_s, value = match.groups()
        try:
            index = int(index_s)
        except ValueError:
            malformed += 1
            continue
        entries.setdefault(index, {})[key.lower()] = value.strip()

    channels: list[Channel] = []
    skipped = malformed
    for index in sorted(entries):
        entry = entries[index]
        raw_url = entry.get("file", "").strip()
        if not raw_url:
            skipped += 1
            continue
        url = _resolve_entry_url(raw_url, base_dir)
        if not is_url(url) and looks_like_playlist_ref(url):
            skipped += 1
            continue
        try:
            duration = float(entry.get("length", "-1") or -1)
        except ValueError:
            duration = -1.0
        title = entry.get("title", "").strip() or _title_from_url(raw_url)
        channels.append(Channel(name=title, url=url, duration=duration))

    return ParseResult(channels=channels, skipped=skipped)


def _playlist_suffix(location: str | Path | None) -> str:
    if location is None:
        return ""
    text = str(location).split("?", 1)[0].split("#", 1)[0]
    return Path(text).suffix.lower()


def parse_playlist_text(
    text: str,
    *,
    base_dir: Path | None = None,
    location: str | Path | None = None,
) -> ParseResult:
    """Parse playlist text, selecting M3U or PLS by ``location`` suffix."""
    if _playlist_suffix(location) == ".pls":
        return parse_pls(text, base_dir=base_dir)
    return parse_m3u(text, base_dir=base_dir)


def read_playlist(path: Path) -> str:
    """Read a local playlist file as text (encoding detected)."""
    return decode_playlist(Path(path).expanduser().read_bytes())


def fetch_playlist(url: str) -> str:
    """Download a remote playlist with the standard library (§P2.4).

    Failures arrive as RuntimeError with a message fit for the panel — the
    caller never sees a traceback, the user never sees a stack dump.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            data = response.read(FETCH_MAX_BYTES + 1)
    except HTTPError as exc:
        raise RuntimeError(f"server answered {exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"could not reach the playlist ({reason})") from exc
    except TimeoutError as exc:
        raise RuntimeError("the connection timed out") from exc
    if len(data) > FETCH_MAX_BYTES:
        raise RuntimeError("playlist is larger than 32 MB — refusing to load it")
    return decode_playlist(data)


def load_playlist(location: str) -> tuple[ParseResult, Path | None]:
    """Load a playlist from a local path or a remote URL.

    Returns the parsed result and the base directory used for relative entries
    (``None`` for remote playlists — relative entries there stay as written).
    """
    if is_url(location):
        return parse_playlist_text(fetch_playlist(location), location=location), None
    path = Path(location).expanduser()
    return parse_playlist_text(read_playlist(path), base_dir=path.parent, location=path), path.parent
