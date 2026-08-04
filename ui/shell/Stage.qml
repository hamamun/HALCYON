import QtQuick

// The centre stage slot.
//
// A normal mode owns its stage only while active.  A mode can opt into
// `keepStageAlive` (Web does) and its Loader then stays constructed but hidden
// while another mode is active.  This is intentionally generic: the shell does
// not know which mode is being parked, only the capability declared by its
// ModeSpec.
Item {
    id: root

    property var modeSpecs: []
    property string activeMode: ""

    // Aurora remains behind every stage.  A Web page is a native child HWND and
    // fills only its own page rectangle; it never overlaps this scene-graph
    // background or any chrome above it.
    AuroraBackground {
        anchors.fill: parent
    }

    Repeater {
        id: stageRepeater
        model: root.modeSpecs

        delegate: Item {
            id: stageSlot
            required property var modelData
            required property int index

            anchors.fill: parent
            property bool isCurrent: modelData.id === root.activeMode
            property bool wasActivated: false
            property bool shouldStayLoaded: isCurrent || (modelData.keepStageAlive && wasActivated)
            readonly property var loadedItem: stageLoader.item

            // The Web page itself is native, so hiding the QML loader alone is
            // not enough.  WebStage exposes `stageActive`; this generic bridge
            // calls it when present before the slot disappears.
            function setChildStageActive(active) {
                if (stageLoader.item && "stageActive" in stageLoader.item)
                    stageLoader.item.stageActive = active
            }

            onIsCurrentChanged: {
                if (isCurrent)
                    wasActivated = true
                setChildStageActive(isCurrent)
            }
            Component.onCompleted: {
                if (isCurrent)
                    wasActivated = true
            }

            visible: isCurrent
            enabled: isCurrent

            Loader {
                id: stageLoader
                anchors.fill: parent
                active: stageSlot.shouldStayLoaded
                source: modelData.stageQml || ""
                asynchronous: false

                onLoaded: {
                    stageSlot.setChildStageActive(stageSlot.isCurrent)
                }
                onStatusChanged: {
                    if (status === Loader.Error)
                        console.warn("Stage: failed to load", source)
                }
            }
        }
    }

    // The mode's transport bar is injected by Main.qml here.  It remains above
    // the active stage, but Web supplies no transport URL, so no bottom shell is
    // rendered in Web mode.
    default property alias overlay: overlayArea.data
    Item {
        id: overlayArea
        anchors.fill: parent
    }
}
