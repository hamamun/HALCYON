import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Lyrics — Milestone 1.8. Sidecar .lrc (timed, auto-scrolling) plus embedded
// tags. Clicking a line seeks to it, which is why the timed format is worth
// parsing properly.
Item {
    id: root

    property var lyrics: typeof Lyrics !== "undefined" ? Lyrics : null
    readonly property int currentLine: lyrics ? lyrics.currentLine : -1

    onCurrentLineChanged: {
        if (currentLine >= 0 && lyrics && lyrics.timed)
            list.positionViewAtIndex(currentLine, ListView.Center);
    }

    ListView {
        id: list
        anchors.fill: parent
        clip: true
        model: root.lyrics ? root.lyrics.lines : []
        spacing: Theme.spaceXs
        visible: count > 0
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }

        delegate: Item {
            required property int index
            required property var modelData
            width: ListView.view.width
            height: lineText.implicitHeight + Theme.spaceSm

            readonly property bool isCurrent: index === root.currentLine

            Text {
                id: lineText
                width: parent.width
                text: modelData.text
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: parent.isCurrent ? Theme.fontSizeLarge : Theme.fontSizeBody
                font.weight: parent.isCurrent ? Theme.weightBold : Theme.weightNormal
                color: parent.isCurrent ? Theme.accent : Theme.textMuted
                opacity: parent.isCurrent ? 1.0 : 0.7

                Behavior on font.pixelSize {
                    NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
                }
                Behavior on color {
                    ColorAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: root.lyrics && root.lyrics.timed
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (modelData.timeMs >= 0) Actions.seekTo(modelData.timeMs)
            }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: Theme.spaceSm
        visible: list.count === 0

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Glyphs.lyrics
            font.family: Theme.fontFamilyIcons
            font.pixelSize: 30
            color: Theme.textFaint
        }
        Text {
            text: "No lyrics found"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
        }
    }
}
