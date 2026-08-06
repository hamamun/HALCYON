import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// Clear Browsing Data dialog — the one place every browser-data wipe lives
// (§4.1). A native owned popup window (BrowserPopup) so it floats above the
// WebView2 child HWND where a scene-graph Dialog would sit *under* the page.
//
// Opened from the bookmarks dropdown's "Clear browsing data" button.  The
// dropdown passes the MAIN window's ⋯ menu-button anchor and the main window
// itself (a popup Window cannot use Window.window and dies as an anchor once
// hidden) — so this dialog opens Edge-style below the menu button.
BrowserPopup {
    id: root
    width: 380
    height: 480
    acceptsFocus: true

    property var browser: null

    // The eight checkboxes are fixed rows below; on Clear we read each one.
    // timeRanges: 0 minutes means "All time".
    property var timeRanges: [
        { label: "Last hour", minutes: 60 },
        { label: "Last 24 hours", minutes: 60 * 24 },
        { label: "Last 7 days", minutes: 60 * 24 * 7 },
        { label: "Last 4 weeks", minutes: 60 * 24 * 7 * 4 },
        { label: "All time", minutes: 0 }
    ]
    property int selectedRangeIndex: 1   // default: Last 24 hours

    // On-disk cache size in bytes, probed once per open (walking the profile
    // is cheap but not free) and again after a clear.  Only the cache is
    // measurable, so the "Freed space" line is driven by the cache checkbox.
    property real cacheBytes: 0

    signal cleared()

    function openFor(anchorItem, ownerWindow) {
        // Keep the dialog inside the owner window on short screens: shrink it
        // to the space between the anchor and the window's bottom edge.
        if (anchorItem && ownerWindow) {
            var anchorBottom = anchorItem.mapToGlobal(0, anchorItem.height).y + Theme.spaceXs
            var ownerBottom = ownerWindow.y + ownerWindow.height
            root.height = Math.max(280, Math.min(480, ownerBottom - anchorBottom))
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
        if (visible)
            refreshCacheSize()
    }

    // Collect the ticked option ids and the chosen time window, then clear.
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
        var minutes = timeRanges[selectedRangeIndex].minutes
        if (root.browser)
            root.browser.clearBrowsingData(picked, minutes)
        refreshCacheSize()
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

        // time-range dropdown
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm
            Text {
                text: "Time range:"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.textMuted
                Layout.alignment: Qt.AlignVCenter
            }
            ComboBox {
                id: rangeCombo
                Layout.fillWidth: true
                implicitHeight: 32
                textRole: "label"
                valueRole: "minutes"
                model: root.timeRanges
                currentIndex: root.selectedRangeIndex
                onCurrentIndexChanged: root.selectedRangeIndex = currentIndex
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: Theme.glassFill
                    border.width: 1
                    border.color: Theme.glassBorder
                }

                contentItem: Text {
                    leftPadding: Theme.spaceMd
                    text: rangeCombo.displayText
                    font: rangeCombo.font
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                }

                delegate: ItemDelegate {
                    id: delegateItem
                    width: rangeCombo.width
                    text: model.label
                    font: rangeCombo.font
                    highlighted: rangeCombo.highlightedIndex === index

                    contentItem: Text {
                        text: delegateItem.text
                        font: delegateItem.font
                        color: delegateItem.highlighted ? Theme.accent : Theme.text
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }

                    background: Rectangle {
                        color: delegateItem.highlighted ? Theme.glassFillHover : "transparent"
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.glassBorder
        }

        // checkbox list — fixed 8 rows, each with an optional subtitle line
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
        // Only the cache size is measurable (history/cookies are not), so the
        // number appears while "Cached images and files" is selected.
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
                onClicked: root.hidePopup()
            }
            IconButton {
                text: "Clear"
                tooltip: "Clear"
                glyph: Glyphs.clearBrowsingData
                active: true
                onClicked: root.clearData()
            }
        }
    }
}
