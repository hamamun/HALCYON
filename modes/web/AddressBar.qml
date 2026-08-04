import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Halcyon.Ui

// Browser navigation chrome.  This is intentionally not a player transport:
// every action below changes browser history/page state only.
Rectangle {
    id: root
    height: Theme.toolbarRowHeight
    color: Theme.baseElevated

    property var browser: null

    function currentUrl() {
        return browser && browser.activeTab ? (browser.activeTab.url || "") : ""
    }

    function syncUrlField() {
        if (!urlInput.activeFocus)
            urlInput.text = currentUrl()
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
            onClicked: if (root.browser) root.browser.goBack()
        }

        IconButton {
            glyph: Glyphs.forward
            tooltip: "Forward"
            enabled: root.browser && root.browser.activeTab.canGoForward
            onClicked: if (root.browser) root.browser.goForward()
        }

        IconButton {
            glyph: root.browser && root.browser.activeTab.loading ? Glyphs.cancel : Glyphs.refresh
            tooltip: root.browser && root.browser.activeTab.loading ? "Stop" : "Reload"
            enabled: root.browser && root.browser.tabCount > 0 && !root.browser.activeTab.internal
            onClicked: if (root.browser) root.browser.reloadOrStop()
        }

        IconButton {
            glyph: Glyphs.home
            tooltip: "Home (site homepage or Google)"
            onClicked: if (root.browser) root.browser.navigateHome()
        }

        GlassField {
            id: urlInput
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            placeholderText: root.browser && root.browser.tabCount === 0
                             ? "Search Google or enter an address"
                             : "Search or enter address"
            onActiveFocusChanged: {
                if (activeFocus)
                    selectAll()
                else
                    root.syncUrlField()
            }
            onAccepted: {
                if (!root.browser)
                    return
                root.browser.navigateActive(text)
                text = root.currentUrl()
                selectAll()
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
                if (bookmarksDropdown.visible)
                    bookmarksDropdown.hidePopup()
                else
                    bookmarksDropdown.openFor(menuButton, root.Window.window)
            }
        }
    }

    // Empty-star flow: title can be changed, URL remains the active page.
    BrowserPopup {
        id: addBookmarkPopup
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
                TextButton { text: "Cancel"; onClicked: addBookmarkPopup.hidePopup() }
                TextButton {
                    id: saveBookmarkButton
                    text: "Save"
                    primary: true
                    onClicked: {
                        if (root.browser)
                            root.browser.addBookmark(bookmarkTitleInput.text, root.currentUrl())
                        addBookmarkPopup.hidePopup()
                    }
                }
            }
        }
    }

    // Filled-star flow.  The saved page URL intentionally stays fixed: a user
    // is editing its bookmark label, not changing the page they are viewing.
    BrowserPopup {
        id: editBookmarkPopup
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
                TextButton {
                    text: "Remove"
                    onClicked: {
                        if (root.browser)
                            root.browser.removeBookmark(root.currentUrl())
                        editBookmarkPopup.hidePopup()
                    }
                }
                TextButton { text: "Cancel"; onClicked: editBookmarkPopup.hidePopup() }
                TextButton {
                    id: updateBookmarkButton
                    text: "Save"
                    primary: true
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
        browser: root.browser
    }

    Connections {
        target: root.browser
        enabled: target !== null
        function onActiveTabChanged() { root.syncUrlField() }
        function onAddressFocusRequested() {
            urlInput.forceActiveFocus()
            urlInput.selectAll()
        }
    }

    Component.onCompleted: syncUrlField()
}
