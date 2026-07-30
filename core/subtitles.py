"""OpenSubtitles search & download — the behaviour behind the download flyout.

Visuals live in ``ui/transport/SubtitleDownloadDialog.qml``; this object is
what it talks to (QML context property ``Subs``). The split keeps every rule
of §4.1: one implementation of "find a subtitle online", one of "save it next
to the media", regardless of which trigger the UI grows later.

Two rules shape the whole file:

* **The GUI thread never waits on the network.** Every request runs on a
  short-lived :class:`QThread`; results come back through queued signals, which
  Qt delivers on the GUI thread, and only the GUI thread mutates the exposed
  state. A thread crash can therefore never wedge the player.
* **No new dependency.** The REST calls are plain HTTPS via stdlib ``urllib`` —
  Phase 1's requirement list stays exactly as shipped (README).

Only the thin helpers near the bottom know about HTTP; everything above them
is pure and unit-tested without a socket in sight.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Property, QObject, QThread, Signal, Slot

log = logging.getLogger(__name__)

_API_BASE = "https://api.opensubtitles.com/api/v1"
#: OpenSubtitles asks consumers for an identifying UA; the pattern is
#: "AppName vX.Y".
_USER_AGENT = "Halcyon v0.1.0"
_HTTP_TIMEOUT = 15

#: Suffixes the auto-sidecar loader (and VLC's own subtitle demuxer) accepts.
#: A suffix outside this set would save a file nothing ever reloads, so the
#: wire's extension is only trusted when it is in it.
_SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".sub", ".vtt"}


class _Job(QThread):
    """One unit of blocking work, reporting back over a queued signal."""

    done = Signal(object)

    def __init__(self, work, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            self.done.emit(self._work())
        except Exception as exc:  # a worker must never die silently
            log.exception("subtitle download job failed")
            self.done.emit(("error", f"Unexpected error: {exc}"))


class SubtitleBackend(QObject):
    """QML facade ``Subs``: state + search/download slots for the flyout."""

    searchingChanged = Signal()
    resultsChanged = Signal()
    statusChanged = Signal()
    busyIndexChanged = Signal()
    apiKeyChanged = Signal()
    languagesChanged = Signal()
    mediaNameChanged = Signal()

    def __init__(
        self,
        settings,
        controller,
        transport=None,
        transport_bytes=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        #: Injectable so tests run the whole state machine without a socket.
        self._transport = transport or _default_transport
        self._transport_bytes = transport_bytes or _default_transport_bytes

        self._searching = False
        self._busy_index = -1
        self._results: list[dict] = []   # ranked, each carrying a stable ``idx``
        self._best: list[dict] = []
        self._others: list[dict] = []
        self._status = ""
        self._status_is_error = False

        self._jobs: list[_Job] = []
        #: Bumped on every search/download so a slow stale reply can never
        #: overwrite a newer one's state.
        self._search_seq = 0
        self._download_seq = 0

        if hasattr(controller, "mediaNameChanged"):
            controller.mediaNameChanged.connect(self.mediaNameChanged)

    # --------------------------------------------------------- properties ---
    def _get_searching(self) -> bool:
        return self._searching

    searching = Property(bool, _get_searching, notify=searchingChanged)

    def _get_busy_index(self) -> int:
        return self._busy_index

    busyIndex = Property(int, _get_busy_index, notify=busyIndexChanged)  # noqa: N802

    def _get_best(self) -> list:
        return self._best

    bestResults = Property("QVariantList", _get_best, notify=resultsChanged)  # noqa: N802

    def _get_others(self) -> list:
        return self._others

    otherResults = Property("QVariantList", _get_others, notify=resultsChanged)  # noqa: N802

    def _get_status(self) -> str:
        return self._status

    status = Property(str, _get_status, notify=statusChanged)

    def _get_status_is_error(self) -> bool:
        return self._status_is_error

    statusIsError = Property(bool, _get_status_is_error, notify=statusChanged)  # noqa: N802

    def _get_api_key(self) -> str:
        return str(self._settings.get("subs.openSubtitlesApiKey", "") or "").strip()

    def _set_api_key(self, value: str) -> None:
        value = (value or "").strip()
        if value == self._get_api_key():
            return
        self._settings.set("subs.openSubtitlesApiKey", value)
        self.apiKeyChanged.emit()

    apiKey = Property(str, _get_api_key, _set_api_key, notify=apiKeyChanged)  # noqa: N802

    def _get_languages(self) -> list:
        raw = self._settings.get("subs.downloadLanguages", ["en"])
        return _clean_languages(raw)

    def _set_languages(self, value) -> None:
        cleaned = _clean_languages(value)
        if cleaned == self._get_languages():
            return
        self._settings.set("subs.downloadLanguages", cleaned)
        self.languagesChanged.emit()

    languages = Property("QVariantList", _get_languages, _set_languages, notify=languagesChanged)

    def _get_media_name(self) -> str:
        if self._controller is None:
            return ""
        return getattr(self._controller, "currentFileStem", "") or ""

    mediaName = Property(str, _get_media_name, notify=mediaNameChanged)  # noqa: N802

    # ------------------------------------------------------------- slots ---
    @Slot(str)
    def search(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self._set_status("Type a movie or series name first.", error=True)
            return
        key = self._get_api_key()
        if not key:
            self._set_status("Add your OpenSubtitles API key above, then search.",
                             error=True)
            return
        if self._searching:
            return

        self._search_seq += 1
        seq = self._search_seq
        langs = self._get_languages()
        transport = self._transport

        self._set_searching(True)
        self._set_status("Searching\u2026")

        def work():
            return _run_search(transport, query, langs, key)

        job = _Job(work, self)
        job.done.connect(lambda payload, s=seq: self._on_search_done(s, payload))
        job.finished.connect(lambda j=job: self._forget_job(j))
        self._jobs.append(job)
        job.start()

    @Slot(int)
    def download(self, index: int) -> None:
        if self._busy_index != -1 or self._controller is None:
            return
        item = next((r for r in self._results if r.get("idx") == index), None)
        if item is None:
            return
        media_path = self._controller.current_media_path()
        if not media_path:
            self._set_status("Nothing is playing — start the media first.", error=True)
            return
        key = self._get_api_key()
        if not key:
            self._set_status("Add your OpenSubtitles API key above, then download.",
                             error=True)
            return

        self._download_seq += 1
        seq = self._download_seq
        transport = self._transport
        transport_bytes = self._transport_bytes
        file_id = item["file_id"]
        fallback_name = item.get("file_name") or "subtitle.srt"

        self._set_busy_index(index)
        self._set_status("Downloading\u2026")

        def work():
            return _run_download(transport, transport_bytes, file_id, fallback_name, key)

        job = _Job(work, self)
        job.done.connect(
            lambda payload, s=seq, it=item, mp=media_path: self._on_download_done(s, it, mp, payload)
        )
        job.finished.connect(lambda j=job: self._forget_job(j))
        self._jobs.append(job)
        job.start()

    @Slot()
    def clearResults(self) -> None:  # noqa: N802 - QML-facing
        self._results = []
        self._best = []
        self._others = []
        self.resultsChanged.emit()
        self._set_status("")

    # --------------------------------------------------------- job plumbing ---
    def _on_search_done(self, seq: int, payload) -> None:
        if seq != self._search_seq:
            return  # a newer search owns the state; this reply is history
        self._set_searching(False)
        kind, value = payload
        if kind == "error":
            self._set_results([], [])
            self._set_status(value, error=True)
            return
        results = value
        for i, entry in enumerate(results):
            entry["idx"] = i
        best, others = _rank_and_split(results, self._get_languages())
        self._results = results
        self._set_results(best, others)
        if not results:
            self._set_status("No subtitles found for this title.")
        else:
            self._set_status(f"{len(results)} subtitle(s) found.")

    def _on_download_done(self, seq: int, item: dict, media_path: str, payload) -> None:
        if seq != self._download_seq:
            return
        self._set_busy_index(-1)
        kind, value, *rest = payload
        if kind == "error":
            self._set_status(value, error=True)
            return

        blob, file_name = value, rest[0]
        target = _target_path(media_path, file_name, item.get("lang", ""))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        except OSError as exc:
            log.warning("could not save subtitle: %s", exc)
            self._set_status(f"Could not save the file: {exc}", error=True)
            return

        # Attach through the one external-subtitle path so the file lands in
        # the popover's Local subtitles section (§4.1).
        self._controller.loadSubtitle(str(target))
        log.info("downloaded subtitle %s (%s)", target.name, item.get("lang", "?"))
        self._set_status(f"Loaded {target.name} — see Local subtitles.")

    def _forget_job(self, job: _Job) -> None:
        if job in self._jobs:
            self._jobs.remove(job)

    # ----------------------------------------------------- state setters ---
    def _set_searching(self, value: bool) -> None:
        if value == self._searching:
            return
        self._searching = value
        self.searchingChanged.emit()

    def _set_busy_index(self, value: int) -> None:
        if value == self._busy_index:
            return
        self._busy_index = value
        self.busyIndexChanged.emit()

    def _set_results(self, best: list, others: list) -> None:
        self._best = best
        self._others = others
        self.resultsChanged.emit()

    def _set_status(self, text: str, error: bool = False) -> None:
        if text == self._status and error == self._status_is_error:
            return
        self._status = text
        self._status_is_error = error
        self.statusChanged.emit()

    # ------------------------------------------------------------ shutdown ---
    def shutdown(self) -> None:
        """Give live jobs a moment to land before the process tears down."""
        for job in list(self._jobs):
            if job.isRunning():
                job.wait(1500)
        self._jobs.clear()


# ============================================================ pure helpers ===
def _clean_languages(raw) -> list[str]:
    """Coerce whatever QML/JSON handed us into a tidy list of ISO codes."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        code = str(item).strip().lower()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out or ["en"]


