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
    // timeRanges: 0 minutes means "All time" (translated to None in browser.py).
    property var timeRanges: [
        { label: "Last hour", minutes: 60 },
        { label: "Last 24 hours", minutes: 60 * 24 },
        { label: "Last 7 days", minutes: 60 * 24 * 7 },
        { label: "Last 4 weeks", minutes: 60 * 24 * 7 * 4 },
        { label: "All time", minutes: 0 }
    ]
    property int selectedRangeIndex: 1   // default: Last 24 hours

    // On-disk cache size in bytes, probed once per open (walking the profile
    // is cheap but not free) and again after a clear completes.  Only the
    // cache is measurable, so the "Freed space" line is driven by the cache
    // checkbox.  Kept as an int — cache sizes are whole bytes, never fractional.
    property int cacheBytes: 0

    // True while the native clear is running — used to disable the Clear
    // button and show a busy indicator so the user can't double-click.
    property bool clearing: false

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
        if (visible) {
            clearing = false
            refreshCacheSize()
        }
    }

    // Collect the ticked option ids and the chosen time window, then clear.
    // Returns the list of picked ids (used by tests and for the post-clear
    // summary line).
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
            return picked
        }
        var minutes = timeRanges[selectedRangeIndex].minutes
        clearing = true
        if (root.browser)
            root.browser.clearBrowsingData(picked, minutes)
        // The clearBrowsingData call is synchronous from the GUI thread's
        // point of view (it waits on the .NET Task, pumping Qt events).
        // When we get here, WebView2 has finished and our folder-wipe
        // helper has already removed the regenerable cache directories.
        refreshCacheSize()
        clearing = false
        root.cleared()
        root.hidePopup()
        return picked
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

                // Force the popup (and everything inside it) to a known dark
                // palette.  Qt Quick Controls' Basic style inherits the
                // system palette on the native popup window; without this,
                // even though we set a dark background rectangle, child
                // controls (ItemDelegate, ScrollIndicator) may still render
                // with a light-system colour for text, which is what made
                // the options unreadable. Pinning palette.text / .base /
                // .highlight here overrides the OS fallback entirely.
                palette.text: Theme.text
                palette.windowText: Theme.text
                palette.base: Theme.baseElevated
                palette.window: Theme.baseElevated
                palette.highlight: Theme.accentDim
                palette.highlightedText: Theme.accent
                palette.button: Theme.baseElevated
                palette.buttonText: Theme.text

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: Theme.glassFill
                    border.width: 1
                    border.color: Theme.glassBorder
                }

                contentItem: Text {
                    leftPadding: Theme.spaceMd
                    rightPadding: Theme.spaceMd
                    text: rangeCombo.displayText
                    font: rangeCombo.font
                    color: Theme.text
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                // The popup panel that holds the options.
                //
                // IMPORTANT — when you override ``popup.contentItem`` (a
                // ListView), you MUST also set its ``delegate`` property.
                // The previous fix only set ``ComboBox.delegate`` above and
                // assumed the ListView would pick it up, but with a custom
                // contentItem that delegate is not auto-wired, so Qt fell
                // back to the built-in default delegate which paints text
                // using the *system* palette. That was the cause of the
                // "black text on black / light text on light" the user kept
                // seeing. We declare the delegate inline here so the ListView
                // uses it directly — and we also pin a dark palette on the
                // popup (above) as a second guard against OS fallback.
                popup: Popup {
                    id: rangePopup
                    y: rangeCombo.height
                    width: rangeCombo.width
                    implicitHeight: contentItem.implicitHeight
                    padding: Theme.spaceXs
                    topInset: 0
                    bottomInset: 0
                    leftInset: 0
                    rightInset: 0

                    palette.text: Theme.text
                    palette.windowText: Theme.text
                    palette.base: Theme.baseElevated
                    palette.window: Theme.baseElevated
                    palette.highlight: Theme.accentDim
                    palette.highlightedText: Theme.accent
                    palette.button: Theme.baseElevated
                    palette.buttonText: Theme.text

                    contentItem: ListView {
                        id: popupList
                        clip: true
                        implicitHeight: contentHeight
                        model: rangePopup.visible ? rangeCombo.delegateModel : null
                        currentIndex: rangeCombo.highlightedIndex
                        // CRITICAL: assign delegate explicitly so the ListView
                        // does NOT fall back to Qt's default system-themed
                        // delegate, which paints text in the OS palette color.
                        delegate: ItemDelegate {
                            id: popupDelegateItem
                            width: popupList.width
                            text: model.label
                            font: rangeCombo.font
                            highlighted: rangeCombo.highlightedIndex === index
                            palette.text: Theme.text
                            palette.windowText: Theme.text
                            palette.highlight: Theme.accentDim
                            palette.highlightedText: Theme.accent

                            contentItem: Text {
                                leftPadding: Theme.spaceMd
                                rightPadding: Theme.spaceMd
                                text: popupDelegateItem.text
                                font: popupDelegateItem.font
                                color: popupDelegateItem.highlighted ? Theme.accent : Theme.text
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                            }

                            background: Rectangle {
                                color: popupDelegateItem.highlighted ? Theme.glassFillHover : "transparent"
                                radius: Theme.radiusSmall
                            }
                        }
                        ScrollIndicator.vertical: ScrollIndicator {
                            palette.alternateBase: Theme.baseElevated
                        }
                    }

                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: Theme.baseElevated
                        border.width: 1
                        border.color: Theme.glassBorderStrong
                    }
                }

                // The top-level ``delegate`` property is unused now that the
                // popup declares its delegate inline (see note above). Leave
                // a minimal stub so nothing else in the scene graph tries to
                // read it and falls over.
                delegate: ItemDelegate {
                    width: rangeCombo.width
                    text: model.label
                    font: rangeCombo.font
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
