import QtQuick
import QtQuick.Layouts
import Halcyon.Ui

// A labelled list of selectable tracks, used twice inside TrackPopover (audio
// and subtitles). Extracted so the two are provably the same control rather
// than two similar ones — §B.1.
ColumnLayout {
    id: root

    property string title: ""
    property var tracks: []
    property int currentId: -1
    property string emptyText: "None"
    property bool allowOff: false

    signal trackChosen(int id)

    spacing: Theme.spaceXs

    Text {
        text: root.title
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeTiny
        font.weight: Theme.weightBold
        color: Theme.textFaint
    }

    Text {
        visible: root.tracks.length === 0
        text: root.emptyText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.textFaint
        Layout.fillWidth: true
    }

    Repeater {
        model: root.tracks

        delegate: ListRow {
            required property var modelData
            Layout.fillWidth: true
            height: 30
            current: modelData.id === root.currentId
            onClicked: root.trackChosen(modelData.id)

            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.right: parent.right
                text: modelData.label
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: parent.current ? Theme.accent : Theme.text
            }
        }
    }
}