def _normalise_results(payload) -> list[dict]:
    """Flatten the OpenSubtitles ``/subtitles`` payload into row dicts.

    Anything missing a ``file_id`` or a display name is dropped — a result you
    cannot download is clutter, and KeyErrors at render time are worse.
    """
    rows: list[dict] = []
    if not isinstance(payload, dict):
        return rows
    data = payload.get("data")
    if not isinstance(data, list):
        return rows
    for item in data:
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        file_id = files[0].get("file_id") if files else None
        file_name = files[0].get("file_name") if files else None
        name = attrs.get("release") or file_name
        if not file_id or not name:
            continue
        rows.append(
            {
                "file_id": int(file_id),
                "file_name": str(file_name or "subtitle.srt"),
                "name": str(name),
                "lang": str(attrs.get("language") or ""),
                "downloads": int(attrs.get("download_count") or 0),
                "rating": attrs.get("ratings") or 0,
                "hd": bool(attrs.get("hd")),
                "trusted": bool(attrs.get("from_trusted")),
            }
        )
    return rows


def _rank_and_split(results: list[dict], preferred: list[str]) -> tuple[list, list]:
    """Order by best-guess quality, then split (top 3, the rest).

    Preferred language dominates; trusted uploaders, HD flags, download counts
    and community rating break the ties. Deterministic for equal scores so the
    list is stable between searches of the same title.
    """

    def score(row: dict) -> float:
        value = 0.0
        if preferred:
            if row["lang"] == preferred[0]:
                value += 100.0
            elif row["lang"] in preferred:
                value += 60.0
        if row["trusted"]:
            value += 8.0
        if row["hd"]:
            value += 4.0
        value += math.log10(max(0, row["downloads"]) + 1.0) * 2.0
        try:
            value += min(5.0, max(0.0, float(row["rating"]))) / 2.0
        except (TypeError, ValueError):
            pass
        return value

    ordered = sorted(
        results, key=lambda row: (score(row), row["downloads"]), reverse=True
    )
    return ordered[:3], ordered[3:]


