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
            return channel.logo
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
    carry signals, so they live on this small long-referenced object."""

    succeeded = Signal(str, str)   # source id, playlist text
    failed = Signal(str, str)      # source id, human message


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

        if error is not None:
            self._signals.failed.emit(self._source.id, error)
        else:
            self._signals.succeeded.emit(self._source.id, text)


class M3UContext(QObject):
    """The object published to QML as ``modeContext_m3u``.

    Owns the channel model, the saved-sources store and all source loading;
    enforces the owner's two behaviour rules from inside M3U (§P2.3/§P2.4).
    The shell never names it — it is found through the registry (§A.2).
    """

    sourcesChanged = Signal()
    statusChanged = Signal()
    infoChanged = Signal()

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

        self._status_message = ""
        self._status_is_error = False
        self._loading = False
        self._current_source_name = ""
        self._current_source_id = ""
        self._unsaved_source_name = ""
        self._unsaved_source_kind = ""
        self._unsaved_source_location = ""
        self._last_attempted_id = ""
        self._pending_source_id = ""
        self._inflight: dict[str, _LoadSignals] = {}

        self._previous_mode = controller.activeMode
        self._restored_last_source = False

        grouping = settings.get_mode("m3u", "grouping", GROUPING_CATEGORY)
        self._model.setGrouping(
            grouping if grouping in (GROUPING_NONE, GROUPING_CATEGORY, GROUPING_COUNTRY)
            else GROUPING_CATEGORY
        )

        # Stream play errors surface in the panel with the retry affordance
        # (§M2.4) — clear message, no crash, no hang. Local surfaces its own
        # errors; this handler only speaks while M3U is the active mode.
        self._failed_channel_url = ""
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
        source = self._store.get(source_id)
        ok = self._store.remove(source_id)
        if ok:
            self._favourites.remove_source(source_id)
            if self._settings.get_mode("m3u", "lastSource", "") == source_id:
                self._settings.set_mode("m3u", "lastSource", "")
            if source_id == self._current_source_id:
                self._current_source_id = ""
                if self._model.favouritesOnly:
                    self._model.setFavouritesOnly(False)
                self._model.set_favourites(set())
                if source is not None:
                    self._remember_unsaved_source(source.name, source.kind, source.location)
                    self._current_source_name = f"{source.name} (not saved)"
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
        self._failed_channel_url = ""
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
        QThreadPool.globalInstance().start(_LoadWorker(source, signals))

    @Slot()
    def retry(self) -> None:  # noqa: N802
        """The one retry affordance (§M2.4). A failed *load* refetches the
        source; a failed *channel* reopens the stream URL."""
        if self._failed_channel_url:
            url, self._failed_channel_url = self._failed_channel_url, ""
            self._set_status("", is_error=False)
            self._engine.open(url)
            return
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
        self._model.clear()
        self._set_status("", is_error=False)

    # ------------------------------------------------------------ internals --
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
        self._engine.open(url)

    def _stop_playback(self) -> None:
        try:
            if self._engine.currentMedia:
                self._engine.stop()
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
        self._failed_channel_url = current.url if current else ""
        name = current.name if current else "This channel"
        self._set_status(
            f"{name} could not be played — it may be offline or unreachable.",
            is_error=True,
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
            # Leaving M3U stops the stream (list + last channel stay put).
            self._stop_playback()

    def _restore_last_source(self) -> None:
        """Re-open the last-used source when M3U is first opened (§P2.4).
        List only — playback still starts from a click, never automatically."""
        if self._model.count > 0 or self._loading:
            return
        last_id = self._settings.get_mode("m3u", "lastSource", "")
        if last_id and self._store.get(last_id) is not None:
            self.loadSource(last_id)
