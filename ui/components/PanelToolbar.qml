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

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.glassBorder
    }
}