def _target_path(media_path: str, file_name: str, lang: str) -> Path:
    """Where a downloaded subtitle lands: beside the media, named to auto-load.

    First choice is ``<media stem><.srt>`` — exactly what the sidecar loader
    looks for next launch. On collision the language tag goes in, then a
    counter, so a re-download never silently overwrites an earlier save.
    """
    media = Path(media_path)
    stem = media.stem
    ext = Path(file_name or "").suffix.lower()
    if ext not in _SUBTITLE_SUFFIXES:
        ext = ".srt"
    lang = (lang or "").strip().lower()

    first = media.parent / f"{stem}{ext}"
    if not first.exists():
        return first
    if lang:
        second = media.parent / f"{stem}.{lang}{ext}"
        if not second.exists():
            return second
        for n in range(2, 100):
            candidate = media.parent / f"{stem}.{lang}.{n}{ext}"
            if not candidate.exists():
                return candidate
    for n in range(2, 100):
        candidate = media.parent / f"{stem}.{n}{ext}"
        if not candidate.exists():
            return candidate
    return first  # unreachable in practice; overwrite rather than lose the file


# ============================================================ HTTP (stdlib) ===
def _http_error_message(exc: urllib.error.HTTPError) -> str:
    """One friendly sentence per status code the REST API realistically sends."""
    code = exc.code
    if code in (401, 403):
        return "API key rejected — check it and try again."
    if code == 404:
        return "Nothing found for that request."
    if code == 406:
        return "Download limit reached — OpenSubtitles' free quota resets daily."
    if code == 429:
        return "Too many requests — wait a moment and try again."
    if code == 503:
        return "The subtitle service is unavailable right now."
    return f"The subtitle service answered with an error ({code})."


