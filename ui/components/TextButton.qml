import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Labelled button — §B.1. Dialog confirmations, panel toolbar items that need a
// word rather than a glyph, settings rows.
AbstractButton {
    id: root

    property bool primary: false
    property string glyph: ""

    implicitHeight: 32
    implicitWidth: content.implicitWidth + Theme.spaceLg * 2
    hoverEnabled: true
    opacity: enabled ? 1.0 : Theme.opacityDisabled

    background: Rectangle {
        radius: Theme.radiusSmall
        color: root.primary
               ? (root.pressed ? Qt.darker(Theme.accent, 1.2)
                               : root.hovered ? Qt.lighter(Theme.accent, 1.08) : Theme.accent)
               : (root.pressed ? Theme.glassFillPressed
                               : root.hovered ? Theme.glassFillHover : Theme.glassFill)
        border.width: root.primary ? 0 : 1
        border.color: Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    contentItem: Row {
        id: content
        spacing: Theme.spaceSm
        anchors.centerIn: parent

        Text {
            visible: root.glyph.length > 0
            text: root.glyph
            font.pixelSize: Theme.iconSize - 4
            color: root.primary ? Theme.textOnAccent : Theme.text
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            font.weight: Theme.weightMedium
            color: root.primary ? Theme.textOnAccent : Theme.text
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
