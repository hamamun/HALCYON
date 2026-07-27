import QtQuick
import QtQuick.Effects
import Halcyon.Ui

// Frosted glass surface — §7, §B.1.
//
// The one implementation of "a panel". Every dock, popover, dialog and OSD pill
// is this component with different tokens. Blurring what is *behind* it is only
// possible because video is a scene-graph item (§0.3) — with a native video
// window there would be nothing to sample.
Item {
    id: root

    // What to blur. Usually the Stage. Leave null for a plain tinted panel
    // (cheaper, and correct when nothing interesting sits behind).
    property Item blurSource: null
    property real blurRadius: Theme.blurPanel
    property color fillColor: Theme.glassFill
    property color borderColor: Theme.glassBorder
    property real borderWidth: 1
    property real radius: Theme.radiusPanel
    property bool showBorder: true

    // Backdrop blur. MultiEffect is the supported route in Qt 6 and runs
    // entirely on the GPU.
    MultiEffect {
        anchors.fill: parent
        source: root.blurSource
        visible: root.blurSource !== null
        blurEnabled: true
        blur: 1.0
        blurMax: Math.round(root.blurRadius)
        autoPaddingEnabled: false
        maskEnabled: true
        maskSource: mask
    }

    Item {
        id: mask
        anchors.fill: parent
        layer.enabled: true
        visible: false
        Rectangle {
            anchors.fill: parent
            radius: root.radius
            color: "white"
        }
    }

    // Tint + border, always drawn: it is what makes the glass read as a surface
    // rather than a smudge.
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: root.fillColor
        border.width: root.showBorder ? root.borderWidth : 0
        border.color: root.borderColor
    }

    default property alias content: contentArea.data
    Item {
        id: contentArea
        anchors.fill: parent
    }
}
