import QtQuick
import Halcyon.Ui

// The shared Local / M3U / Web mode switcher.  It is deliberately separate
// from TitleBar: borderless mode removes that bar, but mode switching must
// remain available in every chrome home.
Row {
    id: root

    property string activeMode: ""
    readonly property int modeCount: modeRepeater.count

    signal modeRequested(string modeId)

    spacing: Theme.spaceXs

    Repeater {
        id: modeRepeater
        model: Modes.list

        delegate: Rectangle {
            required property var modelData
            readonly property bool isActive: modelData.id === root.activeMode

            width: chipLabel.implicitWidth + Theme.spaceLg * 2
            height: 28
            radius: Theme.radiusPill
            color: isActive ? Theme.glassFillHover
                 : chipMouse.containsMouse ? Theme.glassFill : "transparent"
            border.width: isActive ? 1 : 0
            border.color: Theme.accentDim

            Behavior on color {
                ColorAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
            }

            Text {
                id: chipLabel
                anchors.centerIn: parent
                text: modelData.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                font.weight: parent.isActive ? Theme.weightBold : Theme.weightNormal
                color: parent.isActive ? Theme.accent : Theme.textMuted
            }

            MouseArea {
                id: chipMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.modeRequested(modelData.id)
            }
        }
    }
}
