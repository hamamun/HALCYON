import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

Popover {
    id: root

    property var ctx: null
    signal bookmarkPicked(int sourceIndex)
    signal manageRequested()

    width: 360
    height: Math.min(420, header.height + list.contentHeight + Theme.spaceMd * 2)
    padding: Theme.spaceMd

    Column {
        anchors.fill: parent
        spacing: Theme.spaceSm

        Row {
            id: header
            width: parent.width
            height: Theme.hitTarget
            spacing: Theme.spaceSm

            IconButton {
                glyph: Glyphs.bookmarkManager
                tooltip: "Manage bookmarks"
                onClicked: {
                    root.close();
                    root.manageRequested();
                }
            }
            IconButton {
                glyph: Glyphs.add
                tooltip: "Add manual bookmark"
                onClicked: {
                    root.close();
                    root.manageRequested();
                }
            }
            Item { width: parent.width - Theme.hitTarget * 2 - Theme.spaceSm * 2; height: 1 }
        }

        Rectangle {
            width: parent.width
            height: 1
            color: Theme.glassBorder
        }

        ListView {
            id: list
            width: parent.width
            height: Math.min(contentHeight, 320)
            clip: true
            model: root.ctx ? root.ctx.bookmarks : null
            spacing: Theme.spaceXs
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
                onClicked: {
                    root.close();
                    root.bookmarkPicked(row.sourceIndex);
                }

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    spacing: Theme.spaceSm

                    Image {
                        width: 20
                        height: 20
                        anchors.verticalCenter: parent.verticalCenter
                        source: row.favicon
                        asynchronous: true
                        fillMode: Image.PreserveAspectFit
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 28
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
                }
            }
        }

        Text {
            visible: root.ctx && root.ctx.bookmarks.count === 0
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: "No bookmarks"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
        }
    }
}
