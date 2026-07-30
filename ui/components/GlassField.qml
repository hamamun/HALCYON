import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one text field — §B.1.
//
// API keys, the subtitle search box, anything the user types into: glass fill,
// 1px border, accent ring on focus. Same radius and motion as every other
// control, so it cannot drift away from the icon buttons beside it.
TextField {
    id: root

    implicitWidth: 200
    implicitHeight: 32
    padding: 0
    leftPadding: Theme.spaceMd
    rightPadding: Theme.spaceMd

    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeSmall
    color: Theme.text
    placeholderTextColor: Theme.textFaint
    selectionColor: Theme.accentDim
    selectedTextColor: Theme.text
    selectByMouse: true
    clip: true

    background: Rectangle {
        radius: Theme.radiusSmall
        color: root.activeFocus ? Theme.glassFillHover : Theme.glassFill
        border.width: 1
        border.color: root.activeFocus ? Theme.accentDim : Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
        Behavior on border.color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }
}
