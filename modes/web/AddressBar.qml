import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Halcyon.Ui

// Browser navigation chrome - Edge-like URL behaviour (§P3.3).
// Fixed: new tab blank, switch/close always shows correct URL, never copies old.
// Suggestions dropdown: local tabs/bookmarks + free Google suggest (no new lib).
Rectangle {
    id: root
    height: Theme.toolbarRowHeight
    color: Theme.baseElevated

    property var browser: null
    property bool stageActive: true
    property bool _isSyncing: false
    // activeTabChanged is a snapshot/update signal, not just a tab-switch
    // signal: WebView2 emits it for URL, title, loading, history and media
    // changes too.  Remember the identity separately so same-page updates can
    // never erase an address draft or dismiss its suggestions.
    property string _activeTabId: ""
    // Set when focus is being handed back from the suggestions popup so the
    // focus-in handler skips selectAll() (typing must continue, Edge-style).
    property bool _refocusingFromPopup: false

    function currentUrl() {
        return browser && browser.activeTab ? (browser.activeTab.url || "") : ""
    }

    function currentTabId() {
        return browser && browser.activeTab ? (browser.activeTab.id || "") : ""
    }

    function handleActiveTabUpdate() {
        var nextId = currentTabId()
        if (nextId !== _activeTabId) {
            _activeTabId = nextId
            urlSuggestions.hidePopup()
            syncUrlField(true)
            urlInput.focus = false
        } else {
            // Redirects still reach the bar when it is idle, but an in-progress
            // edit and its suggestion list remain wholly owned by the user.
            syncUrlField(false)
        }
    }

    // Edge-like: force=true always overwrites, even when focused - needed for tab switch/close/new
    function syncUrlField(force) {
        var shouldForce = !!force
        if (shouldForce || !urlInput.activeFocus) {
            var url = currentUrl()
            if (urlInput.text !== url) {
                _isSyncing = true
                urlInput.text = url
                _isSyncing = false
            }
        }
    }

    function commitNavigation(queryText) {
        if (!browser)
            return
        urlSuggestions.hidePopup()
        browser.navigateActive(queryText)
        // Edge moves focus to page after Enter/Go
        urlInput.focus = false
    }

    function focusInput() {
        urlInput.forceActiveFocus()
        urlInput.selectAll()
    }

    onVisibleChanged: {
        // The bookmark/suggestion popups are separate top-level native windows,
        // so hiding this bar (e.g. page fullscreen) does not hide them. Close
        // them whenever the bar disappears.
        if (!visible) {
            addBookmarkPopup.hidePopup()
            editBookmarkPopup.hidePopup()
            bookmarksDropdown.hidePopup()
            clearBrowsingDataDialog.hidePopup()
            urlSuggestions.hidePopup()
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceXs

        IconButton {
            glyph: Glyphs.back
            tooltip: "Back"
            enabled: root.browser && root.browser.activeTab.canGoBack
            onClicked: {
                urlSuggestions.hidePopup()
                if (root.browser) root.browser.goBack()
            }
        }

        IconButton {
            glyph: Glyphs.forward
            tooltip: "Forward"
            enabled: root.browser && root.browser.activeTab.canGoForward
            onClicked: {
                urlSuggestions.hidePopup()
                if (root.browser) root.browser.goForward()
            }
        }

        IconButton {
            glyph: root.browser && root.browser.activeTab.loading ? Glyphs.cancel : Glyphs.refresh
            tooltip: root.browser && root.browser.activeTab.loading ? "Stop" : "Reload"
            enabled: root.browser && root.browser.tabCount > 0 && !root.browser.activeTab.internal
            onClicked: {
                urlSuggestions.hidePopup()
                if (root.browser) root.browser.reloadOrStop()
            }
        }

        IconButton {
            glyph: Glyphs.home
            tooltip: "Home (site homepage or Google)"
            onClicked: {
                urlSuggestions.hidePopup()
                if (root.browser) root.browser.navigateHome()
                urlInput.focus = false
            }
        }

        GlassField {
            id: urlInput
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            placeholderText: root.browser && root.browser.tabCount === 0
                             ? "Search Google or enter an address"
                             : "Search or enter address"

            // Edge: clicking address bar selects all; leaving restores if not typing
            onActiveFocusChanged: {
                if (activeFocus) {
                    if (root._refocusingFromPopup) {
                        // Focus handed back from the suggestions popup — keep
                        // the caret where it was so the next letter appends
                        // instead of replacing the selection.
                        root._refocusingFromPopup = false
                    } else {
                        selectAll()
                    }
                } else {
                    // urlSuggestions IS the popup Window (a BrowserPopup), so
                    // test its own activation — `urlSuggestions.Window.window`
                    // is invalid here (Window.window only supports Item types).
                    if (urlSuggestions.visible && urlSuggestions.active) {
                        // The native suggestions window briefly took window
                        // activation (Windows quirk — should not happen with
                        // tooltip-style flags, but heal it): give typing focus
                        // back without touching the text or hiding suggestions.
                        root._refocusingFromPopup = true
                        urlInput.forceActiveFocus()
                        return
                    }
                    root.syncUrlField(false)
                    urlSuggestions.hidePopup()
                }
            }

            // While typing show suggestions - suppress during forced sync (tab switch)
            onTextChanged: {
                if (root._isSyncing)
                    return
                if (!activeFocus)
                    return
                var trimmed = text.trim()
                if (trimmed.length > 0 && root.browser) {
                    urlSuggestions.showFor(urlInput, root.Window.window, text)
                } else {
                    urlSuggestions.hidePopup()
                }
            }

            // Keyboard handling - Edge style
            Keys.onPressed: function(event) {
                if (urlSuggestions.visible) {
                    if (event.key === Qt.Key_Down) {
                        urlSuggestions.selectNext()
                        event.accepted = true
                        return
                    } else if (event.key === Qt.Key_Up) {
                        urlSuggestions.selectPrev()
                        event.accepted = true
                        return
                    }
                }
            }

            Keys.onEscapePressed: function(event) {
                // First Esc hides suggestions, second restores URL, third blurs
                if (urlSuggestions.visible) {
                    urlSuggestions.hidePopup()
                    event.accepted = true
                    return
                }
                var realUrl = root.currentUrl()
                if (text !== realUrl) {
                    root.syncUrlField(true)
                    selectAll()
                    event.accepted = true
                    return
                }
                // Already restored -> blur to page (Edge behaviour)
                focus = false
                event.accepted = true
            }

            // TextField emits accepted for both the main Return key and the
            // numeric-keypad Enter key. Keep one path for both so neither key
            // is swallowed and navigation can never be committed twice.
            onAccepted: {
                if (urlSuggestions.visible && urlSuggestions.hasSelection) {
                    urlSuggestions.acceptSelection()
                    return
                }
                if (!root.browser)
                    return
                root.commitNavigation(text)
            }
        }

        // Go button - Edge-like
        IconButton {
            glyph: "\u203A"
            plainTextGlyph: true
            tooltip: "Go"
            enabled: urlInput.text.trim().length > 0
            onClicked: {
                if (!root.browser)
                    return
                if (urlSuggestions.visible && urlSuggestions.hasSelection) {
                    urlSuggestions.acceptSelection()
                    return
                }
                root.commitNavigation(urlInput.text)
            }
        }

        IconButton {
            id: starButton
            property bool saved: root.browser && root.browser.activeTabBookmarked
            glyph: saved ? Glyphs.bookmarkFilled : Glyphs.bookmark
            tooltip: saved ? "Edit or remove bookmark" : "Bookmark this page"
            enabled: root.browser && root.browser.tabCount > 0
                     && !!root.browser.activeTab.url && !root.browser.activeTab.internal
            active: saved
            onClicked: {
                urlSuggestions.hidePopup()
                if (saved)
                    editBookmarkPopup.showBelow(starButton, root.Window.window)
                else
                    addBookmarkPopup.showBelow(starButton, root.Window.window)
            }
        }

        IconButton {
            id: menuButton
            glyph: Glyphs.more
            tooltip: "Bookmarks"
            onClicked: {
                urlSuggestions.hidePopup()
                if (bookmarksDropdown.visible)
                    bookmarksDropdown.hidePopup()
                else
                    bookmarksDropdown.openFor(menuButton, root.Window.window)
            }
        }
    }

    // Bookmark add/edit popups unchanged
    BrowserPopup {
        id: addBookmarkPopup
        objectName: "addBookmarkPopup"
        stageActive: root.stageActive
        width: 340
        height: 164
        onVisibleChanged: {
            if (visible)
                bookmarkTitleInput.text = root.browser && root.browser.activeTab
                                          ? (root.browser.activeTab.title || root.browser.activeTab.url) : ""
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spaceLg
            spacing: Theme.spaceSm

            Text {
                text: "Add Bookmark"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarge
                font.weight: Theme.weightBold
            }

            GlassField {
                id: bookmarkTitleInput
                Layout.fillWidth: true
                placeholderText: "Title"
                onAccepted: saveBookmarkButton.clicked()
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spaceSm
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: addBookmarkPopup.hidePopup()
                }
                IconButton {
                    id: saveBookmarkButton
                    glyph: Glyphs.save
                    tooltip: "Save"
                    onClicked: {
                        if (root.browser)
                            root.browser.addBookmark(bookmarkTitleInput.text, root.currentUrl())
                        addBookmarkPopup.hidePopup()
                    }
                }
            }
        }
    }

    BrowserPopup {
        id: editBookmarkPopup
        objectName: "editBookmarkPopup"
        stageActive: root.stageActive
        width: 340
        height: 164
        onVisibleChanged: {
            if (!visible || !root.browser)
                return
            var saved = root.browser.bookmarks.getByUrl(root.currentUrl())
            editTitleInput.text = saved ? (saved.title || "") : ""
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spaceLg
            spacing: Theme.spaceSm

            Text {
                text: "Edit Bookmark"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarge
                font.weight: Theme.weightBold
            }

            GlassField {
                id: editTitleInput
                Layout.fillWidth: true
                placeholderText: "Title"
                onAccepted: updateBookmarkButton.clicked()
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spaceSm
                IconButton {
                    glyph: Glyphs.deleteItem
                    tooltip: "Remove bookmark"
                    onClicked: {
                        if (root.browser)
                            root.browser.removeBookmark(root.currentUrl())
                        editBookmarkPopup.hidePopup()
                    }
                }
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: editBookmarkPopup.hidePopup()
                }
                IconButton {
                    id: updateBookmarkButton
                    glyph: Glyphs.save
                    tooltip: "Save"
                    onClicked: {
                        if (root.browser)
                            root.browser.updateBookmark(root.currentUrl(), editTitleInput.text,
                                                        root.currentUrl())
                        editBookmarkPopup.hidePopup()
                    }
                }
            }
        }
    }

    BookmarksDropdown {
        id: bookmarksDropdown
        stageActive: root.stageActive
        browser: root.browser
        clearDialog: clearBrowsingDataDialog
    }

    ClearBrowsingDataDialog {
        id: clearBrowsingDataDialog
        stageActive: root.stageActive
        browser: root.browser
        onCleared: {
            // data cleared — nothing else to do; dialog hides itself
        }
    }

    // Edge-like omnibox - local + free Google suggest
    UrlSuggestionsDropdown {
        id: urlSuggestions
        stageActive: root.stageActive
        browser: root.browser
        onSuggestionAccepted: function(text) {
            root.commitNavigation(text)
        }
    }

    Connections {
        target: root.browser
        enabled: target !== null
        // activeTabChanged also fires for same-tab URL/title/loading/history/
        // media updates. Only a real tab identity change may discard the
        // current edit. Same-tab updates refresh the displayed URL only while
        // the field is not being edited and leave suggestions/focus untouched.
        function onActiveTabChanged() {
            root.handleActiveTabUpdate()
        }
        function onTabsChanged() {
            // When last tab closed -> blank (Edge)
            if (root.browser && root.browser.tabCount === 0) {
                urlSuggestions.hidePopup()
                root.syncUrlField(true)
                urlInput.focus = false
            }
        }
        function onActiveTabIndexChanged() {
            // Handle the index signal too, but decide by stable tab identity:
            // closing a tab to the left changes the index without changing the
            // active page and must not interrupt an address edit.
            root.handleActiveTabUpdate()
        }
        function onAddressFocusRequested() {
            // New blank tab -> blank + focused + select all (Edge)
            urlSuggestions.hidePopup()
            root.syncUrlField(true)
            urlInput.forceActiveFocus()
            urlInput.selectAll()
        }
    }

    Component.onCompleted: {
        _activeTabId = currentTabId()
        syncUrlField(true)
    }
}
