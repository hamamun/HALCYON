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
    // Docks set this so Turbo (no blur, native HWND) still reads as a surface.
    // MiniBar leaves it false: it wants the light tint, and Mini is always Soft.
    property bool solidIfUnblurred: false

    readonly property bool blurActive: blurSource !== null
    readonly property color effectiveFill: (solidIfUnblurred && !blurActive)
                                           ? Theme.glassFillSolid
                                           : fillColor

    // Backdrop blur. MultiEffect is the supported route in Qt 6 and runs
    // entirely on the GPU.
    //
    // Instantiated only while there is something to sample. A live MultiEffect
    // (or its layer-enabled mask) that still points at the Stage cannot be
    // moved into the Turbo overlay window — Qt rejects "the same item on
    // different windows" and the docks vanish under the native HWND. Destroying
    // the effect *before* the chrome is reparented is what makes that move
    // legal.
    Loader {
        id: blurLoader
        anchors.fill: parent
        active: root.blurActive
        sourceComponent: blurComponent
    }

    Component {
        id: blurComponent

        Item {
            anchors.fill: parent

            MultiEffect {
                anchors.fill: parent
                source: root.blurSource
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
        }
    }

    // Tint + border, always drawn: it is what makes the glass read as a surface
    // rather than a smudge.
    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: root.effectiveFill
        border.width: root.showBorder ? root.borderWidth : 0
        border.color: root.borderColor
    }

    default property alias content: contentArea.data
    Item {
        id: contentArea
        anchors.fill: parent
    }
}
