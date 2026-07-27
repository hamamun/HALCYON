import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Local's left panel — §P1.5.
//
// The toolbar here is THE ONLY PLACE these four actions exist (§4.1):
// Add Files, Add Folder, Clear Selected, Clear Playlist. There is no menu bar
// copy, no empty-stage button, no transport-bar duplicate. The empty state below
// and Ctrl+O both *invoke* Actions.addFiles() — they do not implement it.
Item {
    id: root

    property var model: typeof LocalPlaylist !== "undefined" ? LocalPlaylist : null
    property var selection: []

    function isSelected(row) { return selection.indexOf(row) >= 0 }

    function selectOnly(row) { selection = [row] }

    function toggleSelection(row) {
        var next = selection.slice();
        var at = next.indexOf(row);
        if (at >= 0) next.splice(at, 1); else next.push(row);
        selection = next;
    }

    function selectRange(row) {
        if (selection.length === 0) { selection = [row]; return; }
        var anchor = selection[selection.length - 1];
        var lo = Math.min(anchor, row), hi = Math.max(anchor, row);
        var next = [];
        for (var i = lo; i <= hi; i++) next.push(i);
        selection = next;
    }

    // ------------------------------------------------------------ toolbar --
    PanelToolbar {
        id: toolbar
        width: parent.width
        anchors.top: parent.top

        IconButton {
            glyph: Glyphs.addFile
            tooltip: "Add files (Ctrl+O)"
            onClicked: Actions.addFiles()
        }
        IconButton {
            glyph: Glyphs.addFolder
            tooltip: "Add folder"
            onClicked: Actions.addFolder()
        }
        IconButton {
            glyph: Glyphs.clearItem
            tooltip: "Clear selected (Delete)"
            enabled: root.selection.length > 0     // §P1.5: only with a selection
            onClicked: Actions.clearSelected()
        }
        IconButton {
            glyph: Glyphs.clearAll
            tooltip: "Clear playlist"
            enabled: root.model && root.model.count > 0
            onClicked: Actions.clearPlaylist()
        }
    }

    // --------------------------------------------------------------- list --
    ListView {
        id: list
        anchors.top: toolbar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spaceSm
        clip: true
        model: root.model
        spacing: 1
        visible: root.model && root.model.count > 0
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 6
        }

        delegate: ListRow {
            id: row
            required property int index
            required property string title
            required property int duration
            required property bool isCurrent
            required property bool isAudio

            width: ListView.view.width
            selected: root.isSelected(index)
            current: isCurrent

            onClicked: function(mouse) {
                if (mouse.modifiers & Qt.ControlModifier) root.toggleSelection(index);
                else if (mouse.modifiers & Qt.ShiftModifier) root.selectRange(index);
                else root.selectOnly(index);
            }
            onDoubleClicked: Actions.playIndex(index)

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: Theme.spaceSm

                Text {
                    width: 22
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.index + 1
                    horizontalAlignment: Text.AlignRight
                    font.family: Theme.fontFamilyMono
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.isAudio ? Glyphs.music : Glyphs.video
                    font.pixelSize: 13
                    color: row.current ? Theme.accent : Theme.textFaint
                }
                Text {
                    width: parent.width - 22 - 13 - durationLabel.width - Theme.spaceSm * 4
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.title
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: row.current ? Theme.accent : Theme.text
                }
                Text {
                    id: durationLabel
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.duration > 0 ? root.formatDuration(row.duration) : "\u2013"
                    font.family: Theme.fontFamilyMono
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }
            }
        }
    }

    function formatDuration(ms) {
        var total = Math.floor(ms / 1000);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = (h > 0 && m < 10 ? "0" : "") + m;
        var ss = (s < 10 ? "0" : "") + s;
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }

    // -------------------------------------------------------- empty state --
    // A prompt, not a second button: it calls the same action the toolbar does.
    Column {
        anchors.centerIn: parent
        width: parent.width - Theme.spaceXl * 2
        spacing: Theme.spaceMd
        visible: !root.model || root.model.count === 0

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Glyphs.playlist
            font.pixelSize: 34
            color: Theme.textFaint
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Nothing queued yet.\nDrop files anywhere, or add them below."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
            lineHeight: 1.35
        }
        TextButton {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Add files"
            glyph: Glyphs.addFile
            onClicked: Actions.addFiles()      // same action, not a copy
        }
    }
}
