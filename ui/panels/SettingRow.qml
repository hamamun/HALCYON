import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// One labelled toggle. Extracted so every settings row is provably the same
// control (§B.1) rather than four near-identical ones.
Item {
    id: root

    property string label: ""
    property string description: ""
    property bool checked: false

    signal toggled(bool on)

    implicitHeight: column.implicitHeight

    Column {
        id: column
        anchors.left: parent.left
        anchors.right: toggle.left
        anchors.rightMargin: Theme.spaceMd
        spacing: 2

        Text {
            width: parent.width
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            color: Theme.text
        }
        Text {
            width: parent.width
            text: root.description
            visible: text.length > 0
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }

    Switch {
        id: toggle
        anchors.right: parent.right
        anchors.verticalCenter: column.verticalCenter
        checked: root.checked
        onToggled: root.toggled(checked)

        indicator: Rectangle {
            implicitWidth: 40
            implicitHeight: 22
            x: toggle.width - width
            y: toggle.height / 2 - height / 2
            radius: height / 2
            color: toggle.checked ? Theme.accent : Theme.glassFill
            border.width: 1
            border.color: toggle.checked ? Theme.accent : Theme.glassBorder

            Behavior on color {
                ColorAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
            }

            Rectangle {
                x: toggle.checked ? parent.width - width - 3 : 3
                y: 3
                width: 16
                height: 16
                radius: 8
                color: toggle.checked ? Theme.textOnAccent : Theme.textMuted

                Behavior on x {
                    NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
                }
            }
        }
    }
}
