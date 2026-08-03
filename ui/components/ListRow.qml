import QtQuick
import Halcyon.Ui

// The one list row — §B.1. Local's queue, M3U's channels and Web's bookmarks
// are all this: same height, same selection highlight, same hover.
Rectangle {
    id: root

    property bool selected: false
    property bool current: false      // now playing / current page
    property bool hovered: hoverArea.containsMouse
    property alias containsMouse: hoverArea.containsMouse

    signal clicked(var mouse)
    signal doubleClicked(var mouse)
    signal rightClicked(var mouse)

    height: Theme.listRowHeight
    radius: Theme.radiusSmall
    color: selected ? Theme.glassFillHover
         : hovered ? Theme.glassFill
         : "transparent"

    Behavior on color {
        ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
    }

    // Now-playing marker: a single accent bar on the leading edge. Same
    // treatment in every mode.
    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        width: 3
        height: parent.height * 0.55
        radius: 1.5
        color: Theme.accent
        opacity: root.current ? 1 : 0
        Behavior on opacity {
            NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
        }
    }

    // The row-wide click/hover floor. It is declared BEFORE the content slot
    // so it stacks *beneath* whatever the caller puts inside the row: text and
    // plain Items do not accept mouse events, so row clicks fall through to
    // this area exactly as before — but nested controls (an Edit/Delete
    // IconButton, as in the M3U sources dialog) are above it and receive
    // their clicks. Declaring it after the content instead made every nested
    // button inert: this area consumed every press first, and the row merely
    // selected.
    MouseArea {
        id: hoverArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton)
                root.rightClicked(mouse);
            else
                root.clicked(mouse);
        }
        onDoubleClicked: function(mouse) { root.doubleClicked(mouse) }
    }

    default property alias content: contentArea.data
    Item {
        id: contentArea
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceMd
        anchors.rightMargin: Theme.spaceSm
    }
}
