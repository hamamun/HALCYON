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
//
// SIMPLE BY DESIGN: there is NO time-range dropdown.  Every clear wipes the
// ticked kinds for ALL TIME (WebView2's one-argument ClearBrowsingDataAsync
// is the documented all-time form).  Tick the rows you want gone, hit Clear.
BrowserPopup {
    id: root
    width: 380
    height: 440
    acceptsFocus: true

    property var browser: null

    // On-disk cache size in bytes, probed once per open and again after a
    // clear completes, so the "will be cleared" line always shows the real
    // current number (0 once the cache is actually gone).
    property int cacheBytes: 0

    // True while the native clear is running — disables Clear and shows a
    // busy label so the user can't double-click.
    property bool clearing: false

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

    function refreshCacheSize() {
        cacheBytes = root.browser ? root.browser.cacheSizeBytes() : 0
    }

    function formatBytes(n) {
        if (n <= 0)
            return "0 MB"
        var mb = n / (1024 * 1024)
        if (mb >= 1024)
            return "~" + (mb / 1024).toFixed(2) + " GB"
        if (mb < 1)
            return "less than 1 MB"
        return "~" + (mb < 10 ? mb.toFixed(1) : Math.round(mb).toString()) + " MB"
    }

    onVisibleChanged: {
        if (visible) {
            clearing = false
            refreshCacheSize()
        }
    }

    // Collect the ticked rows and clear them ALL TIME.  The browser slot is
    // synchronous from the GUI thread's point of view (it waits on the .NET
    // Task, pumping Qt events), so by the time we return the cache folders
    // are already wiped and the size line can show the real post-clear size.
    function clearData() {
        var picked = []
        if (cb0.checked) picked.push("browsingHistory")
        if (cb1.checked) picked.push("downloadHistory")
        if (cb2.checked) picked.push("cookies")
        if (cb3.checked) picked.push("cache")
        if (cb4.checked) picked.push("passwords")
        if (cb5.checked) picked.push("autofill")
        if (cb6.checked) picked.push("sitePermissions")
        if (cb7.checked) picked.push("serviceWorkers")
        if (picked.length === 0) {
            root.hidePopup()
            return
        }
        clearing = true
        if (root.browser)
            root.browser.clearBrowsingDataAll(picked)
        refreshCacheSize()
        clearing = false
        root.cleared()
        root.hidePopup()
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

        // hint — no dropdown: everything ticked clears for all time
        Text {
            Layout.fillWidth: true
            text: "Everything you tick is cleared for all time."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textMuted
            elide: Text.ElideRight
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

        // Freed-space estimate — updates live as the cache box is ticked.
        // Only the cache size is measurable, so the number appears while
        // "Cached images and files" is selected.
        Text {
            Layout.fillWidth: true
            visible: cb3.checked && root.cacheBytes > 0
            text: root.formatBytes(root.cacheBytes) + " will be cleared"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textMuted
            elide: Text.ElideRight
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
                enabled: !root.clearing
                onClicked: root.hidePopup()
            }
            IconButton {
                id: clearBtn
                text: root.clearing ? "Clearing…" : "Clear"
                tooltip: "Clear"
                glyph: Glyphs.clearBrowsingData
                active: true
                enabled: !root.clearing
                onClicked: root.clearData()
            }
        }
    }
}
