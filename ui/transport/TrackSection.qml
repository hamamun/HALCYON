import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Halcyon.Ui

// A labelled list of selectable tracks, used twice inside TrackPopover (audio
// and subtitles). Extracted so the two are provably the same control rather
// than two similar ones — §B.1.
//
// Two rules this control exists to enforce, in one place, for both sections:
//
//   1. **The off row is pinned.** libVLC always publishes a "Disable" entry
//      (id -1). It is not a track, it is the way back to silence / no
//      subtitles, so it sits above the list and never scrolls away — you can
//      always turn a track off without hunting for the row.
//   2. **Past `maxVisibleRows` the list scrolls itself, not the popover.**
//      A file with 50+ embedded subtitles used to render 50+ rows and blow the
//      popover past the top of the screen, so most of them were unreachable.
//      Beyond five rows this becomes a fixed-height scroll area with its own
//      slim scrollbar; the popover's overall height stops growing.
//
// Tracks arrive as `{ id, label, off }` — the off row is identified by its id
// in core/app.py, never by matching the localised word "Disable" in QML.
ColumnLayout {
    id: root

    property string title: ""
    property var tracks: []
    property int currentId: -1
    property string emptyText: "None"
    //: How many rows are shown before the section starts scrolling (§2.c/2.d).
    property int maxVisibleRows: 5

    signal trackChosen(int id)

    readonly property int rowHeight: 30
    readonly property var offTrack: {
        for (var i = 0; i < tracks.length; i++)
            if (tracks[i].off === true)
                return tracks[i];
        return null;
    }
    readonly property var realTracks: {
        var out = [];
        for (var i = 0; i < tracks.length; i++)
            if (tracks[i].off !== true)
                out.push(tracks[i]);
        return out;
    }
    readonly property bool scrolls: realTracks.length > maxVisibleRows

    spacing: Theme.spaceXs

    // ------------------------------------------------------------- header --
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spaceSm

        Text {
            text: root.title
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            font.weight: Theme.weightBold
            color: Theme.textFaint
        }
        Item { Layout.fillWidth: true }
        // A count only earns its place once the list is long enough to scroll —
        // "1" next to a single track is noise.
        Text {
            visible: root.scrolls
            text: root.realTracks.length
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }

    Text {
        visible: root.tracks.length === 0
        text: root.emptyText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.textFaint
        Layout.fillWidth: true
    }

    // ------------------------------------------------- pinned "off" row --
    // Outside the Flickable on purpose: it must stay put while the list below
    // it scrolls.
    ListRow {
        id: offRow
        visible: root.offTrack !== null
        Layout.fillWidth: true
        Layout.preferredHeight: root.rowHeight
        current: root.offTrack !== null && root.offTrack.id === root.currentId
        onClicked: { if (root.offTrack !== null) root.trackChosen(root.offTrack.id) }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            text: root.offTrack !== null ? root.offTrack.label : ""
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            // `offRow.current`, not `parent.current`. ListRow reparents its
            // default children into an inner content Item, so `parent` here is
            // that Item — which has no `current`, so the expression was always
            // undefined and the label never turned accent. The row's leading
            // accent bar did light up, which is why the two disagreed.
            color: offRow.current ? Theme.accent : Theme.textMuted
        }
    }

    // A hairline under the pinned row makes the "this part does not move"
    // boundary visible instead of implied.
    Rectangle {
        visible: root.offTrack !== null && root.realTracks.length > 0
        Layout.fillWidth: true
        Layout.topMargin: 1
        Layout.bottomMargin: 1
        Layout.preferredHeight: 1
        color: Theme.glassBorder
    }

    // ------------------------------------------------- scrollable tracks --
    ListView {
        id: list
        visible: root.realTracks.length > 0
        Layout.fillWidth: true
        Layout.preferredHeight: root.scrolls
                                ? root.maxVisibleRows * root.rowHeight
                                : root.realTracks.length * root.rowHeight
        clip: true
        interactive: root.scrolls
        model: root.realTracks
        boundsBehavior: Flickable.StopAtBounds
        // Keep the playing track in view when the popover opens on a long list.
        currentIndex: {
            for (var i = 0; i < root.realTracks.length; i++)
                if (root.realTracks[i].id === root.currentId)
                    return i;
            return -1;
        }
        onVisibleChanged: if (visible && currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

        ScrollBar.vertical: ScrollBar {
            policy: root.scrolls ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
            width: 6
        }

        delegate: ListRow {
            id: trackRow
            required property var modelData
            width: ListView.view.width - (root.scrolls ? Theme.spaceSm : 0)
            height: root.rowHeight
            current: modelData.id === root.currentId
            onClicked: root.trackChosen(modelData.id)

            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.right: parent.right
                text: trackRow.modelData.label
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                // See offRow above: `parent` is ListRow's inner content Item.
                color: trackRow.current ? Theme.accent : Theme.text
            }
        }
    }
}
