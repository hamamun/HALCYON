import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Halcyon's internal bookmark-management tab.  It is shown only when the active
// browser tab is halcyon://bookmarks, so no native WebView2 child sits over it.
Rectangle {
    id: root
    color: Theme.base

    property var browser: null
    readonly property var filteredItems: {
        var items = browser ? browser.bookmarkItems : []
        var query = searchInput.text.trim().toLowerCase()
        if (query.length === 0)
            return items
        return items.filter(function(item) {
            return String(item.title || "").toLowerCase().indexOf(query) >= 0
                || String(item.url || "").toLowerCase().indexOf(query) >= 0
        })
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "Bookmarks Manager"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTitle
                font.weight: Theme.weightBold
            }
            IconButton {
                glyph: Glyphs.add
                tooltip: "New Tab"
                onClicked: if (root.browser) root.browser.addTab("")
            }
        }

        // Search and manual add are intentionally separate fields.  A title is
        // never inferred from a URL here, so users can create tidy bookmarks.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            GlassField {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: "Search bookmarks"
                clearable: true
            }
            GlassField {
                id: manualTitle
                Layout.preferredWidth: 180
                placeholderText: "Title"
            }
            GlassField {
                id: manualUrl
                Layout.preferredWidth: 260
                placeholderText: "https://…"
                onAccepted: addBookmarkButton.clicked()
            }
            IconButton {
                id: addBookmarkButton
                glyph: Glyphs.add
                tooltip: "Add bookmark"
                enabled: manualUrl.text.trim().length > 0
                onClicked: {
                    if (!root.browser || manualUrl.text.trim().length === 0)
                        return
                    root.browser.addBookmark(manualTitle.text, manualUrl.text)
                    manualTitle.text = ""
                    manualUrl.text = ""
                }
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.filteredItems.length === 0
            text: searchInput.text.trim().length === 0
                  ? "No bookmarks yet — use ★ to save a page."
                  : "No matching bookmarks."
            horizontalAlignment: Text.AlignHCenter
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
        }

        ListView {
            id: managerList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.filteredItems
            spacing: Theme.spaceXs

            delegate: Rectangle {
                id: bookmarkRow
                required property var modelData
                required property int index
                width: managerList.width
                height: 58
                radius: Theme.radiusSmall
                color: rowMouse.containsMouse ? Theme.glassFillHover : Theme.glassFill
                border.width: 1
                border.color: Theme.glassBorder

                RowLayout {
                    anchors.fill: parent
                    z: 1
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceSm
                    spacing: Theme.spaceSm

                    // Drag handle.  Reordering is disabled while filtering so
                    // a displayed index can never be mistaken for the store's
                    // permanent order.
                    Item {
                        Layout.preferredWidth: 24
                        Layout.preferredHeight: Theme.hitTarget
                        opacity: dragHandler.active ? 1.0 : Theme.opacityRest

                        Text {
                            anchors.centerIn: parent
                            text: Glyphs.more
                            rotation: 90
                            color: Theme.textMuted
                            font.family: Theme.fontFamilyIcons
                            font.pixelSize: Theme.iconSize - 4
                        }

                        DragHandler {
                            id: dragHandler
                            target: null
                            property int fromIndex: -1
                            enabled: searchInput.text.trim().length === 0
                            onActiveChanged: {
                                if (active) {
                                    fromIndex = bookmarkRow.index
                                    return
                                }
                                if (fromIndex < 0 || !root.browser)
                                    return
                                var targetIndex = managerList.indexAt(
                                            0, bookmarkRow.y + translation.y + bookmarkRow.height / 2)
                                if (targetIndex >= 0 && targetIndex !== fromIndex)
                                    root.browser.reorderBookmarks(fromIndex, targetIndex)
                                fromIndex = -1
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text {
                            Layout.fillWidth: true
                            text: bookmarkRow.modelData.title || bookmarkRow.modelData.url
                            color: Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeBody
                            font.weight: Theme.weightMedium
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: bookmarkRow.modelData.url
                            color: Theme.textMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeTiny
                            elide: Text.ElideRight
                        }
                    }

                    IconButton {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32
                        glyph: Glyphs.chevronUp
                        iconSize: Theme.iconSize - 5
                        tooltip: "Move up"
                        enabled: bookmarkRow.index > 0 && searchInput.text.trim().length === 0
                        onClicked: if (root.browser) root.browser.reorderBookmarks(bookmarkRow.index, bookmarkRow.index - 1)
                    }
                    IconButton {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32
                        glyph: Glyphs.chevronDown
                        iconSize: Theme.iconSize - 5
                        tooltip: "Move down"
                        enabled: bookmarkRow.index < managerList.count - 1 && searchInput.text.trim().length === 0
                        onClicked: if (root.browser) root.browser.reorderBookmarks(bookmarkRow.index, bookmarkRow.index + 1)
                    }
                    IconButton {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32
                        glyph: Glyphs.edit
                        iconSize: Theme.iconSize - 5
                        tooltip: "Edit bookmark"
                        onClicked: {
                            editPopup.oldUrl = bookmarkRow.modelData.url
                            editTitle.text = bookmarkRow.modelData.title || ""
                            editUrl.text = bookmarkRow.modelData.url
                            editPopup.open()
                        }
                    }
                    IconButton {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32
                        glyph: Glyphs.deleteItem
                        iconSize: Theme.iconSize - 5
                        tooltip: "Delete bookmark"
                        onClicked: {
                            deletePopup.targetUrl = bookmarkRow.modelData.url
                            deletePopup.open()
                        }
                    }
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    anchors.rightMargin: Theme.hitTarget * 4 + Theme.spaceSm * 4
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onDoubleClicked: {
                        if (root.browser)
                            root.browser.navigateActive(bookmarkRow.modelData.url)
                    }
                }
            }
        }
    }

    Popup {
        id: editPopup
        property string oldUrl: ""
        width: 420
        height: 214
        anchors.centerIn: parent
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.radiusControl
            color: Theme.baseElevated
            border.width: 1
            border.color: Theme.glassBorderStrong
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
            GlassField { id: editTitle; Layout.fillWidth: true; placeholderText: "Title" }
            GlassField { id: editUrl; Layout.fillWidth: true; placeholderText: "https://…" }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spaceSm
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: editPopup.close()
                }
                IconButton {
                    glyph: Glyphs.save
                    tooltip: "Save"
                    enabled: editUrl.text.trim().length > 0
                    onClicked: {
                        if (root.browser)
                            root.browser.updateBookmark(editPopup.oldUrl, editTitle.text, editUrl.text)
                        editPopup.close()
                    }
                }
            }
        }
    }

    Popup {
        id: deletePopup
        property string targetUrl: ""
        width: 310
        height: 138
        anchors.centerIn: parent
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: Theme.radiusControl
            color: Theme.baseElevated
            border.width: 1
            border.color: Theme.glassBorderStrong
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spaceLg
            spacing: Theme.spaceMd
            Text {
                text: "Delete this bookmark?"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarge
                font.weight: Theme.weightBold
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: Theme.spaceSm
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: deletePopup.close()
                }
                IconButton {
                    glyph: Glyphs.deleteItem
                    tooltip: "Delete"
                    onClicked: {
                        if (root.browser)
                            root.browser.removeBookmark(deletePopup.targetUrl)
                        deletePopup.close()
                    }
                }
            }
        }
    }
}
