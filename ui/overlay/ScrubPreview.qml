import QtQuick
import Halcyon.Ui

// Floating still-frame preview above the seek bar — §S.
//
// A pure display: a 160×90 still of the video at the position under the
// pointer, framed in the aurora-glass style with the timestamp at the corner.
// It knows NOTHING about the player or the decoder — the arranger
// (LocalTransport) positions it, feeds it `imageSource` from Player.preview's
// snapshots, and decides when it is allowed to exist at all (§B.4).
Item {
    id: root

    //: Master switch — Settings toggle AND decoder availability combined by
    //: the arranger. When false the popup never appears.
    property bool enabled: false
    //: Pointer is over the seek bar (or dragging it).
    property bool hovered: false
    //: 0..1 position under the pointer; -1 while away.
    property real fraction: -1
    //: Media length in ms (for the time label).
    property int duration: 0
    //: The frame to show — file:// URL from the decoder, "" = none yet.
    property string imageSource: ""

    //: Whether the popup should be on screen at all.
    readonly property bool shown:
        enabled && hovered && fraction >= 0 && duration > 0

    // 160×90 = 16:9 thumbnail; odd aspect ratios letterbox inside the frame.
    width: 160
    height: 90

    // Fade in/out rather than pop, matching the rest of the chrome.
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
        NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: Qt.rgba(Theme.base.r, Theme.base.g, Theme.base.b, 0.95)
        border.width: 1
        border.color: Theme.glassBorder

        // The still. Fill the frame; PreserveAspectFit letterboxes 4:3 and
        // 21:9 content on the dark backing instead of cropping it.
        Image {
            anchors.fill: parent
            anchors.margins: 1
            source: root.imageSource
            fillMode: Image.PreserveAspectFit
            cache: false          // rotating temp files — never cache stale frames
            asynchronous: false   // PNGs are small; decode synchronously, show now
        }

        // Corner timestamp, mirroring the seek bar's hover tooltip format.
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: timeText.implicitWidth + Theme.spaceSm
            height: 16
            color: Qt.rgba(0, 0, 0, 0.55)
            radius: Theme.radiusSmall / 2

            Text {
                id: timeText
                anchors.centerIn: parent
                text: root.formatTime(Math.max(0, root.fraction) * root.duration)
                font.family: Theme.fontFamilyMono
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.text
            }
        }
    }

    function formatTime(ms) {
        if (!isFinite(ms) || ms < 0) ms = 0;
        var total = Math.floor(ms / 1000);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = (h > 0 && m < 10 ? "0" : "") + m;
        var ss = (s < 10 ? "0" : "") + s;
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }
}
