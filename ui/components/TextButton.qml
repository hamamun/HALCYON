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
    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    leftPadding: Theme.spaceLg
    rightPadding: Theme.spaceLg
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

    // Label centred in the *button*, not packed against its left edge.
    //
    // The contentItem used to be the Row itself, anchored `centerIn: parent`.
    // A Control positions and resizes its contentItem itself, so those anchors
    // never applied: the Row kept its own implicit width and sat at x = 0.
    // Invisible while the button hugged its label — and plainly wrong the
    // moment anything set an explicit width, which is exactly what the search
    // dialog's full-width "Search" and the footer's "Close" do.
    //
    // So the contentItem is now a plain Item the control is free to stretch,
    // with the glyph+label Row centred inside *that*. `implicitWidth`/
    // `implicitHeight` still report the Row's size, so an unsized button hugs
    // its label exactly as before.
    contentItem: Item {
        implicitWidth: content.implicitWidth
        implicitHeight: content.implicitHeight

        Row {
            id: content
            anchors.centerIn: parent
            spacing: root.glyph.length > 0 ? Theme.spaceSm : 0

            Text {
                visible: root.glyph.length > 0
                width: visible ? implicitWidth : 0
                text: root.glyph
                font.family: Theme.fontFamilyIcons
                font.pixelSize: Theme.iconSize - 4
                color: root.primary ? Theme.textOnAccent : Theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: root.text
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                font.weight: Theme.weightMedium
                color: root.primary ? Theme.textOnAccent : Theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