def _default_transport(url: str, api_key: str, payload):
    """JSON round-trip. Returns ``(data, None)`` or ``(None, friendly_message)``."""
    headers = {
        "Api-Key": api_key,
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, _http_error_message(exc)
    except urllib.error.URLError:
        return None, "No internet connection."
    except (ValueError, OSError) as exc:
        log.warning("subtitle service parse failure: %s", exc)
        return None, "Unexpected response from the subtitle service."


def _default_transport_bytes(url: str, api_key: str):
    """Fetch the signed download link's file body."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT * 2) as response:
            return response.read(), None
    except urllib.error.HTTPError as exc:
        return None, _http_error_message(exc)
    except (urllib.error.URLError, OSError):
        return None, "The download could not be completed."


def _run_search(transport, query: str, langs: list[str], key: str):
    """Worker half of ``search()`` — runs off the GUI thread.

    The API is queried *without* a ``languages`` filter so the full catalogue
    for the title comes back; the language-aware ranking in
    :func:`_rank_and_split` then floats the user's preferred picks to the top
    of Best matches while everything else populates the More results section
    below. Filtering server-side would leave that section empty for most
    titles — which was the reported bug.
    """
    params: dict[str, str] = {"query": query}
    url = f"{_API_BASE}/subtitles?{urllib.parse.urlencode(params)}"
    data, err = transport(url, key, None)
    if err is not None:
        return ("error", err)
    return ("results", _normalise_results(data))


def _run_download(transport, transport_bytes, file_id: int, fallback_name: str, key: str):
    """Worker half of ``download()``: negotiate the link, then pull the bytes."""
    data, err = transport(f"{_API_BASE}/download", key, {"file_id": file_id})
    if err is not None:
        return ("error", err)
    link = (data or {}).get("link")
    if not link:
        return ("error", "The subtitle service did not return a download link.")
    file_name = (data or {}).get("file_name") or fallback_name
    blob, err = transport_bytes(link, key)
    if err is not None:
        return ("error", err)
    return ("blob", blob, file_name)
