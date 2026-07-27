import QtQuick
import QtQuick.Layouts
import Halcyon.Ui

// Shared transport part — §B.4. The gear popover.
//
// The ONE home for speed, audio track, subtitle track and subtitle delay
// (§P1.4). These do not also appear in a menu bar, a right-click menu, or the
// settings dialog. Hotkeys (S, A, [, ]) invoke the same Actions entries this
// popover binds to — same implementation, different trigger.
Popover {
    id: root

    property real rate: 1.0
    property var audioTracks: []          // [{ id, label }]
    property var subtitleTracks: []
    property int currentAudioId: -1
    property int currentSubtitleId: -1
    property int subtitleDelayMs: 0

    implicitWidth: 268

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spaceMd

        // ------------------------------------------------------- speed --
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceXs

            Text {
                text: "Speed"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                font.weight: Theme.weightBold
                color: Theme.textFaint
            }

            Flow {
                Layout.fillWidth: true
                spacing: Theme.spaceXs

                Repeater {
                    model: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
                    delegate: Rectangle {
                        required property real modelData
                        readonly property bool isCurrent: Math.abs(modelData - root.rate) < 0.01

                        width: 48
                        height: 26
                        radius: Theme.radiusSmall
                        color: isCurrent ? Theme.accentDim
                             : speedMouse.containsMouse ? Theme.glassFillHover
                             : Theme.glassFill
                        border.width: 1
                        border.color: isCurrent ? Theme.accent : Theme.glassBorder

                        Behavior on color {
                            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                        }

                        Text {
                            anchors.centerIn: parent
                            text: modelData + "\u00D7"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: parent.isCurrent ? Theme.accent : Theme.textMuted
                        }

                        MouseArea {
                            id: speedMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Actions.setRate(modelData)
                        }
                    }
                }
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.glassBorder }

        // -------------------------------------------------- audio track --
        TrackSection {
            Layout.fillWidth: true
            title: "Audio"
            tracks: root.audioTracks
            currentId: root.currentAudioId
            emptyText: "No audio tracks"
            onTrackChosen: function(id) { Actions.setAudioTrack(id) }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.glassBorder }

        // ----------------------------------------------------- subtitles --
        TrackSection {
            Layout.fillWidth: true
            title: "Subtitles"
            tracks: root.subtitleTracks
            currentId: root.currentSubtitleId
            emptyText: "No subtitles"
            allowOff: true
            onTrackChosen: function(id) { Actions.setSubtitleTrack(id) }
        }

        // --------------------------------------------- subtitle delay --
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            Text {
                text: "Delay"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textMuted
                Layout.fillWidth: true
            }
            IconButton {
                glyph: "\uE738"
                iconSize: 14
                implicitWidth: 28
                implicitHeight: 28
                tooltip: "-50 ms"
                onClicked: Actions.adjustSubtitleDelay(-50)
            }
            Text {
                text: (root.subtitleDelayMs > 0 ? "+" : "") + root.subtitleDelayMs + " ms"
                font.family: Theme.fontFamilyMono
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.text
                horizontalAlignment: Text.AlignHCenter
                Layout.preferredWidth: 58
            }
            IconButton {
                glyph: "\uE710"
                iconSize: 14
                implicitWidth: 28
                implicitHeight: 28
                tooltip: "+50 ms"
                onClicked: Actions.adjustSubtitleDelay(50)
            }
        }

        TextButton {
            Layout.fillWidth: true
            text: "Load subtitle file\u2026"
            glyph: Glyphs.subtitles
            onClicked: Actions.loadSubtitleFile()
        }
    }
}
