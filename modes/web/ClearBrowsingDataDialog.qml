import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// Clear Browsing Data dialog — the one place every browser-data wipe lives
// (§4.1). A native owned popup window (BrowserPopup) so it floats above the
// WebView2 child HWND where a scene-graph Dialog would sit *under* the page.
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

    signal cleared()

    function openFor(anchorItem, ownerWindow) {
        showBelow(anchorItem, ownerWindow)
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
                delegate: ItemDelegate {
                    width: rangeCombo.width
                    text: model.label
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                    highlighted: rangeCombo.highlightedIndex === index
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Theme.glassBorder
        }

        // checkbox list — fixed 8 rows, each with optional warning line
        Flickable {
            id: optionsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: optionsColumn.height
            boundsFlick: false
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
                }
                CheckBoxRow {
                    id: cb1
                    optionId: "downloadHistory"
                    label: "Download history"
                    defaultTick: false
                    destructive: false
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
                }
                CheckBoxRow {
                    id: cb7
                    optionId: "serviceWorkers"
                    label: "Service workers and offline data"
                    defaultTick: false
                    destructive: false
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
            TextButton {
                text: "Cancel"
                glyph: Glyphs.cancel
                onClicked: root.hidePopup()
            }
            TextButton {
                text: "Clear"
                glyph: Glyphs.clearBrowsingData
                primary: true
                onClicked: root.clearData()
            }
        }
    }
}
