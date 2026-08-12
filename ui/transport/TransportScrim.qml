import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// Vertical gradient behind a control bar so icons stay legible over bright
// video. Same treatment in every mode that draws a bar; the bar's *height*
// differs per mode (§B.2) and this follows it.
//
// `solid` is the Turbo path: there is no scene-graph picture to fade over,
// so the light Soft gradient would leave the controls washed out. A dark
// strip keeps the same shape and the same buttons readable.
Rectangle {
    property bool solid: false

    color: "transparent"
    gradient: Gradient {
        GradientStop {
            position: 0.0
            color: solid ? Qt.rgba(Theme.base.r, Theme.base.g, Theme.base.b, 0.72)
                         : Theme.scrimTop
        }
        GradientStop {
            position: 1.0
            color: solid ? Theme.glassFillSolid : Theme.scrimBottom
        }
    }
}
