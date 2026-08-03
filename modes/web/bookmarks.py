"""Bookmarks for Web mode (§P3.5).

The store belongs to ``modes/web`` alone: deleting Web mode deletes bookmarks
without touching Local queues or M3U sources.  QML reads it through a small
``QAbstractListModel`` so the dropdown and the manager tab share one source of
truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot

from core import paths

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Bookmark:
    title: str
    url: str
    favicon: str = ""


class BookmarkModel(QAbstractListModel):
    """Persistent bookmark list with simple add/edit/delete/reorder/search."""

    CountRole = Qt.UserRole + 1
    TitleRole = Qt.UserRole + 2
    UrlRole = Qt.UserRole + 3
    FaviconRole = Qt.UserRole + 4
    SourceIndexRole = Qt.UserRole + 5

    countChanged = Signal()
    filterChanged = Signal()
    changed = Signal()

    _ROLE_NAMES = {
        CountRole: b"count",
        TitleRole: b"title",
        UrlRole: b"url",
        FaviconRole: b"favicon",
        SourceIndexRole: b"sourceIndex",
    }

    def __init__(self, store_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._store_path = store_path or paths.data_file("web_bookmarks.json")
        self._items: list[Bookmark] = []
        self._filter = ""
        self._visible: list[int] = []
        self._load()

    # ---------------------------------------------------------------- model --
    def roleNames(self):  # noqa: N802 - Qt API
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return len(self._visible)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._visible)):
            return None
        source = self._visible[index.row()]
        item = self._items[source]
        if role in (Qt.DisplayRole, self.TitleRole):
            return item.title
        if role == self.UrlRole:
            return item.url
        if role == self.FaviconRole:
            return item.favicon
        if role == self.SourceIndexRole:
            return source
        if role == self.CountRole:
            return len(self._items)
        return None

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._visible)

    @Property(int, notify=countChanged)
    def totalCount(self) -> int:  # noqa: N802 - QML-facing
        return len(self._items)

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:  # noqa: N802 - QML-facing
        return self._filter

    @Slot(str)
    def setFilter(self, text: str) -> None:  # noqa: N802 - QML-facing
        text = str(text or "")
        if text == self._filter:
            return
        self._filter = text
        self.filterChanged.emit()
        self._rebuild_visible()

    # --------------------------------------------------------------- actions --
    @Slot(str, str, result=bool)
    def addBookmark(self, title: str, url: str) -> bool:  # noqa: N802
        url = normalise_url(url)
        if not url:
            return False
        title = clean_title(title, url)
        existing = self.index_of_url(url)
        if existing >= 0:
            self.updateBookmark(existing, title, url)
            return True
        self.beginResetModel()
        self._items.append(Bookmark(title=title, url=url, favicon=favicon_for(url)))
        self._visible = self._compute_visible()
        self.endResetModel()
        self._save_emit()
        return True

    @Slot(int, str, str, result=bool)
    def updateBookmark(self, source_index: int, title: str, url: str) -> bool:  # noqa: N802
        if not (0 <= int(source_index) < len(self._items)):
            return False
        url = normalise_url(url)
        if not url:
            return False
        source_index = int(source_index)
        self._items[source_index] = Bookmark(
            title=clean_title(title, url),
            url=url,
            favicon=favicon_for(url),
        )
        row = self._visible.index(source_index) if source_index in self._visible else -1
        if row >= 0:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [self.TitleRole, self.UrlRole, self.FaviconRole])
        self._save_emit()
        return True

    @Slot(int, result=bool)
    def deleteBookmark(self, source_index: int) -> bool:  # noqa: N802
        if not (0 <= int(source_index) < len(self._items)):
            return False
        source_index = int(source_index)
        self.beginResetModel()
        del self._items[source_index]
        self._visible = self._compute_visible()
        self.endResetModel()
        self._save_emit()
        return True

    @Slot(int, int, result=bool)
    def moveBookmark(self, source_index: int, target_index: int) -> bool:  # noqa: N802
        source_index = int(source_index)
        target_index = int(target_index)
        if not (0 <= source_index < len(self._items)):
            return False
        target_index = max(0, min(target_index, len(self._items) - 1))
        if source_index == target_index:
            return True
        self.beginResetModel()
        item = self._items.pop(source_index)
        self._items.insert(target_index, item)
        self._visible = self._compute_visible()
        self.endResetModel()
        self._save_emit()
        return True

    @Slot(str, result=int)
    def indexOfUrl(self, url: str) -> int:  # noqa: N802 - QML-facing
        return self.index_of_url(url)

    @Slot(int, result="QVariant")
    def get(self, source_index: int):
        if not (0 <= int(source_index) < len(self._items)):
            return {}
        item = self._items[int(source_index)]
        return asdict(item)

    def index_of_url(self, url: str) -> int:
        target = canonical_url(url)
        if not target:
            return -1
        for i, item in enumerate(self._items):
            if canonical_url(item.url) == target:
                return i
        return -1

    # -------------------------------------------------------------- storage --
    def _load(self) -> None:
        if not self._store_path.exists():
            self._items = _default_bookmarks()
            self._visible = self._compute_visible()
            self._save()
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("could not read web bookmarks: %s", self._store_path)
            raw = []
        items: list[Bookmark] = []
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict):
                continue
            url = normalise_url(entry.get("url", ""))
            if not url:
                continue
            items.append(Bookmark(
                title=clean_title(entry.get("title", ""), url),
                url=url,
                favicon=str(entry.get("favicon", "") or favicon_for(url)),
            ))
        self._items = items or _default_bookmarks()
        self._visible = self._compute_visible()

    def _save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item) for item in self._items]
        tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._store_path)

    def _save_emit(self) -> None:
        self._save()
        self.countChanged.emit()
        self.changed.emit()

    def _compute_visible(self) -> list[int]:
        needle = self._filter.strip().lower()
        if not needle:
            return list(range(len(self._items)))
        return [
            i for i, item in enumerate(self._items)
            if needle in item.title.lower() or needle in item.url.lower()
        ]

    def _rebuild_visible(self) -> None:
        self.beginResetModel()
        self._visible = self._compute_visible()
        self.endResetModel()
        self.countChanged.emit()


def normalise_url(text: str) -> str:
    """Turn user text into a navigable URL, preserving searches elsewhere."""
    text = str(text or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "file://", "about:")):
        return text
    if "://" in text:
        return text
    # Looks like a host or local intranet name.
    if "." in text and " " not in text:
        return "https://" + text
    return "https://www.bing.com/search?q=" + _quote_search(text)


def canonical_url(text: str) -> str:
    url = normalise_url(text)
    if not url:
        return ""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{netloc}{path}?{parsed.query}" if parsed.query else f"{scheme}://{netloc}{path}"


def clean_title(title: str, url: str) -> str:
    title = str(title or "").strip()
    if title:
        return title[:160]
    parsed = urlparse(normalise_url(url))
    host = parsed.netloc or parsed.path or "Bookmark"
    return host.replace("www.", "", 1)[:160]


def favicon_for(url: str) -> str:
    parsed = urlparse(normalise_url(url))
    if not parsed.netloc:
        return ""
    # Google favicon endpoint keeps QML Image loading simple and cacheable.
    return f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32"


def title_for_url(url: str) -> str:
    parsed = urlparse(normalise_url(url))
    if parsed.netloc:
        return parsed.netloc.replace("www.", "", 1)
    if parsed.scheme == "about":
        return "New tab"
    return clean_title("", url)


def _quote_search(text: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(text)


def _default_bookmarks() -> list[Bookmark]:
    defaults = [
        ("YouTube", "https://www.youtube.com"),
        ("Google", "https://www.google.com"),
        ("GitHub", "https://github.com"),
    ]
    return [Bookmark(title=t, url=u, favicon=favicon_for(u)) for t, u in defaults]
