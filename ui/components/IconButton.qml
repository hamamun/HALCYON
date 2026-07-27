import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one button — §B.1.
//
// A play button in M3U is *this component* with the same icon, size and hover
// behaviour as Local's. Not a lookalike: the same file. 40x40 hit target, glass
// hover ring, 220 ms OutCubic, tooltip on hover — everywhere, forever.
AbstractButton {
    id: root

    property string glyph: ""              // see ui/components/Glyphs.qml
    property string tooltip: ""
    property bool active: false            // "on" state, e.g. shuffle enabled
    property real iconSize: Theme.iconSize
    property color iconColor: Theme.text
    property color activeColor: Theme.accent
    property bool showRing: true

    implicitWidth: Theme.hitTarget
    implicitHeight: Theme.hitTarget
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    opacity: enabled ? 1.0 : Theme.opacityDisabled

    background: Rectangle {
        anchors.fill: parent
        radius: Theme.radiusControl
        visible: root.showRing
        color: root.pressed ? Theme.glassFillPressed
             : root.hovered ? Theme.glassFillHover
             : "transparent"
        border.width: root.hovered || root.active ? 1 : 0
        border.color: root.active ? Theme.accentDim : Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    contentItem: Item {
        Text {
            anchors.centerIn: parent
            text: root.glyph
            font.family: Theme.fontFamilyIcons
            font.pixelSize: root.iconSize
            color: root.active ? root.activeColor
                 : root.hovered ? Theme.text
                 : Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, Theme.opacityRest)
            scale: root.pressed ? 0.90 : 1.0

            Behavior on color {
                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
            Behavior on scale {
                NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }
    }

    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.delay: 500
    ToolTip.text: tooltip
}
