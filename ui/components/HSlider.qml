import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one slider — §B.1. Volume, EQ bands, video adjust and the seek bar's
// track all derive from this look.
Slider {
    id: root

    property real trackHeight: 4
    property color trackColor: Theme.trackRest
    property color fillColor: Theme.accent
    property bool showHandle: true
    property real handleSize: 12

    implicitHeight: Theme.hitTarget
    hoverEnabled: true

    background: Rectangle {
        x: root.leftPadding
        y: root.topPadding + root.availableHeight / 2 - height / 2
        width: root.availableWidth
        height: root.trackHeight
        radius: height / 2
        color: root.trackColor

        Rectangle {
            width: root.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.accent }
                GradientStop { position: 1.0; color: Theme.accentAlt }
            }
        }

        Behavior on height {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + root.availableHeight / 2 - height / 2
        width: root.handleSize
        height: width
        radius: width / 2
        color: Theme.text
        // Always visible when the slider is enabled: a handle that only
        // appears on hover reads as a disabled/greyed-out control, which is
        // exactly how the volume and seek sliders were being perceived.
        visible: root.showHandle && root.enabled
        opacity: root.hovered || root.pressed ? 1.0 : 0.85
        scale: root.pressed ? 1.15 : 1.0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }

        Behavior on scale {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }
}
