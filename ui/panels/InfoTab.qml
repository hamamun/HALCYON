import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Info tab — filename, resolution, codecs, bitrate, duration, container
// (Milestone 1.8). Metadata comes from libVLC, so there is no ffprobe
// dependency to ship.
Flickable {
    id: root

    property var meta: typeof Metadata !== "undefined" ? Metadata : null

    contentHeight: column.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }

    Column {
        id: column
        width: parent.width
        spacing: Theme.spaceMd

        // Album art, when the file has any.
        Rectangle {
            width: parent.width
            height: width
            radius: Theme.radiusControl
            color: Theme.glassFill
            border.width: 1
            border.color: Theme.glassBorder
            visible: root.meta && root.meta.artworkUrl !== ""
            clip: true

            Image {
                anchors.fill: parent
                source: root.meta ? root.meta.artworkUrl : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
            }
        }

        Text {
            width: parent.width
            text: root.meta && root.meta.title !== "" ? root.meta.title : "Nothing playing"
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.weightBold
            color: Theme.text
        }

        Text {
            width: parent.width
            visible: root.meta && root.meta.artist !== ""
            text: root.meta ? root.meta.artist : ""
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            color: Theme.textMuted
        }

        Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

        Repeater {
            model: root.meta ? root.meta.details : []

            delegate: Row {
                required property var modelData
                width: column.width
                spacing: Theme.spaceSm

                Text {
                    width: 100
                    text: modelData.label
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.textFaint
                }
                Text {
                    width: parent.width - 100 - Theme.spaceSm
                    text: modelData.value
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }
            }
        }

        // --------------------------------------------- live stats --
        // Counters polled once a second while playing (§P1.5). Hidden until
        // the first reading lands, so an idle file shows nothing stale.
        Column {
            width: parent.width
            spacing: Theme.spaceXs
            visible: root.meta && root.meta.liveStats
                     && root.meta.liveStats.inputBitrate !== ""

            Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

            Text {
                text: "LIVE"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                font.weight: Theme.weightBold
                color: Theme.textFaint
            }

            Row {
                width: parent.width
                spacing: Theme.spaceSm

                Text {
                    width: 100
                    text: "Input bitrate"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.textFaint
                }
                Text {
                    width: parent.width - 100 - Theme.spaceSm
                    text: root.meta ? root.meta.liveStats.inputBitrate : ""
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }
            }

            Row {
                width: parent.width
                spacing: Theme.spaceSm

                Text {
                    width: 100
                    text: "Decoded frames"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.textFaint
                }
                Text {
                    width: parent.width - 100 - Theme.spaceSm
                    text: root.meta ? root.meta.liveStats.decodedFrames : ""
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }
            }

            Row {
                width: parent.width
                spacing: Theme.spaceSm

                Text {
                    width: 100
                    text: "Dropped frames"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.textFaint
                }
                Text {
                    width: parent.width - 100 - Theme.spaceSm
                    text: root.meta ? root.meta.liveStats.droppedFrames : ""
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }
            }
        }
    }
}
