import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// One labelled text field — §B.1. API key, username, password.
//
// Writes on editing-finished rather than on every keystroke: Settings debounces
// to disk anyway, but a `changed` signal per character would make the subtitle
// service drop its session token forty times while you paste a key.
Item {
    id: root

    property string label: ""
    property string description: ""
    property string placeholder: ""
    property string value: ""
    property bool secret: false

    signal edited(string value)

    implicitHeight: column.implicitHeight

    Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.spaceXs

        Row {
            width: parent.width
            spacing: Theme.spaceSm

            Text {
                width: 140
                anchors.verticalCenter: parent.verticalCenter
                text: root.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.text
            }

            TextField {
                id: field
                width: parent.width - 140 - Theme.spaceSm - (reveal.visible ? reveal.width + Theme.spaceSm : 0)
                text: root.value
                placeholderText: root.placeholder
                echoMode: (root.secret && !reveal.showing) ? TextInput.Password : TextInput.Normal
                selectByMouse: true
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.text
                placeholderTextColor: Theme.textFaint
                onEditingFinished: if (text !== root.value) root.edited(text)

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: Theme.glassFill
                    border.width: 1
                    border.color: field.activeFocus ? Theme.accent : Theme.glassBorder

                    Behavior on border.color {
                        ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }
                }
            }

            // Pasting a 32-character key blind is how a typo'd key turns into
            // "OpenSubtitles rejected the API key" with no way to check.
            IconButton {
                id: reveal
                property bool showing: false
                anchors.verticalCenter: parent.verticalCenter
                visible: root.secret
                glyph: showing ? Glyphs.conceal : Glyphs.reveal
                iconSize: 14
                implicitWidth: 30
                implicitHeight: 30
                tooltip: showing ? "Hide" : "Show"
                onClicked: showing = !showing
            }
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
}
