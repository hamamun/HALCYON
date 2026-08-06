import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// Clear Browsing Data dialog — the one place every browser-data wipe lives.
// A native owned popup window (BrowserPopup) so it floats above the WebView2
// child HWND where a scene-graph Dialog would sit *under* the page.
//
// Opened from the bookmarks dropdown's "Clear browsing data" button.  The
// dropdown passes the MAIN window's ⋯ menu-button anchor and the main window
// itself (a popup Window cannot use Window.window and dies as an anchor once
// hidden) — so this dialog opens Edge-style below the menu button.
BrowserPopup {
    id: root
    width: 380
    height: 440
    acceptsFocus: true

    property var browser: null

    signal cleared()

    function openFor(anchorItem, ownerWindow) {
        // Keep the dialog inside the owner window on short screens: shrink it
        // to the space between the anchor and the window's bottom edge.
        if (anchorItem && ownerWindow) {
            var anchorBottom = anchorItem.mapToGlobal(0, anchorItem.height).y + Theme.spaceXs
            var ownerBottom = ownerWindow.y + ownerWindow.height
            root.height = Math.max(280, Math.min(440, ownerBottom - anchorBottom))
        }
        showBelow(anchorItem, ownerWindow)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceLg
        spacing: Theme.spaceMd

        // title
        Text {
            text: "Clear browsing data"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.weightBold
            color: Theme.text
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.glassBorder
        }

        // checkbox list — fixed 8 rows
        Flickable {
            id: optionsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: optionsColumn.height
            boundsBehavior: Flickable.StopAtBounds
            ColumnLayout {
                id: optionsColumn
                width: optionsList.width
                spacing: 0

                CheckBoxRow {
                    id: cb0
                    optionId: "browsingHistory"
                    label: "Browsing history"
                    defaultTick: true
                    destructive: false
                    note: "Address-bar suggestions disappear, history is empty."
                }
                CheckBoxRow {
                    id: cb1
                    optionId: "downloadHistory"
                    label: "Download history"
                    defaultTick: false
                    destructive: false
                    note: "The list clears — files already saved stay on disk."
                }
                CheckBoxRow {
                    id: cb2
                    optionId: "cookies"
                    label: "Cookies and site data"
                    defaultTick: true
                    destructive: true
                }
                CheckBoxRow {
                    id: cb3
                    optionId: "cache"
                    label: "Cached images and files"
                    defaultTick: true
                    destructive: false
                    note: "The big space-saver. Pages load slowly once, then speed back up."
                }
                CheckBoxRow {
                    id: cb4
                    optionId: "passwords"
                    label: "Passwords"
                    defaultTick: false
                    destructive: true
                }
                CheckBoxRow {
                    id: cb5
                    optionId: "autofill"
                    label: "Autofill form data"
                    defaultTick: false
                    destructive: true
                }
                CheckBoxRow {
                    id: cb6
                    optionId: "sitePermissions"
                    label: "Site permissions"
                    defaultTick: false
                    destructive: false
                    note: "Camera, location and mic reset — sites will ask again."
                }
                CheckBoxRow {
                    id: cb7
                    optionId: "serviceWorkers"
                    label: "Service workers and offline data"
                    defaultTick: false
                    destructive: false
                    note: "Offline sites re-download; can fix broken sites."
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.glassBorder
        }

        // footer: Cancel + Clear
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            Item { Layout.fillWidth: true }
            IconButton {
                text: "Cancel"
                tooltip: "Cancel"
                glyph: Glyphs.cancel
                onClicked: root.hidePopup()
            }
            IconButton {
                id: clearBtn
                text: "Clear"
                tooltip: "Clear"
                glyph: Glyphs.clearBrowsingData
                active: true
                // Clean state: button present, no clearing logic wired yet.
                onClicked: {}
            }
        }
    }
}
