import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// Shared transport part — §B.4. The subtitle/track popover.
//
// The ONE home for speed, audio track, subtitle track, local subtitle files
// and subtitle delay (§P1.4). These do not also appear in a menu bar, a
// right-click menu, or the settings dialog. Hotkeys (S, A, [, ]) invoke the
// same Actions entries this popover binds to — same implementation, different
// trigger.
//
// Subtitles come in two lists, kept apart end to end: tracks multiplexed into
// the media ("Subtitles") and files loaded from disk — sidecar, hand-picked,
// or downloaded ("Local subtitles"). Both cap at five visible rows and scroll
// with the one ThinScrollBar.
//
// If the window is too small for the natural height (Main enforces a 520px
// minimum), the caller sets maxHeight and the whole panel flicks, capped, with
// the same scrollbar — never clipped against the title bar.
Popover {
    id: root

    property real rate: 1.0
    property var audioTracks: []          // [{ id, label }]
    property var subtitleTracks: []       // embedded in the media
    property var localSubtitleTracks: []  // loaded from disk
    property int currentAudioId: -1
    property int currentSubtitleId: -1
    property int subtitleDelayMs: 0
    property real maxHeight: 0            // 0 = natural height
    property bool hasVideo: true           // true if current media has video tracks

    // The transport bar opens the download flyout; the popover only reports.
    signal downloadRequested()

    implicitWidth: 336

    contentItem: Flickable {
        id: flick

        implicitWidth: root.implicitWidth - root.leftPadding - root.rightPadding
        implicitHeight: root.maxHeight > 0
                        ? Math.min(column.implicitHeight,
                                   root.maxHeight - root.topPadding - root.bottomPadding)
                        : column.implicitHeight

        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        interactive: contentHeight > height + 1
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: column
            width: flick.width - (flickScroll.visible ? 12 : 0)
            spacing: Theme.spaceMd

            // -------------------------------------------------- speed --
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

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.glassBorder }

            // ---------------------------------------------- audio track --
            TrackSection {
                Layout.fillWidth: true
                title: "Audio"
                tracks: root.audioTracks
                currentId: root.currentAudioId
                emptyText: "No audio tracks"
                onTrackChosen: function(id) { Actions.setAudioTrack(id) }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.glassBorder }

            // ------------------------------------------------- subtitles --
            TrackSection {
                Layout.fillWidth: true
                title: "Subtitles"
                tracks: root.subtitleTracks
                currentId: root.currentSubtitleId
                emptyText: "No subtitles"
                allowOff: true
                onTrackChosen: function(id) { Actions.setSubtitleTrack(id) }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.glassBorder }

            // ------------------------------------------ local subtitles --
            TrackSection {
                Layout.fillWidth: true
                title: "Local subtitles"
                tracks: root.localSubtitleTracks
                currentId: root.currentSubtitleId
                emptyText: "None loaded from disk"
                onTrackChosen: function(id) { Actions.setSubtitleTrack(id) }
            }

            // ----------------------------------------- subtitle delay --
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

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.glassBorder }

            // -------------------------------------- subtitle files --
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceXs

                Text {
                    text: "Subtitle files"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    font.weight: Theme.weightBold
                    color: root.hasVideo ? Theme.textFaint : Theme.textDisabled
                    Layout.fillWidth: true
                }
                IconButton {
                    glyph: Glyphs.openFile
                    iconSize: 16
                    implicitWidth: 32
                    implicitHeight: 32
                    tooltip: "Load subtitle file…"
                    enabled: root.hasVideo
                    opacity: root.hasVideo ? 1 : Theme.opacityDisabled
                    onClicked: Actions.loadSubtitleFile()
                }
                IconButton {
                    glyph: Glyphs.download
                    iconSize: 16
                    implicitWidth: 32
                    implicitHeight: 32
                    tooltip: "Download subtitles…"
                    enabled: root.hasVideo
                    opacity: root.hasVideo ? 1 : Theme.opacityDisabled
                    onClicked: root.downloadRequested()
                }
            }
        }

        ScrollBar.vertical: ThinScrollBar { id: flickScroll }
    }
}
