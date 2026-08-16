"""M3U mode's channel list and context — Milestones 2.1–2.3 (§P2.3/§P2.4).

Two pieces:

* :class:`ChannelModel` — the flat ``QAbstractListModel`` behind the channel
  list. Holds every parsed channel once; the *view* (filter text + grouping)
  is a rebuilt index order, so grouping changes never re-parse anything.
* :class:`M3UContext` — the object the shell exposes to QML as
  ``modeContext_m3u`` (via :func:`modes.m3u.build_m3u_context`). It owns the
  model, the saved-sources store, background playlist loading, and the two
  behaviour rules the owner set:
    * **loading a source stops the current stream** (§P2.4, 2026-08-02), and
    * **the one-tuner rule** (v3.4): entering M3U stops Local's playback and
      leaving M3U stops the stream — enforced from here, so no Phase 1 file
      needs an edit (§A.3).

Isolation (§A.1): this module imports from ``core`` and ``modes.m3u`` only —
never from Local.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QRunnable,
    QThreadPool,
    Qt,
    Signal,
    Slot,
)

from core import paths as path_utils
from modes.m3u.parser import Channel, ParseResult, parse_m3u
from modes.m3u import parser
from modes.m3u.favourites import FavouritesStore
from modes.m3u.logo_cache import LogoFailureStore, is_loadable_logo
from modes.m3u.sources import KIND_FILE, KIND_URL, MAX_SOURCES, Source, SourcesStore

log = logging.getLogger(__name__)

GROUPING_NONE = "none"
GROUPING_CATEGORY = "category"
GROUPING_COUNTRY = "country"
GROUPING_LANGUAGE = "language"


class ChannelModel(QAbstractListModel):
    """All channels from the loaded playlist, presented through a *view* that
    the filter box and the grouping selector rebuild in place."""

    NameRole = Qt.UserRole + 1
    GroupRole = Qt.UserRole + 2
    CountryRole = Qt.UserRole + 3
    LogoRole = Qt.UserRole + 4
    UrlRole = Qt.UserRole + 5
    GroupKeyRole = Qt.UserRole + 6
    IsCurrentRole = Qt.UserRole + 7
    LanguageRole = Qt.UserRole + 8
    IsGroupExpandedRole = Qt.UserRole + 9
    IsFavouriteRole = Qt.UserRole + 10

    countChanged = Signal()
    totalCountChanged = Signal()
    currentIndexChanged = Signal()
    groupingChanged = Signal()
    expandedGroupChanged = Signal()
    favouritesOnlyChanged = Signal()
    favouritesChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._channels: list[Channel] = []
        self._view: list[Channel] = []       # filter + grouping applied
        self._current: Channel | None = None
        self._current_index: int = -1        # cached index in _view for O(1) play resume (15k list)
        self._filter = ""
        self._grouping = GROUPING_CATEGORY
        self._expanded_group = ""
        self._group_counts: dict[str, int] = {}
        self._favourite_urls: set[str] = set()
        self._favourites_only = False
        #: Predicate injected by :class:`M3UContext`: "has this logo URL
        #: already failed?". Kept as a plain callable so the model stays
        #: testable head-less and knows nothing about where the answer is
        #: stored.
        self._logo_is_dead = None

    # ------------------------------------------------------------- Qt API --
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._view)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._view)):
            return None
        channel = self._view[index.row()]
        if role == self.NameRole:
            return channel.name
        if role == self.GroupRole:
            return channel.group
        if role == self.CountryRole:
            return channel.country
        if role == self.LanguageRole:
            return channel.language
        if role == self.LogoRole:
            return self.display_logo(channel)
        if role == self.UrlRole:
            return channel.url
        if role == self.GroupKeyRole:
            return self._group_key(channel)
        if role == self.IsCurrentRole:
            return channel is self._current
        if role == self.IsGroupExpandedRole:
            if self._grouping == GROUPING_NONE:
                return True
            return self._group_key(channel) == self._expanded_group
        if role == self.IsFavouriteRole:
            return channel.url in self._favourite_urls
        return None

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {
            self.NameRole: b"name",
            self.GroupRole: b"group",
            self.CountryRole: b"country",
            self.LanguageRole: b"language",
            self.LogoRole: b"logo",
            self.UrlRole: b"url",
            self.GroupKeyRole: b"groupKey",
            self.IsCurrentRole: b"isCurrent",
            self.IsGroupExpandedRole: b"isGroupExpanded",
            self.IsFavouriteRole: b"isFavourite",
        }

    # --------------------------------------------------------- QML surface --
    @Property(int, notify=countChanged)
    def count(self) -> int:  # noqa: N802
        return len(self._view)

    @Property(int, notify=totalCountChanged)
    def totalCount(self) -> int:  # noqa: N802
        return len(self._channels)

    @Property(int, notify=favouritesChanged)
    def favouriteCount(self) -> int:  # noqa: N802
        if not self._channels:
            return 0
        return sum(1 for channel in self._channels if channel.url in self._favourite_urls)

    @Property(int, notify=currentIndexChanged)
    def currentIndex(self) -> int:  # noqa: N802
        return self._current_index

    @Property(str, notify=groupingChanged)
    def grouping(self) -> str:  # noqa: N802
        return self._grouping

    @Property(str, notify=expandedGroupChanged)
    def expandedGroup(self) -> str:  # noqa: N802
        return self._expanded_group

    @Property(bool, notify=favouritesOnlyChanged)
    def favouritesOnly(self) -> bool:  # noqa: N802
        return self._favourites_only

    @Slot(str, result=int)
    def groupCount(self, group_key: str) -> int:  # noqa: N802
        return self._group_counts.get(group_key, 0)

    @Slot(str)
    def toggleGroup(self, group_key: str) -> None:  # noqa: N802
        if self._grouping == GROUPING_NONE:
            return
        if self._expanded_group == group_key:
            self._expanded_group = ""
        else:
            self._expanded_group = group_key
        if self._view:
            top = self.index(0)
            bottom = self.index(len(self._view) - 1)
            self.dataChanged.emit(top, bottom, [self.IsGroupExpandedRole])
        self.expandedGroupChanged.emit()

    # ------------------------------------------------------------ mutation --
    def set_channels(self, channels: list[Channel]) -> None:
        """Replace the whole list (a source was loaded). The current channel
        stays highlighted when it survives the swap — by URL, the only stable
        identity a channel has."""
        self.beginResetModel()
        current_url = self._current.url if self._current else None
        self._channels = list(channels)
        self._current = None
        if current_url:
            for channel in self._channels:
                if channel.url == current_url:
                    self._current = channel
                    break
        self._rebuild_view(preserve_expanded=False)
        self.endResetModel()
        self.countChanged.emit()
        self.totalCountChanged.emit()
        self.currentIndexChanged.emit()
        self.expandedGroupChanged.emit()
        self.favouritesChanged.emit()

    @Slot(str)
    def setFilter(self, text: str) -> None:  # noqa: N802
        text = (text or "").strip().casefold()
        if text == self._filter:
            return
        self.beginResetModel()
        self._filter = text
        self._rebuild_view(preserve_expanded=True)
        self.endResetModel()
        self.countChanged.emit()
        self.currentIndexChanged.emit()
        self.expandedGroupChanged.emit()

    @Slot(str)
    def setGrouping(self, grouping: str) -> None:  # noqa: N802
        if grouping not in (GROUPING_NONE, GROUPING_CATEGORY, GROUPING_COUNTRY, GROUPING_LANGUAGE):
            return
        if grouping == self._grouping:
            return
        self.beginResetModel()
        self._grouping = grouping
        self._rebuild_view(preserve_expanded=False)
        self.endResetModel()
        self.groupingChanged.emit()
        self.countChanged.emit()
        self.currentIndexChanged.emit()
        self.expandedGroupChanged.emit()
        # The QML panel persists the choice through the context (mode settings).

    @Slot(bool)
    def setFavouritesOnly(self, enabled: bool) -> None:  # noqa: N802
        enabled = bool(enabled)
        if enabled == self._favourites_only:
            return
        self.beginResetModel()
        self._favourites_only = enabled
        self._rebuild_view(preserve_expanded=True)
        self.endResetModel()
        self.favouritesOnlyChanged.emit()
        self.countChanged.emit()
        self.currentIndexChanged.emit()
        self.expandedGroupChanged.emit()

    # ------------------------------------------------------------ playback --
    @Slot(int, result=bool)
    def play_index(self, row: int) -> bool:
        if not (0 <= row < len(self._view)):
            return False
        self._set_current(self._view[row])
        if self._play is not None:
            self._play(self._current.url)
        return True

    @Slot(result=bool)
    def play_next(self) -> bool:
        """Called by the shared controller on Next and when a stream ends.
        At the last channel there is nothing after it — the caller stops."""
        row = self.currentIndex
        if row < 0:
            return self.play_index(0) if self._view else False
        if row + 1 >= len(self._view):
            return False
        return self.play_index(row + 1)

    @Slot(result=bool)
    def play_previous(self) -> bool:
        row = self.currentIndex
        if row <= 0:
            return self.play_index(0) if self._view else False
        return self.play_index(row - 1)

    @Slot()
    def clear(self) -> None:
        """Empty the list (Clear Playlist). The shared controller stops the
        player itself; `current` drops with the content."""
        self.beginResetModel()
        self._channels = []
        self._view = []
        self._current = None
        self._current_index = -1
        self._expanded_group = ""
        self._group_counts = {}
        self.endResetModel()
        self.countChanged.emit()
        self.totalCountChanged.emit()
        self.currentIndexChanged.emit()
        self.expandedGroupChanged.emit()
        self.favouritesChanged.emit()

    def channel_at(self, row: int) -> Channel | None:
        if not (0 <= row < len(self._view)):
            return None
        return self._view[row]

    def set_favourites(self, urls: set[str]) -> None:
        urls = {str(url).strip() for url in urls if str(url).strip()}
        if urls == self._favourite_urls:
            return
        reset = self._favourites_only
        if reset:
            self.beginResetModel()
        self._favourite_urls = urls
        if reset:
            self._rebuild_view(preserve_expanded=True)
            self.endResetModel()
            self.countChanged.emit()
            self.currentIndexChanged.emit()
            self.expandedGroupChanged.emit()
        elif self._view:
            top = self.index(0)
            bottom = self.index(len(self._view) - 1)
            self.dataChanged.emit(top, bottom, [self.IsFavouriteRole])
        self.favouritesChanged.emit()

    def set_favourite_url(self, url: str, favourite: bool) -> None:
        urls = set(self._favourite_urls)
        if favourite:
            urls.add(url)
        else:
            urls.discard(url)
        self.set_favourites(urls)

    def is_favourite(self, url: str) -> bool:
        """True when ``url`` is starred — used by the mobile remote snapshot."""
        return str(url).strip() in self._favourite_urls

    # ---------------------------------------------------------------- logos --
    def set_logo_gate(self, is_dead) -> None:
        """Install the "has this logo already failed?" predicate.

        Injected rather than imported so the model keeps no store of its own:
        :class:`M3UContext` owns the persistent one, and a head-less test can
        pass a plain ``set().__contains__`` (or nothing at all).
        """
        self._logo_is_dead = is_dead

    def display_logo(self, channel: Channel) -> str:
        """The logo URL the list should actually request — or ``""``.

        Three things are filtered out here, before a single byte is asked for,
        because the row falls back to the globe glyph either way and a request
        that cannot succeed is pure cost:

        * no logo at all;
        * a URL that *cannot* decode in this build (SVG, image share pages);
        * a URL that has already failed for us before.
        """
        logo = (channel.logo or "").strip()
        if not logo or not is_loadable_logo(logo):
            return ""
        is_dead = self._logo_is_dead
        if is_dead is not None:
            try:
                if is_dead(logo):
                    return ""
            except Exception:  # noqa: BLE001 - a broken gate must not blank the list
                log.debug("logo gate raised for %s", logo, exc_info=True)
        return logo

    # ------------------------------------------------------------ internals --
    #: Set by the context: the function that actually opens a URL in the
    #: shared engine. Kept injectable so the model stays testable headless.
    _play = None

    def _set_current(self, channel: Channel) -> None:
        old_row = self._current_index
        self._current = channel
        if self._grouping != GROUPING_NONE and channel is not None:
            group = self._group_key(channel)
            if group and group != self._expanded_group and group in self._group_counts:
                self.toggleGroup(group)
        # new index is where this channel lands in the current view
        try:
            new_row = self._view.index(channel)
        except ValueError:
            new_row = -1
        self._current_index = new_row
        for row in {old_row, new_row} - {-1}:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [self.IsCurrentRole])
        self.currentIndexChanged.emit()

    def _group_key(self, channel: Channel) -> str:
        if self._grouping == GROUPING_CATEGORY:
            return channel.group or "Ungrouped"
        if self._grouping == GROUPING_COUNTRY:
            return channel.country or "Unknown"
        if self._grouping == GROUPING_LANGUAGE:
            return channel.language or "Unknown"
        return ""

    def _rebuild_view(self, preserve_expanded: bool = False) -> None:
        view = list(self._channels)
        if self._filter:
            view = [
                c for c in view
                if self._filter in c.name.casefold()
                or self._filter in c.group.casefold()
                or self._filter in c.country.casefold()
                or self._filter in c.language.casefold()
            ]
        if self._favourites_only:
            view = [c for c in view if c.url in self._favourite_urls]
        if self._grouping != GROUPING_NONE:
            view.sort(key=lambda c: ("\uffff" if self._group_key(c) in ("Ungrouped", "Unknown")
                                     else self._group_key(c).casefold(),
                                     c.name.casefold()))
        self._view = view

        # Compute matching channel count per group in this view
        counts: dict[str, int] = {}
        for c in view:
            key = self._group_key(c)
            counts[key] = counts.get(key, 0) + 1
        self._group_counts = counts

        if self._grouping == GROUPING_NONE:
            self._expanded_group = ""
        else:
            if not (preserve_expanded and self._expanded_group in self._group_counts):
                if self._current is not None and self._group_key(self._current) in self._group_counts:
                    self._expanded_group = self._group_key(self._current)
                elif self._view:
                    self._expanded_group = self._group_key(self._view[0])
                else:
                    self._expanded_group = ""

        # keep cached index in sync with filtered / sorted view
        if self._current is None:
            self._current_index = -1
        else:
            try:
                self._current_index = self._view.index(self._current)
            except ValueError:
                self._current_index = -1


class _LoadSignals(QObject):
    """Bridge for the worker thread → GUI thread hand-off. A QRunnable cannot
    carry signals, so they live on this small long-referenced object. Carries
    a ``cancelled`` flag so in-flight loads stop talking to it once the context
    is going away (same rule as Local's ``_ProbeSignals``).
    """

    succeeded = Signal(str, str)   # source id, playlist text
    failed = Signal(str, str)      # source id, human message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cancelled = False


class _LoadWorker(QRunnable):
    """Fetch + read off the GUI thread: a 2 MB playlist over a slow link must
    never freeze the panel (§P2.4)."""

    def __init__(self, source: Source, signals: _LoadSignals) -> None:
        super().__init__()
        self._source = source
        self._signals = signals

    def run(self) -> None:
        text = ""
        error: str | None = None
        try:
            if self._source.kind == KIND_URL:
                text = parser.fetch_playlist(self._source.location)
            else:
                text = parser.read_playlist(Path(self._source.location))
        except RuntimeError as exc:                       # friendly fetch messages
            error = str(exc)
        except FileNotFoundError:
            error = "file not found — it may have moved"
        except PermissionError:
            error = "cannot read the file (permission denied)"
        except OSError as exc:
            error = f"could not read the file ({exc})"
        except Exception:  # noqa: BLE001 - a playlist must never crash the app
            log.exception("playlist load failed for %s", self._source.location)
            error = "could not load the playlist"

        # Re-check: the context may have been torn down during the fetch above,
        # and emitting into a deleted QObject raises out of a pool thread.
        try:
            if self._signals.cancelled:
                return
            if error is not None:
                self._signals.failed.emit(self._source.id, error)
            else:
                self._signals.succeeded.emit(self._source.id, text)
        except (RuntimeError, Exception):
            pass  # receiver already gone; nothing to report to


class M3UContext(QObject):
    """The object published to QML as ``modeContext_m3u``.

    Owns the channel model, the saved-sources store and all source loading;
    enforces the owner's two behaviour rules from inside M3U (§P2.3/§P2.4).
    The shell never names it — it is found through the registry (§A.2).
    """

    sourcesChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()
    # Emitted when a channel fails to play — QML shows a toast (§M2.4).
    streamError = Signal(str)   # human-readable message

    def __init__(self, engine, controller, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._controller = controller
        self._settings = settings

        self._model = ChannelModel(self)
        self._model._play = self._open_url

        store_path = settings.path.parent / "m3u-sources.json"
        self._store = SourcesStore(store_path)
        favourites_path = settings.path.parent / "m3u-favourites.json"
        self._favourites = FavouritesStore(favourites_path)
        # Dead logos are remembered across sessions: without this, every entry
        # into M3U re-requests every 404/403 in the playlist (§M2.3).
        logo_failures_path = settings.path.parent / "m3u-logo-failures.json"
        self._logo_failures = LogoFailureStore(logo_failures_path)
        self._model.set_logo_gate(self._logo_failures.contains)

        self._status_message = ""
        self._status_is_error = False
        self._loading = False
        self._current_channel_name = ""
        self._current_source_name = ""
        self._current_source_id = ""
        self._unsaved_source_name = ""
        self._unsaved_source_kind = ""
        self._unsaved_source_location = ""
        self._last_attempted_id = ""
        self._pending_source_id = ""
        self._inflight: dict[str, _LoadSignals] = {}
        # A pool of our own, not QThreadPool.globalInstance(). The global pool
        # is shared with the rest of Qt and cannot be drained without stalling
        # unrelated work, so shutdown() had no way to guarantee that every
        # in-flight playlist load had finished (modes/local/playlist.py keeps
        # the same rule for its probes, §9). A load still inside
        # `signals.succeeded.emit(...)` while Python collected the signals
        # QObject tears the process down mid-interpreter-exit — owning the pool
        # lets shutdown() wait, exactly like Local.
        self._pool = QThreadPool(self)
        self._shut_down = False

        self._previous_mode = controller.activeMode
        self._restored_last_source = False

        grouping = settings.get_mode("m3u", "grouping", GROUPING_CATEGORY)
        self._model.setGrouping(
            grouping if grouping in (GROUPING_NONE, GROUPING_CATEGORY, GROUPING_COUNTRY, GROUPING_LANGUAGE)
            else GROUPING_CATEGORY
        )

        # Stream play errors surface in the panel with the retry affordance
        # Stream play errors emit a toast through the streamError signal (§M2.4).
        engine.errorOccurred.connect(self._on_engine_error)

        # The one-tuner rule + last-source restore live on this one connection.
        # Made at startup (contexts are built for every registered mode), so
        # the rule holds from the very first switch — with no edit to any
        # Phase 1 file (§A.3).
        controller.activeModeChanged.connect(self._on_mode_changed)

    # ------------------------------------------------- QML: data providers --
    @Property(QObject, constant=True)
    def channels(self) -> ChannelModel:  # noqa: N802
        return self._model

    @Property("QVariantList", notify=sourcesChanged)
    def sources(self) -> list[dict]:  # noqa: N802
        return [s.as_dict() for s in self._store.list()]

    @Property(bool, notify=sourcesChanged)
    def sourcesFull(self) -> bool:  # noqa: N802
        return self._store.full

    @Property(int, constant=True)
    def sourcesMaxCount(self) -> int:  # noqa: N802
        return MAX_SOURCES

    @Property(str, notify=infoChanged)
    def currentSourceName(self) -> str:  # noqa: N802
        return self._current_source_name

    @Property(bool, notify=infoChanged)
    def canSaveCurrentSource(self) -> bool:  # noqa: N802
        return bool(self._unsaved_source_location) and not self._store.full

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:  # noqa: N802
        return self._status_message

    @Property(bool, notify=statusChanged)
    def statusIsError(self) -> bool:  # noqa: N802
        return self._status_is_error

    @Property(bool, notify=statusChanged)
    def loading(self) -> bool:  # noqa: N802
        return self._loading

    @Property(str, notify=infoChanged)
    def currentChannelName(self) -> str:  # noqa: N802
        return self._current_channel_name

    # ------------------------------------------- QML: sources manager slots --
    @Slot(str, str, str, result=str)
    def addSource(self, name: str, location: str, kind: str) -> str:  # noqa: N802
        """Returns "" on success or a human message the dialog can show."""
        if self._store.full:
            return f"You already have {MAX_SOURCES} — remove one to add another."
        location = (location or "").strip()
        if kind == KIND_URL:
            if not parser.is_url(location):
                return "That doesn't look like a URL — it should start with http:// or https://"
        elif kind == KIND_FILE:
            location = path_utils.normalise_path(location)
            if not Path(location).exists():
                return "File not found — check the path."
        else:
            return "Unknown source type."
        if self._store.add(name, kind, location) is None:
            return "Could not add the source."
        self.sourcesChanged.emit()
        self.infoChanged.emit()
        return ""

    @Slot(str, str, str, result=bool)
    def updateSource(self, source_id: str, name: str, location: str) -> bool:  # noqa: N802
        location = (location or "").strip()
        if location.startswith("file://"):
            location = path_utils.normalise_path(location)
        ok = self._store.update(source_id, name, location)
        if ok:
            if source_id == self._current_source_id and name.strip():
                self._current_source_name = name.strip()
                self.infoChanged.emit()
            self.sourcesChanged.emit()
        return ok

    @Slot(str, result=bool)
    def removeSource(self, source_id: str) -> bool:  # noqa: N802
        ok = self._store.remove(source_id)
        if ok:
            self._favourites.remove_source(source_id)
            if self._settings.get_mode("m3u", "lastSource", "") == source_id:
                self._forget_last_source()
            if source_id == self._current_source_id:
                # Deleting the playlist you are looking at removes it from the
                # screen too. Keeping its channels listed (as an unsaved
                # "(not saved)" list, which one bookmark click would re-save)
                # made a confirmed delete look like it had not happened, and
                # the list came back on the next launch.
                self._current_source_id = ""
                self._current_source_name = ""
                if self._model.favouritesOnly:
                    self._model.setFavouritesOnly(False)
                self._model.set_favourites(set())
                self._clear_unsaved_source()
                self._last_attempted_id = ""
                self._pending_source_id = ""
                self._stop_playback()
                self._model.clear()
                self._current_channel_name = ""
                self._set_status("", is_error=False)
                self.infoChanged.emit()
            self.sourcesChanged.emit()
            self.infoChanged.emit()
        return ok

    @Slot(str)
    def loadSource(self, source_id: str) -> None:  # noqa: N802
        """Load a saved source. **Stops the current stream first** — owner
        decision (§P2.4): the playing channel is not in the new list, so it
        must not keep streaming. Even a failed load stops; that is decisive,
        not half-swapped."""
        source = self._store.get(source_id)
        if source is None:
            self._set_status("That source no longer exists.", is_error=True)
            return
        self._stop_playback()
        self._last_attempted_id = source_id
        self._pending_source_id = source_id
        self._loading = True
        self._set_status(f"Loading {source.name}…", is_error=False)

        if source.kind == KIND_FILE and not Path(source.location).exists():
            self._loading = False
            self._set_status("File not found — it may have moved.", is_error=True)
            return

        signals = _LoadSignals(self)
        signals.succeeded.connect(self._on_load_succeeded)
        signals.failed.connect(self._on_load_failed)
        self._inflight[source_id] = signals
        self._pool.start(_LoadWorker(source, signals))

    @Slot()
    def retry(self) -> None:  # noqa: N802
        """Retry a failed playlist load (§M2.4)."""
        if self._last_attempted_id:
            self.loadSource(self._last_attempted_id)

    @Slot(list)
    def openFiles(self, urls: list) -> None:  # noqa: N802
        """A dropped ``.m3u``/``.m3u8`` on the panel (§P2.4): opens it through
        the same pipeline as Add File — and does **not** save it to the seven."""
        candidates = []
        for entry in urls:
            text = entry.toString() if hasattr(entry, "toString") else str(entry)
            path = path_utils.normalise_path(text)
            if Path(path.split("?", 1)[0]).suffix.lower() in (".m3u", ".m3u8"):
                candidates.append(path)
        if not candidates:
            return
        path = candidates[0]
        self._stop_playback()
        self._last_attempted_id = ""
        try:
            result = parser.parse_m3u(parser.read_playlist(Path(path)),
                                      base_dir=Path(path).parent)
        except (OSError, RuntimeError) as exc:
            self._set_status(f"Could not open the file ({exc})", is_error=True)
            return
        except Exception:  # noqa: BLE001
            log.exception("dropped playlist failed: %s", path)
            self._set_status("Could not open the file.", is_error=True)
            return
        self._current_source_id = ""
        if self._model.favouritesOnly:
            self._model.setFavouritesOnly(False)
        self._current_source_name = f"{Path(path).stem} (not saved)"
        self._remember_unsaved_source(Path(path).stem, KIND_FILE, path)
        self.infoChanged.emit()
        self._apply_result(result)

    @Slot()
    def clearStatus(self) -> None:  # noqa: N802
        self._set_status("", is_error=False)

    @Slot(str)
    def noteLogoFailed(self, url: str) -> None:  # noqa: N802
        """Remember a logo URL that the list could not load (§M2.3).

        Called by the panel from ``Image.onStatusChanged`` when a thumbnail
        ends in ``Image.Error`` — a 404, a 403 hot-link block, a timeout or an
        undecodable payload. The row is already showing its globe fallback; the
        only purpose of remembering is that the *next* visit does not pay for
        the same dead URL again.

        Deliberately fire-and-forget from QML's point of view: it returns
        nothing, cannot fail, and does not touch the model. Re-reading the row
        to blank it now would restart the list's delegate churn for no visible
        gain — the filter takes effect the next time the view is built.
        """
        url = (url or "").strip()
        if not url:
            return
        if self._logo_failures.add(url):
            log.debug("logo unavailable, will not ask again: %s", url)

    @Slot()
    def forgetFailedLogos(self) -> None:  # noqa: N802
        """Give every remembered-bad logo another chance.

        Nothing in the UI calls this yet; it exists so "my logos are missing
        and I know the server is back" has an answer that is not "delete a
        JSON file by hand".
        """
        self._logo_failures.clear()

    @Slot(str)
    def persistGrouping(self, grouping: str) -> None:  # noqa: N802
        """The panel's selector writes both sides: the model's view sorting
        and the remembered choice (§P2.4 — the grouping choice is remembered)."""
        self._model.setGrouping(grouping)
        self._settings.set_mode("m3u", "grouping", grouping)

    @Slot(int, result=str)
    def toggleFavourite(self, row: int) -> str:  # noqa: N802
        """Toggle a channel favourite, or ask QML to save an unsaved list."""
        if not self._current_source_id:
            return "save-required" if self._model.totalCount > 0 else ""
        channel = self._model.channel_at(row)
        if channel is None:
            return ""
        new_state = self._favourites.toggle(self._current_source_id, channel.url)
        if new_state is None:
            return ""
        self._model.set_favourite_url(channel.url, new_state)
        return "added" if new_state else "removed"

    @Slot(result=str)
    def toggleFavouritesOnly(self) -> str:  # noqa: N802
        """Toolbar bookmark: show all channels or only favourites."""
        if self._model.totalCount <= 0:
            return ""
        if not self._current_source_id:
            if self._model.favouritesOnly:
                self._model.setFavouritesOnly(False)
                return ""
            return "save-required"
        self._model.setFavouritesOnly(not self._model.favouritesOnly)
        return ""

    @Slot(result=str)
    def saveCurrentSourceForFavourites(self) -> str:  # noqa: N802
        """Save a dropped/temporary playlist so favourites have a home.

        The already parsed channel list stays in place; only the source gains a
        saved id, after which the next bookmark click can persist normally.
        """
        if not self._unsaved_source_location or not self._unsaved_source_kind:
            return "There is no temporary playlist to save."
        if self._store.full:
            return f"You already have {MAX_SOURCES} — remove one to add another."

        location = self._unsaved_source_location
        kind = self._unsaved_source_kind
        if kind == KIND_FILE and not Path(location).exists():
            return "File not found — it may have moved."
        if kind == KIND_URL and not parser.is_url(location):
            return "That doesn't look like a URL — it should start with http:// or https://"

        source = self._store.add(self._unsaved_source_name, kind, location)
        if source is None:
            return "Could not save the playlist."

        self._current_source_id = source.id
        self._current_source_name = source.name
        self._clear_unsaved_source()
        self._model.set_favourites(self._favourites.list(source.id))
        self._settings.set_mode("m3u", "lastSource", source.id)
        self.sourcesChanged.emit()
        self.infoChanged.emit()
        return ""

    # ------------------------------ shared-controller protocol (duck-typed) --
    # The controller calls these on whichever context is active (§A.2): Next,
    # Previous, end-of-stream advance and Clear Playlist reach M3U through
    # exactly the same generic code path as Local.
    # For Stop -> Play resume the controller also expects count / current_index
    # like Local (§P1.5) — we expose them as thin proxies, no copy of the 15k list.
    @Property(int, notify=statusChanged)
    def count(self) -> int:  # noqa: N802 - for AppController duck-typing
        return self._model.count

    @Property(int, notify=statusChanged)
    def currentIndex(self) -> int:  # noqa: N802 - QML friendly alias
        return self._model.currentIndex

    def current_index(self) -> int:
        return self._model.currentIndex

    def current_playback_label(self) -> str:
        """Friendly name for transport feedback, never the raw stream URL.

        :class:`core.app.AppController` reads this through its generic playlist
        protocol after Next/Previous. It is intentionally a tiny Python-side
        accessor rather than a second playback path.
        """
        current = self._model._current
        return current.name if current is not None else ""

    @Slot(result=bool)
    def play_current(self) -> bool:
        """O(1) resume for 15k lists: re-open the selected channel URL directly,
        without scanning the view. Used by AppController's Play after Stop."""
        cur = self._model._current
        if cur is not None:
            self._open_url(cur.url)
            return True
        if self._model.count > 0:
            return self._model.play_index(0)
        return False

    @Slot(int, result=bool)
    def play_index(self, row: int) -> bool:
        return self._model.play_index(row)

    @Slot(result=bool)
    def play_next(self) -> bool:
        return self._model.play_next()

    @Slot(result=bool)
    def play_previous(self) -> bool:
        return self._model.play_previous()

    @Slot()
    def clear(self) -> None:
        """Clear Playlist, from the panel button, the Delete key or the remote.

        Emptying the list must also **forget** it. The remembered last source
        is what M3U reloads the next time it is opened, so leaving it behind
        meant a cleared playlist quietly came back on the next launch — the
        clearest possible contradiction of an action the user confirmed.
        """
        self._model.clear()
        self._current_channel_name = ""
        self._current_source_id = ""
        self._current_source_name = ""
        self._clear_unsaved_source()
        self._last_attempted_id = ""
        self._pending_source_id = ""
        self._forget_last_source()
        self.infoChanged.emit()
        self._set_status("", is_error=False)

    # ---------------------------------------------------------- shutdown ---
    def shutdown(self) -> None:
        """Stop accepting load results and wait for in-flight loads to exit.

        Mirrors modes/local/playlist.py: setting the ``cancelled`` flag is not
        enough on its own — a load that has already passed the check may be
        inside ``succeeded.emit()`` when this object is collected, which
        crashes the interpreter rather than raising (§9). Clearing the private
        pool's queue and then *waiting* for the running loads is what makes
        teardown deterministic. Idempotent — teardown paths may call it more
        than once.
        """
        if self._shut_down:
            return
        self._shut_down = True
        # Batched logo failures are written here so a session's worth of dead
        # URLs survives even if fewer than SAVE_EVERY of them accumulated.
        try:
            self._logo_failures.save()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            log.debug("could not save the logo failure store", exc_info=True)
        for signals in self._inflight.values():
            signals.cancelled = True
        try:
            # Drop loads that have not started; they cannot be waited on.
            self._pool.clear()
            # Bounded wait: a load is a fetch + parse, a few seconds at worst
            # over a slow link. The timeout means a wedged load can never hang
            # application exit.
            self._pool.waitForDone(5000)
        except RuntimeError:
            # Pool already destroyed by a previous shutdown() — nothing to do.
            pass
        for signals in self._inflight.values():
            try:
                signals.succeeded.disconnect(self._on_load_succeeded)
                signals.failed.disconnect(self._on_load_failed)
            except (RuntimeError, TypeError):
                pass  # already disconnected, or the receiver is gone
        self._inflight.clear()

    # ------------------------------------------------------------ internals --
    def _forget_last_source(self) -> None:
        """Drop the remembered "reload this on next launch" pointer.

        Flushed immediately rather than left to the settings debounce: this is
        written by actions the user takes seconds before closing the app, and a
        pending write is exactly what gets lost then.
        """
        self._settings.set_mode("m3u", "lastSource", "")
        try:
            self._settings.flush()
        except Exception:  # noqa: BLE001 - never let a disk problem break the UI
            log.debug("could not flush settings after forgetting last source",
                      exc_info=True)

    def _remember_unsaved_source(self, name: str, kind: str, location: str) -> None:
        self._unsaved_source_name = (name or "").strip()
        self._unsaved_source_kind = kind
        self._unsaved_source_location = location

    def _clear_unsaved_source(self) -> None:
        self._unsaved_source_name = ""
        self._unsaved_source_kind = ""
        self._unsaved_source_location = ""

    def _open_url(self, url: str) -> None:
        """Channels open straight in the shared engine (§P2.2 — HLS included).
        Not through the controller's openPath: streams never resume, never
        prompt."""
        # Track the channel name for the title bar.
        current = self._model._current
        self._current_channel_name = current.name if current else ""
        self.infoChanged.emit()
        self._engine.open(url)

    def _stop_playback(self) -> None:
        """Stop the shared player and clear shared now-playing state.

        Local and M3U deliberately share the decoder, but metadata and lyrics
        are also shared UI state. Calling the engine directly stopped the
        picture while leaving the previous file/channel name for the idle card
        to display after a mode switch or source change. Use the controller's
        canonical stop path so playback, metadata and lyrics are cleared
        together without touching either mode's own playlist data.
        """
        try:
            self._controller.stop()
        except Exception:  # noqa: BLE001 - stopping must never break switching
            log.debug("engine stop failed (mode switch)", exc_info=True)

    def _apply_result(self, result: ParseResult) -> None:
        self._loading = False
        favourite_urls = (self._favourites.list(self._current_source_id)
                          if self._current_source_id else set())
        self._model.set_favourites(favourite_urls)
        self._model.set_channels(result.channels)
        if not result.channels:
            self._set_status("No playable channels found in this playlist.",
                             is_error=True)
            return
        self._set_status("", is_error=False)
        if result.skipped:
            log.info("M3U: %d malformed/nested entries skipped", result.skipped)

    @Slot(str, str)
    def _on_load_succeeded(self, source_id: str, text: str) -> None:
        self._inflight.pop(source_id, None)
        if source_id != self._pending_source_id:
            return     # a newer click superseded this load; drop it quietly
        self._pending_source_id = ""
        source = self._store.get(source_id)
        base_dir = (Path(source.location).parent
                    if source and source.kind == KIND_FILE else None)
        result = parser.parse_m3u(text, base_dir=base_dir)
        self._current_source_id = source_id
        self._current_source_name = source.name if source else ""
        self._clear_unsaved_source()
        self.infoChanged.emit()
        self._settings.set_mode("m3u", "lastSource", source_id)
        self._apply_result(result)

    @Slot(str, str)
    def _on_load_failed(self, source_id: str, message: str) -> None:
        self._inflight.pop(source_id, None)
        if source_id != self._pending_source_id:
            return
        self._pending_source_id = ""
        self._loading = False
        self._set_status(message, is_error=True)

    def _set_status(self, message: str, is_error: bool) -> None:
        self._status_message = message
        self._status_is_error = is_error
        self.statusChanged.emit()

    @Slot(str)
    def _on_engine_error(self, _message: str) -> None:
        if self._controller.activeMode != "m3u":
            return     # Local announces its own errors; stay out of its way
        current = self._model._current
        name = current.name if current else "This channel"
        self.streamError.emit(
            f"{name} could not be played — it may be offline or unreachable."
        )

    def _on_mode_changed(self) -> None:
        """The one-tuner rule (v3.4, owner decision) + last-source restore —
        both enforced here, from M3U's own files."""
        mode = self._controller.activeMode
        leaving = self._previous_mode
        self._previous_mode = mode

        if mode == "m3u":
            # Entering M3U stops whatever Local was playing.
            self._stop_playback()
            if not self._restored_last_source:
                self._restored_last_source = True
                self._restore_last_source()
        elif leaving == "m3u":
            # Leaving M3U stops the stream and clears the channel name for the title bar.
            self._current_channel_name = ""
            self.infoChanged.emit()
            self._stop_playback()

    def _restore_last_source(self) -> None:
        """Re-open the last-used source when M3U is first opened (§P2.4).
        List only — playback still starts from a click, never automatically."""
        if self._model.count > 0 or self._loading:
            return
        last_id = self._settings.get_mode("m3u", "lastSource", "")
        if last_id and self._store.get(last_id) is not None:
            self.loadSource(last_id)
