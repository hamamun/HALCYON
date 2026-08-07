import QtQuick
import QtQuick.Window
import Halcyon.Ui

// The frameless window — §P1.5, §B.1.
//
// One window shell, identical in every mode. Eight resize handles, drag-move,
// double-click maximise, Aero snap, remembered geometry. Modes change what is
// *inside* it; they never change the chassis.
Window {
    id: shell

    property int resizeMargin: 6
    property bool fullscreen: false
    property bool miniModeActive: false // v1.1 §M — hides resize handles in mini
    readonly property bool maximizedOrFull: visibility === Window.Maximized || fullscreen

    // flags overridden in Main.qml to add StayOnTop in mini — keep base here
    flags: Qt.Window | Qt.FramelessWindowHint
    color: "transparent"
    minimumWidth: 860
    minimumHeight: 520

    // ------------------------------------------------------------ geometry --
    function saveGeometry() {
        if (visibility === Window.Windowed) {
            Settings.set("window.x", shell.x);
            Settings.set("window.y", shell.y);
            Settings.set("window.width", shell.width);
            Settings.set("window.height", shell.height);
        }
        Settings.set("window.maximized", visibility === Window.Maximized);
    }

    function restoreGeometry() {
        var w = Settings.get("window.width", 1280);
        var h = Settings.get("window.height", 760);
        var sx = Settings.get("window.x", -1);
        var sy = Settings.get("window.y", -1);
        shell.width = Math.max(w, shell.minimumWidth);
        shell.height = Math.max(h, shell.minimumHeight);
        if (sx >= 0 && sy >= 0) {
            shell.x = sx;
            shell.y = sy;
        } else {
            shell.x = Screen.width / 2 - shell.width / 2;
            shell.y = Screen.height / 2 - shell.height / 2;
        }
        if (Settings.get("window.maximized", false))
            shell.visibility = Window.Maximized;
    }

    function toggleMaximized() {
        if (fullscreen)
            return;
        visibility = (visibility === Window.Maximized) ? Window.Windowed : Window.Maximized;
    }

    function setFullscreen(on) {
        if (on === fullscreen)
            return;
        fullscreen = on;
        visibility = on ? Window.FullScreen
                        : (Settings.get("window.maximized", false) ? Window.Maximized
                                                                   : Window.Windowed);
    }

    onXChanged: saveTimer.restart()
    onYChanged: saveTimer.restart()
    onWidthChanged: saveTimer.restart()
    onHeightChanged: saveTimer.restart()

    Timer {
        id: saveTimer
        interval: 500
        onTriggered: shell.saveGeometry()
    }

    // ------------------------------------------------------- resize edges --
    // Eight handles: four edges, four corners. Qt's startSystemResize gives us
    // native behaviour (including snap-to-edge) for free.
    Repeater {
        model: [
            { e: Qt.LeftEdge,                   c: Qt.SizeHorCursor,  x: 0, y: 1, w: 0, h: 1 },
            { e: Qt.RightEdge,                  c: Qt.SizeHorCursor,  x: 1, y: 1, w: 0, h: 1 },
            { e: Qt.TopEdge,                    c: Qt.SizeVerCursor,  x: 1, y: 0, w: 1, h: 0 },
            { e: Qt.BottomEdge,                 c: Qt.SizeVerCursor,  x: 1, y: 1, w: 1, h: 0 },
            { e: Qt.LeftEdge | Qt.TopEdge,      c: Qt.SizeFDiagCursor, x: 0, y: 0, w: 0, h: 0 },
            { e: Qt.RightEdge | Qt.TopEdge,     c: Qt.SizeBDiagCursor, x: 1, y: 0, w: 0, h: 0 },
            { e: Qt.LeftEdge | Qt.BottomEdge,   c: Qt.SizeBDiagCursor, x: 0, y: 1, w: 0, h: 0 },
            { e: Qt.RightEdge | Qt.BottomEdge,  c: Qt.SizeFDiagCursor, x: 1, y: 1, w: 0, h: 0 }
        ]

        delegate: MouseArea {
            required property var modelData
            z: 9999
            visible: !shell.maximizedOrFull && !shell.miniModeActive
            enabled: visible
            cursorShape: modelData.c

            width: modelData.w ? shell.width - shell.resizeMargin * 2 : shell.resizeMargin
            height: modelData.h ? shell.height - shell.resizeMargin * 2 : shell.resizeMargin
            x: modelData.x === 0 ? 0
             : (modelData.w ? shell.resizeMargin : shell.width - shell.resizeMargin)
            y: modelData.y === 0 ? 0
             : (modelData.h ? shell.resizeMargin : shell.height - shell.resizeMargin)

            onPressed: shell.startSystemResize(modelData.e)
        }
    }
}
