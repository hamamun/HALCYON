import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one confirmation dialog — §B.1. Used wherever an action is destructive
// enough to warrant a check (Clear Playlist with >1 item, §P1.5).
Dialog {
    id: root

    property string message: ""

    signal confirmed()

    anchors.centerIn: Overlay.overlay
    modal: true
    padding: Theme.spaceXl
    closePolicy: Popup.CloseOnEscape

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    header: Text {
        text: root.title
        padding: Theme.spaceXl
        bottomPadding: 0
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Theme.weightBold
        color: Theme.text
    }

    contentItem: Text {
        text: root.message
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeBody
        color: Theme.textMuted
    }

    footer: Item {
        implicitHeight: 56
        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spaceSm

            TextButton {
                text: "Cancel"
                onClicked: root.close()
            }
            TextButton {
                text: "Clear"
                primary: true
                onClicked: { root.confirmed(); root.close(); }
            }
        }
    }

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
}
