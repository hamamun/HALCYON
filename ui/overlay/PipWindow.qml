import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui
import Halcyon.Engine

// Picture-in-Picture — §P2.5. Phase 2 owns this file.
//
// A borderless, always-on-top mini window bound to the SAME ring buffer as
// the main Stage (§0.3): no second player, no second decode, ~0 extra CPU.
// The reader refcount in engine/video_out.py exists precisely for this second
// surface — the main Stage never unbinds (§9).
//
// Drag anywhere to move. Releases snap to the nearest screen corner. The
// bottom-right grip resizes, aspect-locked 16:9. Double-click restores the
// main window (which may stay minimised while PiP plays — owner acceptance).
// Hover reveals play/pause and close, from the same IconButton vocabulary as
// everything else (§B.1). Geometry is remembered (via the Settings store).
Window {
    id: pip

    // The window to return to on double-click/restore, set by the M3U bar.
    property var mainWindow: null

    width: 480
    height: 270
    minimumWidth: 240
    minimumHeight: 135
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: Theme.base

    // Deliberately NOT transient for the main window. QML auto-assigns
    // `transientParent` to the window this one is declared inside, and the
    // platform then minimises/hides the transient together with its parent —
    // which is exactly the bug where minimising Halcyon also minimised the
    // PiP. `transientParent: null` makes this a fully independent top-level
    // window (Qt docs, Window.transientParent: "minimizing the parent window
    // will also minimize the transient window ... Setting the transientParent
    // to null will override this behavior"). The main window can therefore
    // minimise while the PiP keeps playing (§P2.5 checklist). Qt.WindowStays-
    // OnTopHint still keeps it above everything, and closing the main window
    // still tears this window down, because the Loader that instantiates it
    // lives inside the main window's scene (QML ownership, not OS ownership).
    transientParent: null

    Component.onCompleted: {
        // Restore where the user last put it — after the defaults above, so a
        // stored geometry wins (§M2.5: position and size remembered).
        var w = Settings.get("pip.w", 0);
        if (w > 0) {
            pip.width = w;
            pip.height = Settings.get("pip.h", Math.round(w * 9 / 16));
        }
        var px = Settings.get("pip.x", -1);
        var py = Settings.get("pip.y", -1);
        if (px >= 0 && py >= 0) {
            pip.x = px;
            pip.y = py;
        } else {
            snapToNearestCorner();
        }
        videoSurface.setSource(Player);
        pip.visible = true;
    }

    onClosing: {
        Settings.set("pip.x", pip.x);
        Settings.set("pip.y", pip.y);
        Settings.set("pip.w", pip.width);
        Settings.set("pip.h", pip.height);
    }

    // ---------------------------------------------------------------- video --
    // The same two-path picture as VideoStage (planar shader / packed item),
    // from the same engine. Twenty repeated lines beat editing a frozen file.
    VideoSurface {
        id: videoSurface
        anchors.fill: parent
        fillMode: 1                      // PreserveAspectFit — aspect never lies
        visible: !isPlanar
    }

    Loader {
        id: shaderLoader
        active: videoSurface && videoSurface.isPlanar
        x: videoSurface.contentRect.x
        y: videoSurface.contentRect.y
        width: videoSurface.contentRect.width
        height: videoSurface.contentRect.height
        sourceComponent: yuvComponent
    }

    Component {
        id: yuvComponent

        ShaderEffect {
            property variant texY: videoSurface.planeY
            property variant texU: videoSurface.planeU
            property variant texV: videoSurface.planeV
            fragmentShader: Qt.resolvedUrl("../shaders/yuv420p.frag.qsb")
        }
    }

    // ------------------------------------------------- drag, restore, snap --
    MouseArea {
        id: dragArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton

        property real grabX: 0
        property real grabY: 0

        onPressed: function(mouse) {
            grabX = mouse.x;
            grabY = mouse.y;
        }
        onPositionChanged: function(mouse) {
            if (!pressed) return;
            snapX.stop();
            snapY.stop();
            pip.x += mouse.x - grabX;
            pip.y += mouse.y - grabY;
        }
        onReleased: snapToNearestCorner()
        onDoubleClicked: pip.restoreMain()
    }

    function restoreMain() {
        if (mainWindow) {
            if (mainWindow.visibility === Window.Minimized)
                mainWindow.showNormal();
            mainWindow.raise();
            mainWindow.requestActivate();
        }
        pip.close();
    }

    function snapToNearestCorner() {
        var scr = pip.Screen;
        var aw = scr ? scr.desktopAvailableWidth : 1920;
        var ah = scr ? scr.desktopAvailableHeight : 1080;
        var m = 8;                                    // breathing room, like the shell
        var corners = [
            Qt.point(m, m),                 Qt.point(aw - pip.width - m, m),
            Qt.point(m, ah - pip.height - m), Qt.point(aw - pip.width - m, ah - pip.height - m)
        ];
        var best = corners[0];
        var bestDist = Number.MAX_VALUE;
        for (var i = 0; i < corners.length; i++) {
            var dx = pip.x - corners[i].x;
            var dy = pip.y - corners[i].y;
            var d = dx * dx + dy * dy;
            if (d < bestDist) { bestDist = d; best = corners[i]; }
        }
        snapX.to = best.x;  snapX.restart();
        snapY.to = best.y;  snapY.restart();
    }

    NumberAnimation {
        id: snapX
        target: pip
        property: "x"
        duration: Theme.durNormal
        easing.type: Theme.easing
    }
    NumberAnimation {
        id: snapY
        target: pip
        property: "y"
        duration: Theme.durNormal
        easing.type: Theme.easing
    }

    // ------------------------------------------- hover controls (shared parts) --
    HoverHandler {
        id: hover
        acceptedDevices: PointerDevice.Mouse
    }

    Row {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.spaceXs
        spacing: Theme.spaceXs

        opacity: hover.hovered ? 1.0 : 0.0
        visible: opacity > 0.0
        Behavior on opacity {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }

        IconButton {
            glyph: Player && Player.isPlaying ? Glyphs.pause : Glyphs.play
            tooltip: Player && Player.isPlaying ? "Pause" : "Play"
            onClicked: Actions.playPause()
        }
        IconButton {
            glyph: Glyphs.close
            tooltip: "Close"
            onClicked: pip.close()
        }
    }

    // -------------------------------------- resize grip, aspect-locked 16:9 --
    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 18
        height: 18
        color: resizeGrip.pressed ? Theme.glassFillPressed
             : resizeGrip.containsMouse ? Theme.glassFillHover : "transparent"
        radius: Theme.radiusSmall

        Text {
            anchors.centerIn: parent
            text: "◢"
            font.pixelSize: 10
            color: Theme.textFaint
            opacity: hover.hovered || resizeGrip.containsMouse ? 1.0 : 0.0
            Behavior on opacity {
                NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }

        MouseArea {
            id: resizeGrip
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.SizeFDiagCursor

            property real startWidth: 0
            property real grabX: 0

            onPressed: function(mouse) {
                startWidth = pip.width;
                grabX = pip.x + mouse.x;
            }
            onPositionChanged: function(mouse) {
                if (!pressed) return;
                var globalX = pip.x + mouse.x;
                var newWidth = Math.max(pip.minimumWidth,
                                        startWidth + (globalX - grabX));
                pip.width = newWidth;
                pip.height = Math.round(newWidth * 9 / 16);   // aspect-locked
            }
        }
    }

    // Esc closes, like every other transient surface in the app.
    Shortcut {
        sequence: "Escape"
        onActivated: pip.close()
    }
}
