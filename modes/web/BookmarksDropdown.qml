import QtQuick
import QtQuick.Layouts
import Halcyon.Ui

// Edge-style bookmark menu.  BrowserPopup is a native owned popup so it stays
// above the WebView2 child HWND where a scene-graph Popup cannot.
BrowserPopup {
    id: root
    width: 300
    height: Math.min(420, Math.max(140, 88 + (root.browser ? root.browser.bookmarkItems.length : 0) * 52))

    property var browser: null
    property var clearDialog: null

    // The main-window anchor (the ⋯ menu button) and the main window itself,
    // remembered from openFor().  Needed when the clear-browsing dialog opens:
    // this dropdown is a separate popup Window, so `root.Window.window` is NOT
    // usable here (Window.window only supports Item types) and a button inside
    // this popup is a dead anchor once the dropdown hides.  The dialog must be
    // parented to and anchored in the main window, Edge-style.
    property Item _mainAnchor: null
    property var _mainWindow: null

    function openFor(anchorItem, ownerWindow) {
        _mainAnchor = anchorItem
        _mainWindow = ownerWindow
        showBelow(anchorItem, ownerWindow)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceSm
        spacing: Theme.spaceXs

        // Pinned top row: browser-housekeeping actions (§4.1 — one home each).
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceXs

            TextButton {
                id: clearButton
                text: "Clear browsing data"
                glyph: Glyphs.clearBrowsingData
                onClicked: {
                    root.hidePopup()
                    var dialog = root.clearDialog
                    var anchor = root._mainAnchor
                    var owner = root._mainWindow
                    if (!dialog || !anchor || !owner)
                        return
                    // Deferred one tick: showing a new Qt.Popup in the same
                    // event that hides this one lets the dropdown's close /
                    // deactivation handling dismiss the new popup on Windows.
                    Qt.callLater(function() {
                        dialog.openFor(anchor, owner)
                    })
                }
            }
            Item { Layout.fillWidth: true }
            TextButton {
                id: manageButton
                text: "Manage Bookmarks"
                glyph: Glyphs.bookmark
                onClicked: {
                    if (root.browser)
                        root.browser.openBookmarksManager()
                    root.hidePopup()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.glassBorder
        }

        Text {
            Layout.fillWidth: true
            Layout.margins: Theme.spaceMd
            visible: !root.browser || root.browser.bookmarkItems.length === 0
            text: "No bookmarks yet — use ★ to save this page."
            wrapMode: Text.WordWrap
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
        }

        ListView {
            id: bookmarksList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            visible: root.browser && root.browser.bookmarkItems.length > 0
            model: root.browser ? root.browser.bookmarkItems : []
            spacing: Theme.spaceXs

            delegate: Rectangle {
                id: bookmarkRow
                required property var modelData
                width: bookmarksList.width
                height: 48
                radius: Theme.radiusSmall
                color: rowArea.containsMouse ? Theme.glassFillHover : "transparent"

                Column {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceMd
                    anchors.topMargin: Theme.spaceXs
                    anchors.bottomMargin: Theme.spaceXs
                    spacing: 1

                    Text {
                        width: parent.width
                        text: bookmarkRow.modelData.title || bookmarkRow.modelData.url
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: bookmarkRow.modelData.url
                        color: Theme.textMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        elide: Text.ElideRight
                    }
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.browser)
                            root.browser.navigateActive(bookmarkRow.modelData.url)
                        root.hidePopup()
                    }
                }
            }
        }
    }
}
