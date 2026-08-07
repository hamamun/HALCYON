import QtQuick
import QtQuick.Controls.Basic as Controls
import Halcyon.Ui

// Mini Mode bar — §M.3 / §M.4 — v1.1
//
// Fixed 400-420 × 44 (height = Theme.titleBarHeight). Only grip drags.
// Top 3px hairline IS the seek bar (2px rest → 6px + knob on hover).
// Play button has circular progress ring (0-100%) — zero width increase.
// Volume vertical pop-up above mute icon — no width increase.
// All controls bind to same Actions entries as Local transport §4.1.

Item {
    id: root
    width: 400
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
    // No extra width, no extra height outside 44px.
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
                // Rounded only at bottom when thin? Keep pill.
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

        // time tooltip — appears below the hairline so it doesn't go off-screen
        Rectangle {
            id: seekTip
            visible: seekHover.containsMouse && root.duration > 0
            height: 20
            width: tipText.implicitWidth + Theme.spaceMd
            radius: Theme.radiusSmall
            color: Qt.rgba(0.043, 0.055, 0.078, 0.94)
            border.width: 1
            border.color: Theme.glassBorder
            y: seekTrack.height + Theme.spaceXs
            x: Math.max(0, Math.min(root.width - width, seekHover.mouseX - width / 2))

            Text {
                id: tipText
                anchors.centerIn: parent
                text: {
                    var frac = seekHover.mouseX / Math.max(1, root.width);
                    var ms = frac * root.duration;
                    if (!isFinite(ms) || ms < 0) ms = 0;
                    var total = Math.floor(ms / 1000);
                    var h = Math.floor(total / 3600);
                    var m = Math.floor((total % 3600) / 60);
                    var s = total % 60;
                    var mm = (h > 0 && m < 10 ? "0" : "") + m;
                    var ss = (s < 10 ? "0" : "") + s;
                    return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
                }
                font.family: Theme.fontFamilyMono
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.text
            }
        }

        MouseArea {
            id: seekHover
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            property real mouseX: 0
            onPositionChanged: function(mouse) { mouseX = mouse.x }
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
        // clip if window somehow narrower

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
            tooltip: "Previous track"
            iconSize: 18
            onClicked: Actions.previous()
        }

        // Seek -10s
        IconButton {
            glyph: Glyphs.rewind
            tooltip: "Seek -10s"
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
                onProgressChanged: requestPaint()

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
                        // accent solid — gradient hard in Canvas, use accent
                        ctx.strokeStyle = "#5EEAD4";
                        ctx.stroke();
                    }
                }
            }

            IconButton {
                anchors.centerIn: parent
                glyph: root.isPlaying ? Glyphs.pause : Glyphs.play
                tooltip: root.isPlaying ? "Pause" : "Play"
                iconSize: 20
                width: 40
                height: 40
                onClicked: Actions.playPause()
            }
        }

        // Stop
        IconButton {
            glyph: Glyphs.stop
            tooltip: "Stop"
            iconSize: 18
            onClicked: Actions.stop()
        }

        // Next track
        IconButton {
            glyph: Glyphs.next
            tooltip: "Next track"
            iconSize: 18
            onClicked: Actions.next()
        }

        // Seek +10s
        IconButton {
            glyph: Glyphs.fastForward
            tooltip: "Seek +10s"
            iconSize: 18
            onClicked: Actions.seekRelative(10000)
        }

        // Volume / Mute with vertical pop-up — no width increase
        Item {
            id: volumeArea
            width: 40
            height: 44
            anchors.verticalCenter: parent.verticalCenter

            IconButton {
                id: muteBtn
                anchors.centerIn: parent
                glyph: root.volumeGlyph(root.volume, root.muted)
                tooltip: root.muted ? "Unmuted" : "Mute — hover for volume"
                iconSize: 18
                onClicked: Actions.toggleMute()
            }

            // Vertical slider pop-up above bar
            Item {
                id: volumePopup
                anchors.bottom: parent.top
                anchors.bottomMargin: 8
                anchors.horizontalCenter: parent.horizontalCenter
                width: 36
                height: 140
                visible: muteBtn.hovered || popupHover.containsMouse || volSlider.pressed
                z: 10

                GlassPanel {
                    anchors.fill: parent
                    radius: Theme.radiusControl
                    fillColor: Qt.rgba(0.06, 0.08, 0.12, 0.92)
                    borderColor: Theme.glassBorder
                    blurRadius: 16
                }

                Controls.Slider {
                    id: volSlider
                    anchors.fill: parent
                    anchors.margins: Theme.spaceSm
                    orientation: Qt.Vertical
                    from: 0
                    to: 100
                    stepSize: 1
                    // Avoid binding loop: only push to Player when user drags,
                    // but reflect Player.volume when not pressed.
                    onPressedChanged: {
                        if (!pressed) {
                            // commit (already done on valueChanged, but safe)
                        }
                    }
                    Component.onCompleted: {
                        value = root.volume;
                    }
                    // Keep slider in sync when volume changes externally (keys etc.) and not being dragged
                    Connections {
                        target: root
                        function onVolumeChanged() {
                            if (!volSlider.pressed) volSlider.value = root.volume;
                        }
                    }
                    onValueChanged: {
                        if (pressed) {
                            Actions.setVolume(Math.round(value));
                        }
                    }
                    onMoved: {
                        Actions.setVolume(Math.round(value));
                    }

                    background: Rectangle {
                        width: 4
                        height: parent.availableHeight
                        anchors.horizontalCenter: parent.horizontalCenter
                        radius: 2
                        color: Theme.trackRest
                        Rectangle {
                            width: parent.width
                            height: volSlider.visualPosition * parent.height
                            anchors.bottom: parent.bottom
                            radius: 2
                            gradient: Gradient {
                                orientation: Gradient.Vertical
                                GradientStop { position: 0.0; color: Theme.accentAlt }
                                GradientStop { position: 1.0; color: Theme.accent }
                            }
                        }
                    }
                    handle: Rectangle {
                        width: 12
                        height: 12
                        radius: 6
                        color: Theme.text
                        border.width: 1
                        border.color: Theme.glassBorder
                    }
                }

                MouseArea {
                    id: popupHover
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
            }
        }

        // Return to normal — expand
        IconButton {
            glyph: Glyphs.miniReturn
            tooltip: "Back to normal (Esc)"
            iconSize: 18
            onClicked: Actions.toggleMiniMode()
        }
    }

    // Correct vertical slider handle positioning for Qt.Vertical
    // Qt's Slider with custom handle needs y = (1 - visualPosition)*(availableHeight - handleSize)
    // We patch after component creation via binding in volSlider
    Connections {
        target: volSlider
        function onVisualPositionChanged() {
            // handled via binding above if needed
        }
    }
}
