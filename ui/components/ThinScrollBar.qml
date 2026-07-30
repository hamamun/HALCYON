import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one scrollbar — §B.1.
//
// Track lists that outgrow their five visible rows, the flyout itself when a
// small window caps its height — they all wear this: a 4px glass pill that
// only appears while there is something to scroll (visibleSize < 1 by way of
// the AsNeeded policy). Nothing draws its own scrollbar.
ScrollBar {
    id: control

    policy: ScrollBar.AsNeeded
    width: 8
    padding: 2
    background: Item { }

    contentItem: Rectangle {
        implicitWidth: 4
        radius: 2
        color: control.pressed ? Theme.accent
             : control.hovered ? Theme.glassBorderStrong
             : Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }
}
