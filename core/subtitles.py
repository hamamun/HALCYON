"""Online subtitle search and download — opensubtitles.com REST API v1.

One service, one home. The gear popover's *Download subtitles…* button and the
Settings dialog's *Online subtitles* section are two triggers for **this**
object; neither implements any of the behaviour itself (§4.1).

Design notes
------------
* **QtNetwork, not requests.** Phase 1 ships PySide6 and python-vlc and nothing
  else (``requests-phase1.txt``), and every call here is asynchronous anyway —
  a blocking HTTP round-trip on the GUI thread would stall the video.
* **The API key is the user's, never ours.** opensubtitles.com issues a free key
  per consumer; a key baked into the binary would be shared by every install and
  rate-limited into uselessness within a day. No key configured is a *state* the
  UI renders, not an error it hides.
* **Matching is a user choice, not a heuristic we guess at.**
  ``best`` returns only what the file hash (and failing that, a strict
  title/episode match) vouches for; ``all`` returns everything the query turned
  up, ordered so the plausible entries are still on top. Default is ``best``,
  because for a file you already have on disk the hash match is nearly always
  the right subtitle and a 50-row list is not an improvement.
* **Downloads are attached, not just saved.** ``downloadFinished`` carries the
  path; ``main.py`` wires it into the same ``add_slave`` route a dropped .srt
  takes, so there is one "subtitle this file" implementation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import struct
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QByteArray,
    QObject,
    QTimer,
    QUrl,
    QUrlQuery,
    Signal,
    Slot,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from core import paths

log = logging.getLogger(__name__)

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "Halcyon v0.1.0"

#: Match modes offered in Settings and in the search dialog.
MATCH_BEST = "best"
MATCH_ALL = "all"

#: Hard ceilings so a chatty query cannot flood the list view.
BEST_LIMIT = 12
ALL_LIMIT = 60

#: The languages opensubtitles.com actually carries in volume. Kept here rather
#: than in QML so the Settings combo and the search dialog's per-search combo
#: are provably the same list (§B.1).
LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt-BR", "Portuguese (BR)"),
    ("pt-PT", "Portuguese (PT)"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("fa", "Persian"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("bn", "Bengali"),
    ("ta", "Tamil"),
    ("ur", "Urdu"),
    ("id", "Indonesian"),
    ("ms", "Malay"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
    ("zh-CN", "Chinese (simplified)"),
    ("zh-TW", "Chinese (traditional)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("cs", "Czech"),
    ("sk", "Slovak"),
    ("hu", "Hungarian"),
    ("ro", "Romanian"),
    ("bg", "Bulgarian"),
    ("el", "Greek"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("no", "Norwegian"),
    ("hr", "Croatian"),
    ("sr", "Serbian"),
    ("sl", "Slovenian"),
]

#: Release-tag noise. Everything from the first of these onwards is dropped when
#: turning a filename into a search query, because "1080p" is not a film title
#: and sending it produces zero results rather than fewer.
_NOISE_RE = re.compile(
    r"\b("
    r"\d{3,4}p|4k|2160p|1080[ip]|720[ip]|480p|"
    r"x264|x265|h ?264|h ?265|hevc|avc|xvid|divx|"
    r"bluray|blu ray|bdrip|brrip|bdremux|remux|web ?dl|web ?rip|webrip|web|"
    r"hdrip|dvdrip|dvdscr|hdtv|pdtv|cam|ts|tc|hdr10|hdr|dv|sdr|"
    r"aac\d?|ac3|eac3|dts(?: ?hd)?|truehd|atmos|ddp?5 1|dd5 1|flac|mp3|opus|"
    r"\d ?ch|repack|proper|extended|uncut|remastered|limited|internal|multi|dual"
    r")\b.*",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_EPISODE_RE = re.compile(r"\bs(\d{1,2})[ ._-]?e(\d{1,3})\b", re.IGNORECASE)
_SEASON_WORD_RE = re.compile(
    r"\bseason[ ._-]?(\d{1,2})[ ._-]+episode[ ._-]?(\d{1,3})\b", re.IGNORECASE
)


# --------------------------------------------------------------------- hash ---
def opensubtitles_hash(path: str | Path) -> tuple[str, int]:
    """Return ``(hash, size)`` using OpenSubtitles' own 64-bit checksum.

    It is the file size plus every 64-bit word of the first and last 64 KiB,
    summed with wraparound. Cheap on any file size, and it is what makes a
    "this is the subtitle for *this exact release*" match possible at all —
    without it the server can only guess from the filename.

    Returns ``("", 0)`` for anything unreadable or shorter than 128 KiB rather
    than raising: a missing hash degrades the search to a title query, which is
    still useful.
    """
    chunk = 64 * 1024
    try:
        target = Path(path)
        size = target.stat().st_size
        if size < chunk * 2:
            return "", size if size > 0 else 0
        value = size
        with target.open("rb") as fh:
            for offset in (0, size - chunk):
                fh.seek(offset)
                buffer = fh.read(chunk)
                if len(buffer) < chunk:
                    return "", size
                for index in range(chunk // 8):
                    (word,) = struct.unpack_from("<q", buffer, index * 8)
                    value = (value + word) & 0xFFFFFFFFFFFFFFFF
        return f"{value:016x}", size
    except OSError:
        log.debug("could not hash %s", path, exc_info=True)
        return "", 0


# ------------------------------------------------------------------- query ---
def guess_query(path: str | Path) -> dict[str, Any]:
    """Turn a filename into search terms.

    ``Andor.S02E01.1080p.WEB-DL.x265-GRP.mkv`` becomes
    ``{"query": "andor", "season": 2, "episode": 1}``; a film keeps its year so
    two remakes do not collide.
    """
    stem = Path(str(path)).stem
    text = re.sub(r"[._]+", " ", stem)
    text = re.sub(r"\s*[\[(].*?[\])]\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    season = episode = 0
    match = _EPISODE_RE.search(text) or _SEASON_WORD_RE.search(text)
    if match:
        season, episode = int(match.group(1)), int(match.group(2))
        text = text[: match.start()].strip()

    year = 0
    if not season:
        years = _YEAR_RE.findall(text)
        if years:
            year = int(years[-1])

    text = _NOISE_RE.sub("", text).strip(" -_")
    if year:
        text = _YEAR_RE.sub("", text).strip(" -_")
    text = re.sub(r"\s+", " ", text).strip()

    return {
        "query": text.lower(),
        "season": season,
        "episode": episode,
        "year": year,
    }


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _norm(text).split() if len(t) > 2}


def rank_results(
    raw: list[dict],
    *,
    mode: str,
    query: dict[str, Any] | None = None,
    file_name: str = "",
) -> list[dict]:
    """Normalise, score and order the API payload.

    ``best`` keeps only what is defensible: a moviehash match, or — when the
    server returned none — an entry whose release name genuinely overlaps the
    file's own tokens and whose episode numbers agree. ``all`` keeps everything
    but still sorts hash matches to the top, so "show me everything" does not
    mean "show me a shuffled pile".
    """
    query = query or {}
    # Score against the *cleaned* title, not the raw filename. A filename's
    # tokens are mostly release noise ("1080p", "web", "x265", "group"), and
    # including them drags every overlap ratio below the threshold — so a
    # genuine title match scored the same as an unrelated show.
    wanted = _tokens(query.get("query", ""))
    if not wanted and file_name:
        wanted = _tokens(guess_query(file_name).get("query", ""))
    # Release tokens are a *bonus* signal, weighted separately below, so a
    # matching group or source nudges the order without setting the badge.
    release_hint = _tokens(guess_query(file_name).get("query", "")) if file_name else set()
    season, episode = int(query.get("season") or 0), int(query.get("episode") or 0)

    entries: list[dict] = []
    for item in raw or []:
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        first = files[0] if files else {}
        file_id = first.get("file_id")
        if not file_id:
            continue

        release = str(attrs.get("release") or first.get("file_name") or "Subtitle")
        feature = attrs.get("feature_details") or {}
        hash_match = bool(attrs.get("moviehash_match"))

        got = _tokens(release) | _tokens(feature.get("title") or "")
        overlap = len(wanted & got) / float(len(wanted)) if wanted else 0.0
        hint = len(release_hint & got) / float(len(release_hint)) if release_hint else 0.0

        # The episode numbers the *release name* carries are as good as the
        # feature metadata, and far more often present.
        release_meta = guess_query(release)
        release_season = int(feature.get("season_number") or release_meta["season"] or 0)
        release_episode = int(feature.get("episode_number") or release_meta["episode"] or 0)

        episode_ok = True
        if season and release_season:
            episode_ok = release_season == season
        if episode and release_episode:
            episode_ok = episode_ok and release_episode == episode

        downloads = int(attrs.get("download_count") or 0)
        ratings = float(attrs.get("ratings") or 0.0)

        if hash_match:
            match_kind, score = "hash", 1000.0
        elif episode_ok and overlap >= 0.6:
            match_kind, score = "title", 500.0 + overlap * 100.0 + hint * 20.0
        else:
            match_kind, score = "partial", overlap * 100.0 + hint * 20.0
        if not episode_ok:
            # Right show, wrong episode is worse than useless — it is a subtitle
            # that will play, out of sync, and look like a Halcyon bug.
            match_kind, score = "partial", min(score * 0.25, 50.0)
        # Popularity only ever breaks ties; it must never lift a partial above a
        # match, or the most-downloaded subtitle on the site wins every search.
        score += min(downloads, 100000) / 10000.0 + ratings

        entries.append(
            {
                "fileId": int(file_id),
                "subtitleId": str(attrs.get("subtitle_id") or item.get("id") or ""),
                "release": release,
                "fileName": str(first.get("file_name") or release),
                "language": str(attrs.get("language") or "").lower(),
                "title": str(feature.get("title") or feature.get("movie_name") or ""),
                "year": int(feature.get("year") or 0) if feature.get("year") else 0,
                "season": int(feature.get("season_number") or 0)
                if feature.get("season_number")
                else 0,
                "episode": int(feature.get("episode_number") or 0)
                if feature.get("episode_number")
                else 0,
                "downloads": downloads,
                "rating": round(ratings, 1),
                "fps": float(attrs.get("fps") or 0.0),
                "hearingImpaired": bool(attrs.get("hearing_impaired")),
                "trusted": bool(attrs.get("from_trusted")),
                "machineTranslated": bool(
                    attrs.get("machine_translated") or attrs.get("ai_translated")
                ),
                "uploader": str(((attrs.get("uploader") or {}).get("name")) or ""),
                "matchKind": match_kind,
                "score": round(score, 3),
            }
        )

    entries.sort(key=lambda e: e["score"], reverse=True)

    if mode == MATCH_BEST:
        exact = [e for e in entries if e["matchKind"] == "hash"]
        if not exact:
            exact = [e for e in entries if e["matchKind"] == "title"]
        if not exact:
            # Nothing vouched for; rather than an empty list, offer the few most
            # downloaded candidates and let the badge say they are partial.
            exact = entries[:5]
        return exact[:BEST_LIMIT]
    return entries[:ALL_LIMIT]


# ----------------------------------------------------------------- service ---
class SubtitleService(QObject):
    """QML-facing façade over opensubtitles.com."""

    resultsChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    configuredChanged = Signal()
    mediaChanged = Signal()
    quotaChanged = Signal()
    downloadFinished = Signal(str)          # local path of the saved subtitle
    errorOccurred = Signal(str)

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._net = QNetworkAccessManager(self)
        self._results: list[dict] = []
        self._status = ""
        self._busy = False
        self._quota = ""
        self._media_path = ""
        self._token = ""
        self._reply: QNetworkReply | None = None
        self._pending_download: dict | None = None
        settings.changed.connect(self._on_setting_changed)

    # ------------------------------------------------------------ config ---
    def _api_key(self) -> str:
        return str(self._settings.get("subs.online.apiKey", "") or "").strip()

    def _on_setting_changed(self, key: str, _value) -> None:
        if key == "subs.online.apiKey":
            self._token = ""            # a new key invalidates the session
            self.configuredChanged.emit()

    @Property(bool, notify=configuredChanged)
    def configured(self) -> bool:  # noqa: N802 - QML-facing
        return bool(self._api_key())

    @Property("QVariantList", constant=True)
    def languages(self) -> list:  # noqa: N802 - QML-facing
        return [{"code": code, "name": name} for code, name in LANGUAGES]

    @Property(str, notify=mediaChanged)
    def mediaPath(self) -> str:  # noqa: N802 - QML-facing
        return self._media_path

    @Property(str, notify=mediaChanged)
    def mediaName(self) -> str:  # noqa: N802 - QML-facing
        return Path(self._media_path).name if self._media_path else ""

    @Property("QVariantList", notify=resultsChanged)
    def results(self) -> list:  # noqa: N802 - QML-facing
        return self._results

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:  # noqa: N802 - QML-facing
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:  # noqa: N802 - QML-facing
        return self._status

    @Property(str, notify=quotaChanged)
    def quota(self) -> str:  # noqa: N802 - QML-facing
        return self._quota

    @Slot(str)
    def set_media(self, path: str) -> None:
        path = paths.normalise_path(path)
        if path == self._media_path:
            return
        self._media_path = path
        self._results = []
        self._status = ""
        self.mediaChanged.emit()
        self.resultsChanged.emit()
        self.statusChanged.emit()

    @Slot(result=str)
    def suggestedQuery(self) -> str:  # noqa: N802 - QML-facing
        if not self._media_path:
            return ""
        return guess_query(self._media_path).get("query", "")

    # ------------------------------------------------------------ search ---
    @Slot()
    @Slot(str)
    @Slot(str, str)
    @Slot(str, str, str)
    def search(self, query: str = "", language: str = "", mode: str = "") -> None:
        """Run a search. Empty arguments fall back to the saved preferences."""
        if self._busy:
            return
        if not self.configured:
            self._fail(
                "No OpenSubtitles API key yet — add one in Settings › Online subtitles."
            )
            return

        language = (language or str(self._settings.get("subs.online.language", "en"))).strip()
        mode = (mode or str(self._settings.get("subs.online.matchMode", MATCH_BEST))).strip()
        mode = MATCH_ALL if mode == MATCH_ALL else MATCH_BEST

        parsed = guess_query(self._media_path) if self._media_path else {}
        text = (query or parsed.get("query") or "").strip()
        digest, size = ("", 0)
        if self._media_path:
            digest, size = opensubtitles_hash(self._media_path)

        if not text and not digest:
            self._fail("Nothing to search for — play a file or type a title.")
            return

        url = QUrl(f"{API_BASE}/subtitles")
        params = QUrlQuery()
        if language:
            params.addQueryItem("languages", language)
        if digest:
            params.addQueryItem("moviehash", digest)
            # In 'best' the server may pre-filter to hash matches; in 'all' we
            # explicitly ask it not to, which is the whole difference the user
            # sees between the two modes.
            params.addQueryItem(
                "moviehash_match", "only" if mode == MATCH_BEST else "include"
            )
        if text:
            params.addQueryItem("query", text)
        if parsed.get("season"):
            params.addQueryItem("season_number", str(parsed["season"]))
        if parsed.get("episode"):
            params.addQueryItem("episode_number", str(parsed["episode"]))
        if parsed.get("year"):
            params.addQueryItem("year", str(parsed["year"]))
        params.addQueryItem("order_by", "download_count")
        params.addQueryItem("order_direction", "desc")
        url.setQuery(params)

        self._set_busy(True)
        self._set_status("Searching OpenSubtitles\u2026")
        request = self._request(url)
        reply = self._net.get(request)
        self._reply = reply
        reply.finished.connect(
            lambda: self._on_search_finished(
                reply, mode=mode, parsed=parsed, language=language, size=size
            )
        )

    def _on_search_finished(self, reply, *, mode, parsed, language, size) -> None:
        self._reply = None
        payload = self._read(reply)
        if payload is None:
            self._set_busy(False)
            return
        entries = rank_results(
            payload.get("data") or [],
            mode=mode,
            query=parsed,
            file_name=Path(self._media_path).name if self._media_path else "",
        )
        self._results = entries
        self.resultsChanged.emit()
        self._set_busy(False)
        if not entries:
            self._set_status(
                "No subtitles found."
                + (
                    "  Try \u201cAll results\u201d, or a different language."
                    if mode == MATCH_BEST
                    else "  Try a shorter title."
                )
            )
        else:
            hashed = sum(1 for e in entries if e["matchKind"] == "hash")
            self._set_status(
                f"{len(entries)} result{'s' if len(entries) != 1 else ''}"
                + (f" \u00b7 {hashed} exact match" + ("es" if hashed != 1 else "") if hashed else "")
            )

    # ---------------------------------------------------------- download ---
    @Slot(int)
    def download(self, file_id: int) -> None:
        if self._busy:
            return
        if not self.configured:
            self._fail("No OpenSubtitles API key yet — add one in Settings.")
            return
        entry = next((e for e in self._results if e["fileId"] == int(file_id)), None)
        self._pending_download = entry or {"fileId": int(file_id), "language": ""}
        self._set_busy(True)
        self._set_status("Requesting download link\u2026")

        username = str(self._settings.get("subs.online.username", "") or "").strip()
        password = str(self._settings.get("subs.online.password", "") or "")
        if username and password and not self._token:
            self._login(username, password, then=lambda: self._request_link(int(file_id)))
            return
        self._request_link(int(file_id))

    def _login(self, username: str, password: str, then) -> None:
        request = self._request(QUrl(f"{API_BASE}/login"))
        body = QByteArray(json.dumps({"username": username, "password": password}).encode())
        reply = self._net.post(request, body)

        def done() -> None:
            payload = self._read(reply, soft=True)
            if payload and payload.get("token"):
                self._token = str(payload["token"])
            else:
                # A bad account is not fatal: anonymous downloads still work,
                # just with the smaller daily quota.
                log.info("opensubtitles login failed — continuing anonymously")
            then()

        reply.finished.connect(done)

    def _request_link(self, file_id: int) -> None:
        request = self._request(QUrl(f"{API_BASE}/download"))
        body = QByteArray(json.dumps({"file_id": int(file_id)}).encode())
        reply = self._net.post(request, body)
        reply.finished.connect(lambda: self._on_link(reply))

    def _on_link(self, reply) -> None:
        payload = self._read(reply)
        if payload is None:
            self._set_busy(False)
            return
        link = str(payload.get("link") or "")
        if not link:
            self._set_busy(False)
            self._fail(str(payload.get("message") or "OpenSubtitles returned no link."))
            return
        remaining = payload.get("remaining")
        if remaining is not None:
            self._quota = f"{remaining} download{'s' if remaining != 1 else ''} left today"
            self.quotaChanged.emit()
        name = str(payload.get("file_name") or "")
        self._set_status("Downloading\u2026")
        fetch = self._net.get(QNetworkRequest(QUrl(link)))
        fetch.finished.connect(lambda: self._on_file(fetch, name))

    def _on_file(self, reply, suggested_name: str) -> None:
        self._set_busy(False)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail(f"Download failed: {reply.errorString()}")
            reply.deleteLater()
            return
        data = bytes(reply.readAll().data())
        reply.deleteLater()
        if not data:
            self._fail("Download returned an empty file.")
            return
        try:
            target = self._save(data, suggested_name)
        except OSError as exc:
            self._fail(f"Could not save the subtitle: {exc}")
            return
        self._set_status(f"Loaded {target.name}")
        self.downloadFinished.emit(str(target))

    def _save(self, data: bytes, suggested_name: str) -> Path:
        entry = self._pending_download or {}
        language = str(entry.get("language") or "")
        suffix = Path(suggested_name).suffix.lower() or ".srt"
        if suffix not in (".srt", ".ass", ".ssa", ".sub", ".vtt"):
            suffix = ".srt"

        media = Path(self._media_path) if self._media_path else None
        alongside = bool(self._settings.get("subs.online.saveAlongsideMedia", True))
        if media and alongside and os.access(media.parent, os.W_OK):
            stem = media.stem + (f".{language}" if language else "")
            target = media.parent / f"{stem}{suffix}"
        else:
            folder = paths.cache_dir() / "subtitles"
            folder.mkdir(parents=True, exist_ok=True)
            base = (media.stem if media else Path(suggested_name).stem) or "subtitle"
            target = folder / f"{base}{('.' + language) if language else ''}{suffix}"

        # Never clobber a subtitle the user already has.
        counter = 2
        while target.exists():
            target = target.with_name(f"{target.stem}.{counter}{suffix}")
            counter += 1
        target.write_bytes(data)
        log.info("saved subtitle %s", target)
        return target

    # ------------------------------------------------------------- plumbing ---
    def _request(self, url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setRawHeader(b"Api-Key", self._api_key().encode())
        request.setRawHeader(b"User-Agent", USER_AGENT.encode())
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Content-Type", b"application/json")
        if self._token:
            request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        return request

    def _read(self, reply, *, soft: bool = False) -> dict | None:
        """Decode one JSON reply, turning every failure into a readable line."""
        try:
            status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
            raw = bytes(reply.readAll().data())
        finally:
            reply.deleteLater()

        if reply.error() != QNetworkReply.NetworkError.NoError and not raw:
            if not soft:
                self._fail(f"Network error: {reply.errorString()}")
            return None
        try:
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except json.JSONDecodeError:
            if not soft:
                self._fail("OpenSubtitles sent a response Halcyon could not read.")
            return None
        if not isinstance(payload, dict):
            payload = {"data": payload}
        if status >= 400:
            if not soft:
                self._fail(_http_message(status, payload))
            return None
        return payload

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit()

    def _set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _fail(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message)
        self.errorOccurred.emit(message)
        log.info("subtitle search: %s", message)

    @Slot()
    def clear(self) -> None:
        self._results = []
        self._status = ""
        self.resultsChanged.emit()
        self.statusChanged.emit()


def _http_message(status: int, payload: dict) -> str:
    detail = str(payload.get("message") or payload.get("errors") or "").strip()
    known = {
        401: "OpenSubtitles rejected the API key — check it in Settings.",
        403: "OpenSubtitles refused the request (403).",
        406: "Download quota reached for today.",
        429: "Too many requests — wait a moment and try again.",
        502: "OpenSubtitles is unreachable right now.",
        503: "OpenSubtitles is unreachable right now.",
    }
    base = known.get(status, f"OpenSubtitles returned HTTP {status}.")
    return f"{base} {detail}".strip()


def install_debounce(service: SubtitleService, ms: int = 250) -> QTimer:
    """Small helper for callers that want to coalesce rapid searches."""
    timer = QTimer(service)
    timer.setSingleShot(True)
    timer.setInterval(ms)
    return timer
