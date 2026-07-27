import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// 4px at rest, 6px with a knob on hover. Buffered region behind played region,
// played region in the accent gradient. Click anywhere to seek; drag scrubs live
// and commits on release.
//
// Local puts this on its own full-width row (§P1.5). M3U does not use it at all,
// because seeking a live stream is meaningless (§P2.4) — that is §B.2 working as
// intended: a shared part, used where it makes sense, absent where it doesn't.
Item {
    id: root

    property real position: 0.0        // 0..1, played
    property real buffered: 0.0        // 0..1
    property int duration: 0           // ms, for the hover tooltip
    property bool scrubbing: dragArea.pressed

    signal seekRequested(real fraction)
    signal scrubStarted()
    signal scrubEnded()

    implicitHeight: Theme.hitTarget * 0.6
    height: implicitHeight

    readonly property bool active: hoverArea.containsMouse || dragArea.pressed
    readonly property real barHeight: active ? Theme.seekBarHover : Theme.seekBarRest

    onScrubbingChanged: scrubbing ? scrubStarted() : scrubEnded()

    // ------------------------------------------------------------- track --
    Item {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: root.barHeight

        Behavior on height {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }

        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: Theme.trackRest
        }

        Rectangle {
            width: parent.width * Math.max(0, Math.min(1, root.buffered))
            height: parent.height
            radius: height / 2
            color: Theme.trackBuffered
        }

        Rectangle {
            id: played
            width: parent.width * Math.max(0, Math.min(1, root.position))
            height: parent.height
            radius: height / 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.accent }
                GradientStop { position: 1.0; color: Theme.accentAlt }
            }
        }
    }

    // -------------------------------------------------------------- knob --
    Rectangle {
        id: knob
        width: 12
        height: 12
        radius: 6
        color: Theme.text
        anchors.verticalCenter: parent.verticalCenter
        x: track.width * Math.max(0, Math.min(1, root.position)) - width / 2
        opacity: root.active ? 1 : 0
        scale: dragArea.pressed ? 1.2 : 1.0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
        Behavior on scale {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    // ------------------------------------------------------------ tooltip --
    // Hover timestamp. Frame thumbnails are deferred to v1.1 (§8) — they need a
    // second decoder instance.
    Rectangle {
        id: tip
        visible: hoverArea.containsMouse && root.duration > 0
        height: 22
        width: tipText.implicitWidth + Theme.spaceMd
        radius: Theme.radiusSmall
        color: Qt.rgba(0.043, 0.055, 0.078, 0.94)
        border.width: 1
        border.color: Theme.glassBorder
        y: -height - Theme.spaceSm
        x: Math.max(0, Math.min(root.width - width, hoverArea.mouseX - width / 2))

        Text {
            id: tipText
            anchors.centerIn: parent
            text: root.formatTime(hoverArea.mouseX / Math.max(1, root.width) * root.duration)
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.text
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

    // ------------------------------------------------------- interaction --
    MouseArea {
        id: hoverArea
        anchors.fill: parent
        anchors.topMargin: -6
        anchors.bottomMargin: -6
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    MouseArea {
        id: dragArea
        anchors.fill: parent
        anchors.topMargin: -6
        anchors.bottomMargin: -6
        preventStealing: true

        function fractionAt(mx) {
            return Math.max(0, Math.min(1, mx / Math.max(1, root.width)));
        }

        onPressed: function(mouse) { root.seekRequested(fractionAt(mouse.x)) }
        onPositionChanged: function(mouse) {
            if (pressed)
                root.seekRequested(fractionAt(mouse.x));
        }
    }
}
