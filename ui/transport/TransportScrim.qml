import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// Vertical gradient behind a control bar so icons stay legible over bright
// video. Same treatment in every mode that draws a bar; the bar's *height*
// differs per mode (§B.2) and this follows it.
Rectangle {
    gradient: Gradient {
        GradientStop { position: 0.0; color: Theme.scrimTop }
        GradientStop { position: 1.0; color: Theme.scrimBottom }
    }
}
