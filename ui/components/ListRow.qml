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

    // The row's own hit area is declared **before** the content on purpose.
    //
    // Siblings stack in declaration order, so a MouseArea declared last sits on
    // top of everything the row contains — including any real control a caller
    // puts in it. That is what swallowed the first press on the search dialog's
    // per-result "Download" button: the button never saw the click, the row did,
    // and only the row's `doubleClicked` (wired to the same download) appeared
    // to work. Hence "it only downloads on a double click".
    //
    // Declared first, the content paints and handles events above it, while
    // plain Text/Item children — which accept no mouse events — still let a
    // click fall through to this area. Rows stay clickable; buttons inside them
    // work on the first click.
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
