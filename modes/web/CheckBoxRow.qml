import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Halcyon.Ui

// One row in the Clear Browsing Data dialog: a checkbox + label + optional
// subtitle line. Destructive items (cookies, passwords, autofill) carry a
// warning-coloured danger cue; ordinary items can carry a muted ``note`` that
// tells the user what they will notice after clearing (§4.1 spec table).
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

    // Muted "what you'll notice after" line for non-destructive rows.
    property string note: ""

    // The warning text shown beneath destructive rows ("You will be signed out…").
    property string warning: {
        if (!destructive) return ""
        if (optionId === "cookies") return "You will be signed out of sites."
        if (optionId === "passwords") return "Saved logins will be removed."
        if (optionId === "autofill") return "Saved addresses and cards will be removed."
        return ""
    }

    readonly property string subtitle: warning.length > 0 ? warning : note
    readonly property bool hasSubtitle: subtitle.length > 0

    property alias checked: box.checked

    Layout.fillWidth: true
    Layout.preferredHeight: hasSubtitle ? 52 : 36
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
                // Seed the initial tick from defaultTick exactly once.  Using a
                // live `checked: root.defaultTick` binding here makes every
                // later toggle (this MouseArea, or the box itself) an
                // "overwriting binding" error in the terminal.  defaultTick is
                // fixed at construction, so an onCompleted assignment gives the
                // same result without creating a binding to clobber.
                Component.onCompleted: checked = root.defaultTick
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
            visible: root.hasSubtitle
            text: root.subtitle
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: root.warning.length > 0 ? Theme.warning : Theme.textMuted
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
