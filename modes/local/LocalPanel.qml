import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Local's left panel — §P1.5.
//
// The toolbar here is THE ONLY PLACE these four actions exist (§4.1): Add Files,
// Add Folder, Clear Selected, Clear Playlist. There is no menu bar copy, no
// empty-stage button, no transport-bar duplicate. The empty state below and
// Ctrl+O both invoke the same Actions.addFiles() entry point.
Item {
    id: root

    property var model: typeof LocalPlaylist !== "undefined" ? LocalPlaylist : null
    // The source playlist owns the rows and playback state. The proxy is only
    // the view shown here, so filtering never changes the row passed to Actions.
    readonly property var viewModel: root.model ? root.model.filteredModel : null
    property var selection: []
    property int selectionAnchorView: -1

    function isSelected(sourceRow) { return selection.indexOf(sourceRow) >= 0 }

    function selectOnly(sourceRow, viewRow) {
        selection = [sourceRow];
        selectionAnchorView = viewRow;
    }

    function toggleSelection(sourceRow, viewRow) {
        var next = selection.slice();
        var at = next.indexOf(sourceRow);
        if (at >= 0) next.splice(at, 1); else next.push(sourceRow);
        selection = next;
        selectionAnchorView = viewRow;
    }

    function selectRange(viewRow) {
        if (!viewModel || viewModel.count <= 0)
            return;
        var sourceRow = viewModel.sourceRowAt(viewRow);
        if (sourceRow < 0)
            return;
        if (selectionAnchorView < 0 || selection.length === 0) {
            selectOnly(sourceRow, viewRow);
            return;
        }
        var lo = Math.min(selectionAnchorView, viewRow);
        var hi = Math.max(selectionAnchorView, viewRow);
        var next = [];
        for (var i = lo; i <= hi; i++) {
            var row = viewModel.sourceRowAt(i);
            if (row >= 0) next.push(row);
        }
        selection = next;
    }

    // ------------------------------------------------------------ toolbar --
    PanelToolbar {
        id: toolbar
        width: parent.width
        anchors.top: parent.top

        IconButton {
            glyph: Glyphs.openFile
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
            enabled: root.selection.length > 0
            onClicked: {
                Actions.clearSelected();
                root.selection = [];
                root.selectionAnchorView = -1;
            }
        }
        IconButton {
            glyph: Glyphs.clearAll
            tooltip: "Clear playlist"
            enabled: root.model && root.model.count > 0
            onClicked: Actions.clearPlaylist()
        }
    }

    // --------------------------------------------------------------- filter --
    GlassField {
        id: filterField
        anchors.top: toolbar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Theme.spaceSm
        placeholderText: "Filter local media…"
        clearable: true
        clearTooltip: "Clear filter"
        enabled: root.model && root.model.count > 0
        onTextChanged: filterDebounce.restart()
    }

    Timer {
        id: filterDebounce
        interval: 200
        repeat: false
        onTriggered: if (root.viewModel) root.viewModel.setFilter(filterField.text)
    }

    // --------------------------------------------------------------- list --
    ListView {
        id: list
        anchors.top: filterField.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spaceSm
        clip: true
        model: root.viewModel
        spacing: 1
        visible: root.viewModel && root.viewModel.count > 0
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 6
        }

        delegate: ListRow {
            id: row
            required property int index
            required property int sourceIndex
            required property string title
            required property int duration
            required property bool isCurrent
            required property bool isAudio

            width: ListView.view.width
            selected: root.isSelected(sourceIndex)
            current: isCurrent

            onClicked: function(mouse) {
                if (mouse.modifiers & Qt.ControlModifier)
                    root.toggleSelection(sourceIndex, index);
                else if (mouse.modifiers & Qt.ShiftModifier)
                    root.selectRange(index);
                else
                    root.selectOnly(sourceIndex, index);
            }
            onDoubleClicked: Actions.playIndex(sourceIndex)

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: Theme.spaceSm

                Text {
                    width: 22
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.sourceIndex + 1
                    horizontalAlignment: Text.AlignRight
                    font.family: Theme.fontFamilyMono
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.isAudio ? Glyphs.music : Glyphs.video
                    font.family: Theme.fontFamilyIcons
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

    // A non-empty source queue can still have no visible rows while filtering.
    Item {
        anchors.top: filterField.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: root.model && root.model.count > 0
                 && root.viewModel && root.viewModel.count === 0

        Column {
            anchors.centerIn: parent
            width: parent.width - Theme.spaceXl * 2
            spacing: Theme.spaceMd

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Glyphs.search
                font.family: Theme.fontFamilyIcons
                font.pixelSize: 30
                color: Theme.textFaint
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: "No local media match this filter."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textFaint
            }
        }
    }

    function revealPlaying() {
        if (viewModel && viewModel.currentIndex >= 0)
            list.positionViewAtIndex(viewModel.currentIndex, ListView.Contain);
    }

    Connections {
        target: root.viewModel
        function onCurrentIndexChanged() {
            Qt.callLater(root.revealPlaying);
        }
    }

    Component.onCompleted: Qt.callLater(root.revealPlaying)

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
            font.family: Theme.fontFamilyIcons
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
        IconButton {
            anchors.horizontalCenter: parent.horizontalCenter
            glyph: Glyphs.openFile
            tooltip: "Add files (Ctrl+O)"
            onClicked: Actions.addFiles()
        }
    }
}
