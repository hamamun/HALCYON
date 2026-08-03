"""Per-session tabs for Web mode (§P3.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot

from modes.web.bookmarks import favicon_for, normalise_url, title_for_url

MAX_TABS = 15
MANAGER_URL = "halcyon://bookmarks"


@dataclass(slots=True)
class Tab:
    title: str = "New tab"
    url: str = "about:blank"
    favicon: str = ""
    loading: bool = False
    is_manager: bool = False
    history: list[str] = field(default_factory=list)
    history_index: int = -1

    @property
    def can_go_back(self) -> bool:
        return self.history_index > 0

    @property
    def can_go_forward(self) -> bool:
        return 0 <= self.history_index < len(self.history) - 1


class TabModel(QAbstractListModel):
    """A browser-like tab strip, kept only for this app session."""

    TitleRole = Qt.UserRole + 1
    UrlRole = Qt.UserRole + 2
    FaviconRole = Qt.UserRole + 3
    ActiveRole = Qt.UserRole + 4
    LoadingRole = Qt.UserRole + 5
    ManagerRole = Qt.UserRole + 6
    CanGoBackRole = Qt.UserRole + 7
    CanGoForwardRole = Qt.UserRole + 8

    countChanged = Signal()
    activeChanged = Signal()
    changed = Signal()
    limitReached = Signal()

    _ROLE_NAMES = {
        TitleRole: b"title",
        UrlRole: b"url",
        FaviconRole: b"favicon",
        ActiveRole: b"isActive",
        LoadingRole: b"isLoading",
        ManagerRole: b"isManager",
        CanGoBackRole: b"canGoBack",
        CanGoForwardRole: b"canGoForward",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tabs: list[Tab] = []
        self._active = -1

    # ---------------------------------------------------------------- model --
    def roleNames(self):  # noqa: N802
        return self._ROLE_NAMES

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._tabs)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._tabs)):
            return None
        tab = self._tabs[index.row()]
        if role in (Qt.DisplayRole, self.TitleRole):
            return tab.title
        if role == self.UrlRole:
            return tab.url
        if role == self.FaviconRole:
            return tab.favicon
        if role == self.ActiveRole:
            return index.row() == self._active
        if role == self.LoadingRole:
            return tab.loading
        if role == self.ManagerRole:
            return tab.is_manager
        if role == self.CanGoBackRole:
            return tab.can_go_back
        if role == self.CanGoForwardRole:
            return tab.can_go_forward
        return None

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._tabs)

    @Property(int, notify=activeChanged)
    def activeIndex(self) -> int:  # noqa: N802
        return self._active

    @Property(str, notify=activeChanged)
    def activeUrl(self) -> str:  # noqa: N802
        tab = self.active_tab()
        return tab.url if tab else ""

    @Property(str, notify=activeChanged)
    def activeTitle(self) -> str:  # noqa: N802
        tab = self.active_tab()
        return tab.title if tab else ""

    @Property(str, notify=activeChanged)
    def activeFavicon(self) -> str:  # noqa: N802
        tab = self.active_tab()
        return tab.favicon if tab else ""

    @Property(bool, notify=activeChanged)
    def hasActiveTab(self) -> bool:  # noqa: N802
        return self.active_tab() is not None

    @Property(bool, notify=activeChanged)
    def activeIsManager(self) -> bool:  # noqa: N802
        tab = self.active_tab()
        return bool(tab and tab.is_manager)

    @Property(bool, notify=activeChanged)
    def canGoBack(self) -> bool:  # noqa: N802
        tab = self.active_tab()
        return bool(tab and tab.can_go_back)

    @Property(bool, notify=activeChanged)
    def canGoForward(self) -> bool:  # noqa: N802
        tab = self.active_tab()
        return bool(tab and tab.can_go_forward)

    # --------------------------------------------------------------- actions --
    @Slot(result=bool)
    def newBlankTab(self) -> bool:  # noqa: N802
        return self.open_url("about:blank", blank=True)

    @Slot(str, result=bool)
    def openUrl(self, text: str) -> bool:  # noqa: N802
        return self.open_url(text)

    @Slot(result=bool)
    def openManager(self) -> bool:  # noqa: N802
        # Reuse an existing manager tab if one is open.
        for i, tab in enumerate(self._tabs):
            if tab.is_manager:
                self.activate(i)
                return True
        return self._append(Tab(
            title="Bookmarks",
            url=MANAGER_URL,
            favicon="",
            is_manager=True,
            history=[MANAGER_URL],
            history_index=0,
        ))

    @Slot(int)
    def activate(self, index: int) -> None:
        index = int(index)
        if not (0 <= index < len(self._tabs)) or index == self._active:
            return
        old = self._active
        self._active = index
        self._emit_rows([old, self._active])
        self.activeChanged.emit()
        self.changed.emit()

    @Slot(int)
    def close(self, index: int) -> None:
        index = int(index)
        if not (0 <= index < len(self._tabs)):
            return
        self.beginRemoveRows(QModelIndex(), index, index)
        del self._tabs[index]
        self.endRemoveRows()
        if not self._tabs:
            self._active = -1
        elif self._active == index:
            self._active = min(index, len(self._tabs) - 1)
        elif self._active > index:
            self._active -= 1
        self.countChanged.emit()
        self.activeChanged.emit()
        self.changed.emit()

    @Slot(str)
    def navigateActive(self, text: str) -> None:  # noqa: N802
        url = normalise_url(text)
        if not url:
            return
        if self._active < 0:
            self.open_url(url)
            return
        tab = self._tabs[self._active]
        tab.is_manager = False
        self._navigate_tab(tab, url)
        self._emit_rows([self._active])
        self.activeChanged.emit()
        self.changed.emit()

    @Slot()
    def back(self) -> None:
        tab = self.active_tab()
        if not tab or not tab.can_go_back:
            return
        tab.history_index -= 1
        self._apply_history(tab)
        self._active_row_changed()

    @Slot()
    def forward(self) -> None:
        tab = self.active_tab()
        if not tab or not tab.can_go_forward:
            return
        tab.history_index += 1
        self._apply_history(tab)
        self._active_row_changed()

    @Slot()
    def reload(self) -> None:
        tab = self.active_tab()
        if not tab:
            return
        tab.loading = True
        self._active_row_changed()
        tab.loading = False
        self._active_row_changed()

    @Slot()
    def stop(self) -> None:
        tab = self.active_tab()
        if not tab:
            return
        tab.loading = False
        self._active_row_changed()

    @Slot()
    def home(self) -> None:
        self.navigateActive("https://www.bing.com")

    def open_url(self, text: str, *, blank: bool = False) -> bool:
        if blank:
            tab = Tab(title="New tab", url="about:blank", history=["about:blank"], history_index=0)
        else:
            url = normalise_url(text)
            if not url:
                return False
            tab = Tab()
            self._navigate_tab(tab, url)
        return self._append(tab)

    def active_tab(self) -> Tab | None:
        if 0 <= self._active < len(self._tabs):
            return self._tabs[self._active]
        return None

    def _append(self, tab: Tab) -> bool:
        if len(self._tabs) >= MAX_TABS:
            self.limitReached.emit()
            return False
        row = len(self._tabs)
        old = self._active
        self.beginInsertRows(QModelIndex(), row, row)
        self._tabs.append(tab)
        self._active = row
        self.endInsertRows()
        self.countChanged.emit()
        self._emit_rows([old, row])
        self.activeChanged.emit()
        self.changed.emit()
        return True

    def _navigate_tab(self, tab: Tab, url: str) -> None:
        url = normalise_url(url)
        tab.url = url
        tab.title = title_for_url(url)
        tab.favicon = favicon_for(url)
        tab.loading = False
        if tab.history_index < len(tab.history) - 1:
            tab.history = tab.history[: tab.history_index + 1]
        tab.history.append(url)
        tab.history_index = len(tab.history) - 1

    def _apply_history(self, tab: Tab) -> None:
        url = tab.history[tab.history_index]
        tab.url = url
        tab.title = title_for_url(url)
        tab.favicon = favicon_for(url)
        tab.is_manager = (url == MANAGER_URL)
        tab.loading = False

    def _active_row_changed(self) -> None:
        self._emit_rows([self._active])
        self.activeChanged.emit()
        self.changed.emit()

    def _emit_rows(self, rows: list[int]) -> None:
        for row in set(rows):
            if 0 <= row < len(self._tabs):
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, list(self._ROLE_NAMES))


def display_url(url: str) -> str:
    if not url or url == "about:blank":
        return ""
    if url == MANAGER_URL:
        return "Bookmarks"
    parsed = urlparse(url)
    return parsed.geturl()
