import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one confirmation dialog — §B.1. Used wherever an action is destructive
// enough to warrant a check (Clear Playlist with >1 item, §P1.5).
Dialog {
    id: root

    property string message: ""
    // Label of the confirming button. Defaults to "Clear" (the first user was
    // Clear Playlist, §P1.5); destructive flows like deleting a saved
    // playlist pass their own verb so the button names the action it takes.
    property string confirmText: "Clear"
    property string confirmGlyph: Glyphs.clearAll

    signal confirmed()

    anchors.centerIn: Overlay.overlay
    modal: true
    padding: Theme.spaceXl
    closePolicy: Popup.CloseOnEscape

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(Theme.baseElevated.r, Theme.baseElevated.g, Theme.baseElevated.b, 0.98)
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

            IconButton {
                glyph: Glyphs.cancel
                tooltip: "Cancel"
                onClicked: root.close()
            }
            IconButton {
                glyph: root.confirmGlyph
                tooltip: root.confirmText
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
