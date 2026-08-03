import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

Item {
    id: root

    property var ctx: null
    property int selectedSourceIndex: -1

    function openEditor(sourceIndex) {
        selectedSourceIndex = sourceIndex;
        if (sourceIndex >= 0 && ctx) {
            var item = ctx.bookmark(sourceIndex);
            editTitle.text = item.title || "";
            editUrl.text = item.url || "";
        } else {
            editTitle.text = "";
            editUrl.text = "";
        }
        editPopup.open();
        editTitle.forceActiveFocus();
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.base
    }

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceMd

        Row {
            width: parent.width
            height: Theme.hitTarget
            spacing: Theme.spaceSm

            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - Theme.hitTarget * 4 - Theme.spaceSm * 4
                text: "Bookmarks"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTitle
                font.weight: Theme.weightBold
                color: Theme.text
            }
            IconButton {
                glyph: Glyphs.add
                tooltip: "Add bookmark"
                onClicked: root.openEditor(-1)
            }
            IconButton {
                glyph: Glyphs.edit
                tooltip: "Edit bookmark"
                enabled: root.selectedSourceIndex >= 0
                onClicked: root.openEditor(root.selectedSourceIndex)
            }
            IconButton {
                glyph: Glyphs.deleteItem
                tooltip: "Delete bookmark"
                enabled: root.selectedSourceIndex >= 0
                onClicked: deleteConfirm.open()
            }
        }

        GlassField {
            id: searchField
            width: parent.width
            placeholderText: "Search bookmarks…"
            clearable: true
            clearTooltip: "Clear search"
            onTextChanged: if (root.ctx) root.ctx.bookmarks.setFilter(text)
        }

        ListView {
            id: list
            width: parent.width
            height: parent.height - Theme.hitTarget - searchField.height - Theme.spaceMd * 2
            clip: true
            spacing: Theme.spaceXs
            model: root.ctx ? root.ctx.bookmarks : null
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 6
            }

            delegate: ListRow {
                id: row
                required property int sourceIndex
                required property string title
                required property string url
                required property string favicon

                width: ListView.view.width
                height: 54
                selected: root.selectedSourceIndex === row.sourceIndex
                onClicked: root.selectedSourceIndex = row.sourceIndex
                onDoubleClicked: if (root.ctx) root.ctx.openBookmark(row.sourceIndex)

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: Theme.spaceMd

                    Image {
                        width: 22
                        height: 22
                        anchors.verticalCenter: parent.verticalCenter
                        source: row.favicon
                        asynchronous: true
                        fillMode: Image.PreserveAspectFit
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 22 - Theme.hitTarget * 2 - Theme.spaceMd * 3
                        spacing: 2
                        Text {
                            width: parent.width
                            text: row.title
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.weight: Theme.weightMedium
                            color: Theme.text
                        }
                        Text {
                            width: parent.width
                            text: row.url
                            elide: Text.ElideMiddle
                            font.family: Theme.fontFamilyMono
                            font.pixelSize: Theme.fontSizeTiny
                            color: Theme.textFaint
                        }
                    }
                    IconButton {
                        glyph: Glyphs.chevronUp
                        tooltip: "Move up"
                        enabled: row.sourceIndex > 0
                        onClicked: if (root.ctx) root.ctx.moveBookmark(row.sourceIndex, row.sourceIndex - 1)
                    }
                    IconButton {
                        glyph: Glyphs.chevronDown
                        tooltip: "Move down"
                        enabled: root.ctx && row.sourceIndex < root.ctx.bookmarks.totalCount - 1
                        onClicked: if (root.ctx) root.ctx.moveBookmark(row.sourceIndex, row.sourceIndex + 1)
                    }
                }
            }
        }
    }

    Popover {
        id: editPopup
        width: 420
        height: 190
        x: Math.max(Theme.spaceXl, (root.width - width) / 2)
        y: Math.max(Theme.spaceXl, (root.height - height) / 2)

        Column {
            anchors.fill: parent
            spacing: Theme.spaceMd

            GlassField {
                id: editTitle
                width: parent.width
                placeholderText: "Title"
            }
            GlassField {
                id: editUrl
                width: parent.width
                placeholderText: "URL"
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.spaceSm
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: editPopup.close()
                }
                IconButton {
                    glyph: Glyphs.save
                    tooltip: "Save"
                    onClicked: {
                        if (!root.ctx)
                            return;
                        var ok = root.selectedSourceIndex >= 0
                                 ? root.ctx.updateBookmark(root.selectedSourceIndex, editTitle.text, editUrl.text)
                                 : root.ctx.saveBookmark(editTitle.text, editUrl.text);
                        if (ok)
                            editPopup.close();
                    }
                }
            }
        }
    }

    ConfirmDialog {
        id: deleteConfirm
        title: "Delete bookmark"
        message: "Remove this bookmark?"
        onConfirmed: {
            if (root.ctx && root.selectedSourceIndex >= 0) {
                root.ctx.deleteBookmark(root.selectedSourceIndex);
                root.selectedSourceIndex = -1;
            }
        }
    }
}
