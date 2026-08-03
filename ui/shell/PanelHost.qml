import QtQuick
import Halcyon.Ui

// The single left dock slot — §P1.2.
//
// One slot, N panels. Local's queue and M3U's channels land here, loaded from
// `ModeSpec.panel_qml`. A mode may leave the slot empty — Web keeps bookmarks in
// its top-bar dropdown and manager tab (§P3.5).
//
// The dock itself — width, glass, collapse animation — is shared and identical.
// What the panel puts inside is entirely the mode's business (§B.2).
Item {
    id: root

    property bool open: true
    property string source: ""
    property Item blurSource: null
    readonly property bool loading: loader.status === Loader.Loading
    readonly property alias item: loader.item

    width: open ? Theme.leftPanelWidth : 0
    clip: true
    visible: width > 0

    Behavior on width {
        NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
    }

    GlassPanel {
        width: Theme.leftPanelWidth
        height: parent.height
        blurSource: root.blurSource
        radius: 0
        showBorder: false

        Rectangle {
            anchors.right: parent.right
            width: 1
            height: parent.height
            color: Theme.glassBorder
        }

        Loader {
            id: loader
            anchors.fill: parent
            asynchronous: false
            source: root.source
            onStatusChanged: {
                if (status === Loader.Error)
                    console.warn("PanelHost: failed to load", root.source);
            }
        }
    }
}
