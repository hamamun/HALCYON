import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one popover — §B.1. The transport gear menu, preset pickers and the
// settings flyout are all this.
//
// Note it reports `opened` outward: the transport bar must never auto-hide while
// a popover is open (§P1.4), and this is how it knows.
Popup {
    id: root

    property real blurRadius: Theme.blurModal

    padding: Theme.spaceMd
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1
                              duration: Theme.durNormal; easing.type: Theme.easing }
            NumberAnimation { property: "scale"; from: 0.96; to: 1
                              duration: Theme.durNormal; easing.type: Theme.easing }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0
                          duration: Theme.durFast; easing.type: Theme.easing }
    }

    background: Rectangle {
        radius: Theme.radiusControl
        color: Qt.rgba(0.043, 0.055, 0.078, 0.94)   // base, near-opaque
        border.width: 1
        border.color: Theme.glassBorder
    }
}
