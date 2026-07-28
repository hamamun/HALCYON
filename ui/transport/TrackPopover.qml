import QtQuick
import QtQuick.Layouts
import Halcyon.Ui

// Shared transport part — §B.4. The gear popover.
//
// The ONE home for speed, audio track, subtitle track and subtitle delay
// (§P1.4). These do not also appear in a menu bar, a right-click menu, or the
// settings dialog. Hotkeys (S, A, [, ]) invoke the same Actions entries this
// popover binds to — same implementation, different trigger.
//
// Order is fixed and deliberate, most-used first: Speed, Audio, Subtitles,
// then subtitle sourcing (delay / load / download). Each track section scrolls
// internally past five rows (see TrackSection), so this popover has a bounded
// height no matter how many tracks a file carries.
Popover {
    id: root

    property real rate: 1.0
    property var audioTracks: []          // [{ id, label, off }]
    property var subtitleTracks: []
    property int currentAudioId: -1
    property int currentSubtitleId: -1
    property int subtitleDelayMs: 0

    implicitWidth: 288

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
                glyph: Glyphs.minus
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
                glyph: Glyphs.plus
                iconSize: 14
                implicitWidth: 28
                implicitHeight: 28
                tooltip: "+50 ms"
                onClicked: Actions.adjustSubtitleDelay(50)
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.glassBorder }

        // ------------------------------------------- where subs come from --
        // Two sources, one row, same visual weight: a file you already have,
        // and one you do not. The old popover offered only the first, and the
        // download half had nowhere to live.
        //
        // Neither button opens anything *here*. Searching needs a language, a
        // match mode, a query and a result list with release names — that is a
        // dialog, not a 288px flyout, and cramming it in would have made the
        // popover taller than the video. Both are triggers for actions
        // implemented once in Main.qml (§4.1).
        Text {
            text: "Get subtitles"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            font.weight: Theme.weightBold
            color: Theme.textFaint
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            TextButton {
                Layout.fillWidth: true
                text: "From file\u2026"
                glyph: Glyphs.addFile
                onClicked: {
                    root.close();
                    Actions.loadSubtitleFile();
                }
            }
            TextButton {
                Layout.fillWidth: true
                text: "Search online\u2026"
                glyph: Glyphs.download
                // Disabled with nothing playing: an online search is a search
                // *for the current file* (by hash, then by name). Greying it
                // out says that; an empty result list would not.
                enabled: typeof Player !== "undefined" && Player && Player.currentMedia !== ""
                onClicked: {
                    root.close();
                    Actions.searchSubtitlesOnline();
                }
            }
        }

        // The one line of state worth surfacing here rather than in the dialog:
        // whether searching will work at all. Without it the button opens a
        // dialog that can only tell you to go to Settings.
        Text {
            visible: typeof Subtitles !== "undefined" && Subtitles && !Subtitles.configured
            Layout.fillWidth: true
            text: "Add an OpenSubtitles API key in Settings to search online."
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }
}
