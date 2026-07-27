import QtQuick
import Halcyon.Ui

// The centre stage — §P1.2.
//
// Loads `ModeSpec.stage_qml`, which defaults to the video surface and is
// overridden by Web mode to a WebEngineView (§P3.3). Because both are
// QQuickItems, the shell does not care which it got: same slot, same
// compositing, same overlays on top.
Item {
    id: root

    property string source: ""
    property bool osdEnabled: false
    readonly property alias item: loader.item

    // Aurora background — visible whenever the stage content is transparent or
    // letterboxed (§7).
    AuroraBackground {
        anchors.fill: parent
    }

    Loader {
        id: loader
        anchors.fill: parent
        source: root.source
        onStatusChanged: {
            if (status === Loader.Error)
                console.warn("Stage: failed to load", root.source);
        }
    }

    // Overlay layer: OSD and transient chrome live above the stage content but
    // below the transport bar. Only possible because the stage is a scene-graph
    // item (§0.3).
    default property alias overlay: overlayArea.data
    Item {
        id: overlayArea
        anchors.fill: parent
    }
}
