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

    // Opt-in trailing clear affordance. It is deliberately part of the shared
    // field rather than a one-off overlay in a panel, so every searchable field
    // can reserve text room and clear itself in exactly the same way.
    property bool clearable: false
    property string clearTooltip: "Clear text"
    signal clearRequested()
    readonly property bool clearButtonVisible: clearable && text.length > 0

    implicitWidth: 200
    implicitHeight: 32
    padding: 0
    leftPadding: Theme.spaceMd
    // Do not let typed text disappear under the trailing ×.
    rightPadding: root.clearButtonVisible
                  ? Theme.spaceXs + clearButton.width + Theme.spaceXs
                  : Theme.spaceMd

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

    // A compact clear target fits within the 32px field while retaining the
    // same glass hover treatment and icon vocabulary as the rest of the UI.
    Item {
        id: clearButton
        parent: root
        anchors.right: root.right
        anchors.rightMargin: Theme.spaceXs
        anchors.verticalCenter: root.verticalCenter
        width: root.height - Theme.spaceXs * 2
        height: width
        z: 1                         // above TextField's editable content
        opacity: root.clearButtonVisible ? 1.0 : 0.0
        visible: opacity > 0.0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }

        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusSmall
            color: clearArea.pressed ? Theme.glassFillPressed
                 : clearArea.containsMouse ? Theme.glassFillHover : "transparent"

            Behavior on color {
                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }

        Text {
            anchors.centerIn: parent
            text: Glyphs.cancel
            font.family: Theme.fontFamilyIcons
            font.pixelSize: Theme.iconSize - 6
            color: clearArea.containsMouse ? Theme.text : Theme.textMuted

            Behavior on color {
                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }

        MouseArea {
            id: clearArea
            anchors.fill: parent
            enabled: root.clearButtonVisible
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.text = "";
                root.forceActiveFocus();
                root.clearRequested();
            }

            ToolTip.visible: containsMouse && root.clearButtonVisible
            ToolTip.delay: 500
            ToolTip.text: root.clearTooltip
        }
    }
}
