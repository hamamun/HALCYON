import QtQuick
import Halcyon.Ui

// The one panel toolbar — §B.1.
//
// Same row height and same padding in every mode; the *number* of buttons is
// free (four in Local, one in M3U, three in Web) and each is spaced properly for
// its own count. That is §B.2: same parts, arrangement per mode. No reserved
// gaps, no ghost slots.
Item {
    id: root

    property alias spacing: row.spacing
    property int alignment: Qt.AlignLeft

    implicitHeight: Theme.toolbarRowHeight
    height: Theme.toolbarRowHeight

    default property alias buttons: row.data

    //: Right-edge slot for buttons that must not sit inside the main Row.
    //: Putting an anchored child directly in `row` draws the QML warning
    //: "Cannot specify left/right/horizontalCenter/fill/centerIn anchors for
    //: items inside Row" — a Row ignores horizontal anchors, so the button
    //: silently lost its intended edge. Anything assigned to `rightActions`
    //: is placed in this separate right-anchored Row instead.
    property alias rightActions: rightRow.data

    Row {
        id: row
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: root.alignment === Qt.AlignLeft ? parent.left : undefined
        anchors.right: root.alignment === Qt.AlignRight ? parent.right : undefined
        anchors.horizontalCenter: root.alignment === Qt.AlignHCenter ? parent.horizontalCenter : undefined
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceXs
    }

    Row {
        id: rightRow
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: Theme.spaceXs
        spacing: Theme.spaceXs
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.glassBorder
    }
}
