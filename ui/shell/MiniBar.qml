import QtQuick
import QtQuick.Controls.Basic as Controls
import Halcyon.Ui

// Mini Mode bar — §M.3 / §M.4 — v1.1
//
// Fixed 460 × 44 (height = Theme.titleBarHeight). Only grip drags.
// Top 3px hairline IS the seek bar (2px rest → 6px + knob on hover).
// Play button has circular progress ring (0-100%) — zero width increase.
// Innovative horizontal volume capsule to right of mute button — zero clipping.
// Zero tooltips in Mini Mode for unobtrusive, clean controls.
// All controls bind to same Actions entries as Local transport §4.1.

Item {
    id: root
    width: 460
    height: Theme.titleBarHeight // 44px — same as TitleBar §M.3
    readonly property real fixedWidth: width
    readonly property real fixedHeight: height

    // Live bindings from Player — safe when Player null at startup
    property var player: typeof Player !== "undefined" ? Player : null
    readonly property real position: player ? player.position : 0.0 // 0..1
    readonly property real buffered: player ? player.buffered : 0.0
    readonly property int duration: player ? player.duration : 0
    readonly property bool isPlaying: player ? player.isPlaying : false
    readonly property int volume: player ? player.volume : 0
    readonly property bool muted: player ? player.muted : false

    // Seek scrub state — mirrors SeekBar.qml
    property real scrubPosition: 0.0
    property bool scrubbing: seekDrag.pressed
    readonly property real displayPosition:
        Math.max(0, Math.min(1, scrubbing ? scrubPosition : position))

    signal seekRequested(real fraction)

    function volumeGlyph(v, mut) {
        if (mut || v === 0) return Glyphs.volumeMute;
        return v < 34 ? Glyphs.volumeLow : v < 67 ? Glyphs.volumeMid : Glyphs.volumeHigh;
    }

    // ------------------------------------------------------------- background
    GlassPanel {
        id: bg
        anchors.fill: parent
        radius: Theme.radiusControl
        fillColor: Theme.glassFill
        borderColor: Theme.glassBorder
        blurRadius: Theme.blurPanel
        showBorder: true
    }

    // ------------------------------------------------------- top hairline seek §M.4
    // The top 3px of the bar itself is the seek bar. 2px at rest, 6px on hover.
    // No extra width, no extra height outside 44px. No tooltip popup.
    Item {
        id: seekArea
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 10 // hover hit area, includes 3px visual + padding
        z: 2

        readonly property bool seekActive: seekHover.containsMouse || seekDrag.pressed
        readonly property real barHeight: seekActive ? 6 : 2

        // Visual track — sticks to top edge
        Item {
            id: seekTrack
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: seekArea.barHeight

            Behavior on height {
                NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }

            // rest
            Rectangle {
                anchors.fill: parent
                anchors.bottomMargin: 0
                color: Theme.trackRest
                radius: height / 2
            }
            // buffered
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, root.buffered))
                height: parent.height
                radius: height / 2
                color: Theme.trackBuffered
            }
            // played — accent gradient
            Rectangle {
                width: parent.width * root.displayPosition
                height: parent.height
                radius: height / 2
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accentAlt }
                }
            }
        }

        // knob — only when active/usable
        Rectangle {
            id: seekKnob
            width: 10
            height: 10
            radius: 5
            color: Theme.text
            visible: seekArea.seekActive && root.duration > 0
            x: seekTrack.width * root.displayPosition - width / 2
            y: seekTrack.height / 2 - height / 2
        }

        MouseArea {
            id: seekHover
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
        }

        MouseArea {
            id: seekDrag
            anchors.fill: parent
            preventStealing: true
            enabled: root.duration > 0
            cursorShape: Qt.PointingHandCursor

            function fractionAt(mx) {
                return Math.max(0, Math.min(1, mx / Math.max(1, root.width)));
            }

            onPressed: function(mouse) {
                root.scrubPosition = fractionAt(mouse.x);
                Actions.beginScrub();
                root.seekRequested(root.scrubPosition);
            }
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                root.scrubPosition = fractionAt(mouse.x);
                root.seekRequested(root.scrubPosition);
            }
            onReleased: function(mouse) {
                root.scrubPosition = fractionAt(mouse.x);
                root.seekRequested(root.scrubPosition);
                Actions.endScrub();
            }
        }
    }

    // ---------------------------------------------------------- main row
    Row {
        id: controlsRow
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceXs
        anchors.right: parent.right
        anchors.rightMargin: Theme.spaceXs
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 2 // account for 3px seek bar on top — visually center in remaining 41px
        spacing: 2

        // Grip — only draggable via this — 24px
        Item {
            id: grip
            width: 24
            height: Theme.titleBarHeight - 4
            anchors.verticalCenter: parent.verticalCenter

            // 6 dots — 2 columns × 3 rows
            Grid {
                anchors.centerIn: parent
                columns: 2
                rows: 3
                columnSpacing: 3
                rowSpacing: 3
                Repeater {
                    model: 6
                    Rectangle {
                        width: 3
                        height: 3
                        radius: 1.5
                        color: Theme.textFaint
                        opacity: 0.9
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.OpenHandCursor
                acceptedButtons: Qt.LeftButton
                onPressed: {
                    if (root.Window.window) {
                        root.Window.window.startSystemMove();
                    }
                }
            }
        }

        // Prev track
        IconButton {
            glyph: Glyphs.previous
            iconSize: 18
            onClicked: Actions.previous()
        }

        // Seek -10s
        IconButton {
            glyph: Glyphs.rewind
            iconSize: 18
            onClicked: Actions.seekRelative(-10000)
        }

        // Play/Pause with circular progress ring
        Item {
            id: playWrapper
            width: 44
            height: 44
            anchors.verticalCenter: parent.verticalCenter

            // Circular progress ring — background + progress
            Canvas {
                id: ring
                anchors.centerIn: parent
                width: 36
                height: 36
                property real progress: root.displayPosition
                property color ringColor: Theme.accent
                onProgressChanged: requestPaint()
                onRingColorChanged: requestPaint()

                onPaint: {
                    var ctx = getContext("2d");
                    ctx.clearRect(0, 0, width, height);
                    var cx = width / 2;
                    var cy = height / 2;
                    var r = width / 2 - 2;
                    // background full circle
                    ctx.beginPath();
                    ctx.arc(cx, cy, r, 0, Math.PI * 2, false);
                    ctx.lineWidth = 2;
                    ctx.strokeStyle = "#33FFFFFF"; // faint
                    ctx.stroke();

                    // progress arc — from top (-90deg)
                    if (progress > 0.001) {
                        ctx.beginPath();
                        ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress, false);
                        ctx.lineWidth = 2.2;
                        ctx.strokeStyle = ring.ringColor;
                        ctx.stroke();
                    }
                }
            }

            IconButton {
                anchors.centerIn: parent
                glyph: root.isPlaying ? Glyphs.pause : Glyphs.play
                iconSize: 20
                width: 40
                height: 40
                onClicked: Actions.playPause()
            }
        }

        // Stop
        IconButton {
            glyph: Glyphs.stop
            iconSize: 18
            onClicked: Actions.stop()
        }

        // Next track
        IconButton {
            glyph: Glyphs.next
            iconSize: 18
            onClicked: Actions.next()
        }

        // Seek +10s
        IconButton {
            glyph: Glyphs.fastForward
            iconSize: 18
            onClicked: Actions.seekRelative(10000)
        }

        // Mute button with wheel support
        Item {
            width: 40
            height: Theme.titleBarHeight - 4
            anchors.verticalCenter: parent.verticalCenter

            IconButton {
                id: muteBtn
                anchors.centerIn: parent
                glyph: root.volumeGlyph(root.volume, root.muted)
                iconSize: 18
                onClicked: Actions.toggleMute()
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                onWheel: function(wheel) {
                    var delta = wheel.angleDelta.y > 0 ? 5 : -5;
                    Actions.adjustVolume(delta);
                    if (root.muted && delta > 0) Actions.toggleMute();
                }
            }
        }

        // Innovative horizontal volume capsule — inline right of mute button
        Item {
            id: volCapsule
            width: 74
            height: 24
            anchors.verticalCenter: parent.verticalCenter

            Rectangle {
                id: volBg
                anchors.fill: parent
                radius: height / 2
                // Transparent capsule — the bar's own GlassPanel shows through,
                // matching Mini Mode's translucent look instead of an opaque
                // dark pill. Hover/press lift with the same glass tokens every
                // other control uses (IconButton §B.1); the accent gradient
                // fill and glass border keep the capsule shape readable.
                color: volArea.containsMouse || volArea.pressed ? Theme.glassFillHover
                                                                : "transparent"
                border.width: 1
                border.color: volArea.containsMouse || volArea.pressed ? Theme.accentDim
                                                                       : Theme.glassBorder

                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }
                Behavior on border.color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }

                // Filled level indicator (from left)
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: Math.max(0, Math.min(parent.width, parent.width * (root.volume / 100.0)))
                    radius: height / 2
                    opacity: root.muted ? 0.35 : 0.9

                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.accentDim }
                        GradientStop { position: 1.0; color: Theme.accent }
                    }

                    Behavior on width {
                        enabled: !volArea.pressed
                        NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }
                }

                // Volume text label inside capsule
                Text {
                    anchors.centerIn: parent
                    text: root.muted ? "MUTED" : "VOL " + root.volume
                    font.family: Theme.fontFamilyMono
                    font.pixelSize: Theme.fontSizeTiny
                    font.weight: Font.Medium
                    color: Theme.text
                    opacity: root.muted ? 0.6 : 0.95
                }
            }

            MouseArea {
                id: volArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor

                function volumeAt(mx) {
                    var ratio = Math.max(0.0, Math.min(1.0, mx / Math.max(1, width)));
                    return Math.round(ratio * 100);
                }

                onPressed: function(mouse) {
                    var newVol = volumeAt(mouse.x);
                    Actions.setVolume(newVol);
                    if (root.muted && newVol > 0) Actions.toggleMute();
                }
                onPositionChanged: function(mouse) {
                    if (!pressed) return;
                    var newVol = volumeAt(mouse.x);
                    Actions.setVolume(newVol);
                    if (root.muted && newVol > 0) Actions.toggleMute();
                }
                onWheel: function(wheel) {
                    var delta = wheel.angleDelta.y > 0 ? 5 : -5;
                    Actions.adjustVolume(delta);
                    if (root.muted && delta > 0) Actions.toggleMute();
                }
            }
        }

        // Return to normal — expand
        IconButton {
            glyph: Glyphs.miniReturn
            iconSize: 18
            onClicked: Actions.toggleMiniMode()
        }
    }
}
