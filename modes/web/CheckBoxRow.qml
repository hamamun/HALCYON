import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Halcyon.Ui

// One row in the Clear Browsing Data dialog: a checkbox + label + optional
// warning line for destructive items (cookies, passwords, autofill).
//
// The parent dialog reads each row's ``checked`` property when the user hits
// Clear — so the row exposes ``checked`` as a plain alias and ticks the box
// on creation from ``defaultTick``.
Rectangle {
    id: root

    property string optionId: ""
    property string label: ""
    property bool defaultTick: false
    property bool destructive: false

    // The warning text shown beneath destructive rows ("You will be signed out…").
    property string warning: {
        if (!destructive) return ""
        if (optionId === "cookies") return "You will be signed out of sites."
        if (optionId === "passwords") return "Saved logins will be removed."
        if (optionId === "autofill") return "Saved addresses and cards will be removed."
        return ""
    }

    property alias checked: box.checked

    Layout.fillWidth: true
    Layout.preferredHeight: warning.length > 0 ? 52 : 36
    color: rowArea.containsMouse ? Theme.glassFillHover : "transparent"
    radius: Theme.radiusSmall

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            CheckBox {
                id: box
                checked: root.defaultTick
                onToggled: {}
                indicator: Rectangle {
                    implicitWidth: 18
                    implicitHeight: 18
                    radius: 3
                    border.width: 1
                    border.color: box.checked ? Theme.accent : Theme.glassBorder
                    color: box.checked ? Theme.accent : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: box.checked ? "✓" : ""
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        color: Theme.textOnAccent
                    }
                }
                contentItem: Item {}
            }
            Text {
                text: root.label
                Layout.fillWidth: true
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: root.destructive ? Theme.danger : Theme.text
                elide: Text.ElideRight
            }
            Text {
                text: root.destructive ? "⚠" : ""
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.warning
                opacity: root.destructive ? 1 : 0
            }
        }

        Text {
            Layout.leftMargin: 26
            Layout.fillWidth: true
            visible: root.warning.length > 0
            text: root.warning
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.warning
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: rowArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: box.checked = !box.checked
    }
}
