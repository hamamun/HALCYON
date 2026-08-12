import QtQuick
import QtQuick.Window

// The native Turbo video surface, embedded in the single Halcyon window — §V.3.
//
// Turbo hands libVLC a native child window instead of the vmem callbacks, so
// the decoded frame can stay on the GPU. That child is a real platform window;
// `WindowContainer` (Qt 6.7+) is the supported way to place one inside a Qt
// Quick scene, and it is what keeps Turbo *inside* Halcyon rather than in an
// outside video window.
//
// Two consequences are inherent to native child windows and are the reason the
// transparent overlay window next door exists:
//
//   * ordinary QML siblings do NOT paint over the native surface — the child
//     HWND is composited by the window manager above the Quick scene graph;
//   * `MultiEffect` cannot sample it, so the full backdrop blur remains a Soft
//     guarantee (§V.3). Chrome over Turbo is tinted, not frosted.
//
// Everything here is failure-first: if the container cannot be created or the
// engine hands us no window, the shell reports it and the engine continues the
// same media on Soft (§V.4). This item never decides to use Turbo; it only
// renders the decision `App.effectiveVideoMode` already made.
Item {
    id: root

    // True when the engine reports it is actually running the native route.
    // Not the *selected* mode: a Turbo attempt that failed has already fallen
    // back, and this must follow the truth.
    property bool turboActive: false

    // Fetches the engine's native QWindow. Injected so this file stays testable
    // and never reaches for a context property that may not exist.
    property var windowProvider: null

    // Reported failures go here; Main.qml routes them to App.reportTurboFailure.
    signal failed(string reason)

    readonly property bool embedded: container.window !== null

    visible: turboActive
    onTurboActiveChanged: turboActive ? attach() : detach()
    // The shell creates this item only once Turbo is already effective, so the
    // change signal above may never fire for the initial value. Attaching on
    // completion too is what makes both entry paths work; attach() is
    // idempotent, so the overlap costs nothing.
    Component.onCompleted: if (turboActive) attach()

    function attach() {
        if (!turboActive)
            return;
        if (container.window !== null)
            return;
        var w = null;
        try {
            w = windowProvider ? windowProvider() : null;
        } catch (e) {
            root.failed("turboWindow() raised: " + e);
            return;
        }
        if (!w) {
            root.failed("the engine produced no native window");
            return;
        }
        try {
            container.window = w;
        } catch (e2) {
            root.failed("WindowContainer rejected the native window: " + e2);
            return;
        }
        if (container.window === null)
            root.failed("WindowContainer did not adopt the native window");
    }

    function detach() {
        // Clearing the container releases the child *before* the engine
        // destroys it. The reverse order leaves the container holding a
        // dangling platform window (§V.4: clean up the partial surface).
        if (container.window !== null)
            container.window = null;
    }

    // Destruction order matters for the same reason.
    Component.onDestruction: detach()

    WindowContainer {
        id: container
        objectName: "turboWindowContainer"
        anchors.fill: parent
    }
}
