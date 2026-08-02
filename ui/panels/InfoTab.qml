pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The Info tab — grouped file, stream and music metadata.
//
// Metadata is read by core/metadata.py through libVLC.  This tab is deliberately
// read-only: audio and subtitle selection remain in the existing transport
// popover, while Lyrics and Equalizer remain in their own right-dock tabs.
//
// The outer InfoPanel owns the dock, tabs and animation.  This file owns only
// the Info tab's content so changing the presentation cannot disturb the other
// right-panel features.
Flickable {
    id: root

    property var meta: typeof Metadata !== "undefined" ? Metadata : null

    // The guards keep this tab loadable in isolation and preserve compatibility
    // with small fake Metadata objects used by QML tests.
    readonly property var fileRows:
        root.meta && ("fileDetails" in root.meta) ? root.meta.fileDetails : []
    readonly property var generalRows:
        root.meta && ("generalDetails" in root.meta) ? root.meta.generalDetails : []
    readonly property var videoRows:
        root.meta && ("videoDetails" in root.meta) ? root.meta.videoDetails : []
    readonly property var audioRows:
        root.meta && ("audioDetails" in root.meta) ? root.meta.audioDetails : []
    readonly property var musicRows:
        root.meta && ("musicDetails" in root.meta) ? root.meta.musicDetails : []

    readonly property var sections: [
        { title: "File",        rows: root.fileRows },
        { title: "General",     rows: root.generalRows },
        { title: "Video",       rows: root.videoRows },
        { title: "Audio",       rows: root.audioRows },
        { title: "Music tags",  rows: root.musicRows }
    ]

    contentWidth: width
    contentHeight: column.implicitHeight + Theme.spaceMd
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    ScrollBar.vertical: ScrollBar {
        policy: ScrollBar.AsNeeded
        width: 6
    }

    Column {
        id: column
        width: root.width
        spacing: Theme.spaceLg

        // Keep the existing artwork behavior. It is not a metadata row and is
        // not duplicated in General or Music tags.
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
            visible: root.fileRows.length === 0
            text: "Nothing playing"
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.weightBold
            color: Theme.text
        }

        Repeater {
            model: root.sections

            delegate: Column {
                id: section
                required property var modelData

                width: root.width
                spacing: Theme.spaceSm
                visible: section.modelData.rows && section.modelData.rows.length > 0
                height: visible ? implicitHeight : 0

                Text {
                    width: parent.width
                    text: section.modelData.title
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                    font.weight: Theme.weightBold
                    color: Theme.accent
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Theme.glassBorder
                }

                Repeater {
                    model: section.modelData.rows

                    delegate: Row {
                        id: detailRow
                        required property var modelData

                        width: root.width
                        spacing: Theme.spaceSm

                        Text {
                            id: detailLabel
                            width: 96
                            text: detailRow.modelData.label
                            wrapMode: Text.WordWrap
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.textFaint
                        }

                        Text {
                            width: Math.max(0, parent.width - detailLabel.width - Theme.spaceSm)
                            text: detailRow.modelData.value
                            wrapMode: Text.WrapAnywhere
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.text
                        }
                    }
                }
            }
        }
    }
}
