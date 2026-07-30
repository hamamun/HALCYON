import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// A labelled list of selectable tracks, used for audio, embedded subtitles and
// local subtitle files inside TrackPopover. Extracted so the three are
// provably the same control rather than three similar ones — §B.1.
//
// At most five rows show at once; a sixth track makes a thin scrollbar appear
// (§B.1 — the one scrollbar, ThinScrollBar). Five or fewer: no scrollbar, and
// the view is inert so wheel gestures fall through to the popover itself.
ColumnLayout {
    id: root

    property string title: ""
    property var tracks: []
    property int currentId: -1
    property string emptyText: "None"
    property bool allowOff: false

    readonly property int maxVisibleRows: 5
    readonly property int rowHeight: 30

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
        visible: root.tracks.length === 0 && !root.allowOff
        text: root.emptyText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.textFaint
        Layout.fillWidth: true
    }

    // Disable option - sticky header when allowOff is true
    ListRow {
        Layout.fillWidth: true
        visible: root.allowOff && root.tracks.length > 0
        height: root.rowHeight
        current: root.currentId === -1
        onClicked: root.trackChosen(-1)

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            text: "Disable"
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: current ? Theme.accent : Theme.text
        }
    }

    Item {
        Layout.fillWidth: true
        visible: root.tracks.length > 0

        readonly property int visibleRows: Math.min(root.maxVisibleRows, root.tracks.length)
        implicitHeight: list.needsScroll
                        ? root.maxVisibleRows * root.rowHeight
                          + (root.maxVisibleRows - 1) * list.spacing
                        : visibleRows * root.rowHeight
                          + (visibleRows - 1) * list.spacing

        ListView {
            id: list
            anchors.fill: parent
            anchors.rightMargin: needsScroll ? 12 : 0

            readonly property bool needsScroll: count > root.maxVisibleRows

            model: root.tracks
            spacing: Theme.spaceXs
            clip: true
            interactive: needsScroll
            boundsBehavior: Flickable.StopAtBounds

            delegate: ListRow {
                id: row
                required property var modelData
                width: ListView.view.width
                height: root.rowHeight
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
                    color: row.current ? Theme.accent : Theme.text
                }
            }

            ScrollBar.vertical: ThinScrollBar { }
        }
    }
}
