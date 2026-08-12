import QtQuick
import QtQuick.Window

// The transparent chrome overlay for Turbo — §V.3.
//
// A native child window (the Turbo video surface) is composited *above* the
// Qt Quick scene graph, so ordinary QML siblings cannot paint over it. The
// documented way to keep the transport bar, OSD and panels on top of native
// video is a second, transparent window stacked over the first — which is what
// this is.
//
// It is deliberately dumb: it owns no controls of its own. The shell moves its
// existing `chromeLayer` in here while Turbo is running and moves it straight
// back afterwards, so there is exactly one implementation of every control
// (§4.1) rather than a Soft copy and a Turbo copy that drift apart.
//
// Only ever instantiated while Turbo is genuinely active. In Soft — which is
// every session on a platform without the native route — this component is
// never created and the chrome never leaves the main window.
Window {
    id: overlay

    // The window whose body rectangle this overlay must cover.
    property var hostWindow: null
    // Body rectangle in hostWindow coordinates (below the title bar).
    property rect bodyRect: Qt.rect(0, 0, 0, 0)

    readonly property alias hostItem: content

    // Transparent, frameless and click-through-free: the chrome inside it must
    // still receive its own clicks, so this is a normal input-taking window
    // that simply has no background of its own.
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
    // Tracks the main window: minimise/restore and close follow the parent,
    // which is exactly what an overlay should do (the opposite of PipWindow,
    // which sets transientParent to null precisely to escape this).
    transientParent: hostWindow

    x: hostWindow ? hostWindow.x + bodyRect.x : 0
    y: hostWindow ? hostWindow.y + bodyRect.y : 0
    width: Math.max(1, bodyRect.width)
    height: Math.max(1, bodyRect.height)

    Item {
        id: content
        objectName: "turboChromeHost"
        anchors.fill: parent
    }
}
