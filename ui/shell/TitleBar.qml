import QtQuick
import QtQuick.Window
import Halcyon.Ui

// The title bar — 44px, §P1.4.
//
// Mode chips render from the registry (`Modes.list`), so Phase 2 and Phase 3 add
// a chip by appending one line to core/modes.py and **never editing this file**
// (§A.2). In Phase 1 exactly one chip renders, and that is correct, not a
// placeholder.
//
// The one home for: mode switching, settings (gear), window buttons.
Item {
    id: root

    property string activeMode: ""
    property bool showModeChips: modeRepeater.count > 1

    signal modeRequested(string modeId)

    height: Theme.titleBarHeight

    // Drag-to-move. Double-click maximises — the same action the shell exposes,
    // not a second implementation.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: root.Window.window.startSystemMove()
        onDoubleClicked: Actions.toggleMaximized()
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.glassBorder
        opacity: 0.6
    }

    // ------------------------------------------------------------ identity --
    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceLg
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spaceSm

        Rectangle {
            width: 10; height: 10; radius: 2
            anchors.verticalCenter: parent.verticalCenter
            rotation: 45
            gradient: Gradient {
                GradientStop { position: 0.0; color: Theme.accent }
                GradientStop { position: 1.0; color: Theme.accentAlt }
            }
        }
        Text {
            text: "Halcyon"
            anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            font.weight: Theme.weightBold
            font.letterSpacing: 0.4
            color: Theme.text
        }
    }

    // --------------------------------------------------------- mode chips --
    Row {
        id: chipRow
        anchors.centerIn: parent
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

    // ------------------------------------------------------ window buttons --
    Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: Theme.spaceSm
        spacing: 0

        IconButton {
            glyph: Glyphs.settings
            tooltip: "Settings"
            onClicked: Actions.showSettings()
        }
        Item { width: Theme.spaceSm; height: 1 }
        IconButton {
            glyph: Glyphs.minimize
            tooltip: "Minimise"
            showRing: false
            onClicked: Actions.minimizeWindow()
        }
        IconButton {
            glyph: root.Window.window && root.Window.window.visibility === Window.Maximized
                   ? Glyphs.restore : Glyphs.maximize
            tooltip: "Maximise"
            showRing: false
            onClicked: Actions.toggleMaximized()
        }
        IconButton {
            glyph: Glyphs.close
            tooltip: "Close"
            showRing: false
            iconColor: Theme.danger
            onClicked: Actions.closeWindow()

            background: Rectangle {
                radius: Theme.radiusControl
                color: parent.pressed ? Qt.darker(Theme.danger, 1.3)
                     : parent.hovered ? Theme.danger : "transparent"
                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }
            }
        }
    }
}
