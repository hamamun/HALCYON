import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import Halcyon.Ui

// The Playlists manager — §P2.4, owner decision 2026-08-02.
//
// ONE dialog, ONE home (§4.1) for every way a source enters M3U: add a stream
// URL, add a saved .m3u/.m3u8 file, edit, delete — up to seven saved sources.
// Clicking a row loads it (and stops the current stream, per the same owner
// decision). At seven, the Add buttons disable with the hint "Remove one to
// add another" — never a silent cap.
Dialog {
    id: root

    property var ctx: null
    property string errorText: ""

    anchors.centerIn: Overlay.overlay
    modal: true
    padding: Theme.spaceXl
    closePolicy: Popup.CloseOnEscape
    implicitWidth: 540
    implicitHeight: 520

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    onOpened: {
        root.errorText = "";
        sourceList.currentIndex = -1;
    }

    header: Item {
        implicitHeight: 40
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: Theme.spaceXl
            text: "Playlists"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.weightBold
            color: Theme.text
        }
        Text {
            id: countLabel
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: closeBtn.left
            anchors.rightMargin: Theme.spaceSm
            text: root.ctx ? sourceList.count + " / " + root.ctx.sourcesMaxCount : ""
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
        IconButton {
            id: closeBtn
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceSm
            anchors.verticalCenter: parent.verticalCenter
            glyph: Glyphs.close
            tooltip: "Close"
            onClicked: root.close()
        }
    }

    contentItem: Item {
        implicitHeight: 340

        // ---------------------------------------------------- source list --
        ListView {
            id: sourceList
            anchors.fill: parent
            clip: true
            spacing: 2
            model: root.ctx ? root.ctx.sources : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                width: 6
            }

            delegate: ListRow {
                id: sourceRow
                required property int index
                required property var modelData

                width: ListView.view.width
                height: 48
                selected: sourceList.currentIndex === index

                onClicked: sourceList.currentIndex = index
                // Clicking a row twice feels like "open it" — and so does a
                // single double-click. Both load; both stop the stream (§P2.4).
                onDoubleClicked: {
                    root.ctx.loadSource(modelData.id);
                    root.close();
                }

                RowLayout {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4
                    spacing: Theme.spaceMd

                    Text {
                        Layout.alignment: Qt.AlignVCenter
                        text: sourceRow.modelData.kind === "url" ? Glyphs.globe : Glyphs.playlist
                        font.family: Theme.fontFamilyIcons
                        font.pixelSize: 15
                        color: Theme.textMuted
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: 2

                        Text {
                            Layout.fillWidth: true
                            text: sourceRow.modelData.name
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.weight: Theme.weightMedium
                            color: Theme.text
                        }
                        Text {
                            Layout.fillWidth: true
                            text: sourceRow.modelData.location
                            elide: Text.ElideMiddle
                            font.family: Theme.fontFamilyMono
                            font.pixelSize: Theme.fontSizeTiny
                            color: Theme.textFaint
                        }
                    }
                    // Per-row actions reuse the same verbs as the footer —
                    // Edit and Delete are one implementation each (§4.1); the
                    // footer buttons call the same two functions below.
                    // Always reserve space so the URL text never covers them.
                    Row {
                        Layout.alignment: Qt.AlignVCenter
                        spacing: Theme.spaceXs

                        IconButton {
                            glyph: Glyphs.settings
                            tooltip: "Edit"
                            onClicked: root.editSource(sourceRow.modelData)
                        }
                        IconButton {
                            glyph: Glyphs.close
                            tooltip: "Delete"
                            onClicked: root.askDelete(sourceRow.modelData)
                        }
                    }
                }
            }
        }

        // Empty store: the first-run state — one prompt that starts the same
        // Add URL flow, not a second implementation of it (§4.1).
        Column {
            anchors.centerIn: parent
            width: parent.width - Theme.spaceXl * 2
            spacing: Theme.spaceMd
            visible: sourceList.count === 0

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Glyphs.playlist
                font.family: Theme.fontFamilyIcons
                font.pixelSize: 30
                color: Theme.textFaint
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: "No playlists saved yet.\nAdd a stream URL or a saved .m3u file."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textFaint
                lineHeight: 1.35
            }
            TextButton {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Add URL…"
                glyph: Glyphs.globe
                onClicked: addUrlDialog.open()
            }
        }
    }

    footer: Item {
        implicitHeight: 64

        // The cap hint — visible exactly when the cap is what stops you (§P2.4).
        Text {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            visible: root.ctx && root.ctx.sourcesFull
            text: "Seven saved — remove one to add another."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spaceSm

            TextButton {
                text: "Add URL…"
                glyph: Glyphs.globe
                enabled: root.ctx && !root.ctx.sourcesFull
                onClicked: addUrlDialog.open()
            }
            TextButton {
                text: "Add File…"
                glyph: Glyphs.openFile
                enabled: root.ctx && !root.ctx.sourcesFull
                onClicked: fileDialog.open()
            }
            TextButton {
                // Row-level Edit exists; this is for keyboard-first users who
                // select a row — same function, not a copy (§4.1).
                text: "Load"
                primary: true
                enabled: sourceList.currentIndex >= 0
                onClicked: {
                    var entry = sourceList.model[sourceList.currentIndex];
                    if (entry) { root.ctx.loadSource(entry.id); root.close(); }
                }
            }
        }
    }

    // Shared edit/delete verbs — row buttons and any future trigger bind here.
    function editSource(entry) {
        editDialog.entry = entry;
        editDialog.open();
    }
    function askDelete(entry) {
        deleteDialog.entry = entry;
        deleteDialog.open();
    }

    // ------------------------------------------------------------ add URL --
    Dialog {
        id: addUrlDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: Theme.spaceXl
        closePolicy: Popup.CloseOnEscape
        implicitWidth: 420
        title: "Add stream URL"

        background: Rectangle {
            radius: Theme.radiusPanel
            color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
            border.width: 1
            border.color: Theme.glassBorder
        }

        contentItem: Column {
            spacing: Theme.spaceMd

            GlassField {
                id: urlNameField
                width: parent.width
                placeholderText: "Name (e.g. UK Sports)"
            }
            GlassField {
                id: urlField
                width: parent.width
                placeholderText: "https://…/playlist.m3u8"
                onAccepted: addUrlDialog.save()
            }
            Text {
                width: parent.width
                visible: root.errorText.length > 0
                text: root.errorText
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.danger
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.spaceSm

                TextButton { text: "Cancel"; onClicked: addUrlDialog.close() }
                TextButton { text: "Add"; primary: true; onClicked: addUrlDialog.save() }
            }
        }

        function save() {
            var problem = root.ctx.addSource(urlNameField.text, urlField.text, "url");
            if (problem.length > 0) { root.errorText = problem; return; }
            urlNameField.text = ""; urlField.text = ""; root.errorText = "";
            addUrlDialog.close();
        }
        onOpened: { root.errorText = ""; urlNameField.forceActiveFocus() }
    }

    // ------------------------------------------------------------ add file --
    FileDialog {
        id: fileDialog
        title: "Choose a playlist"
        nameFilters: ["Playlists (*.m3u *.m3u8)", "All files (*)"]
        onAccepted: {
            var problem = root.ctx.addSource("", selectedFile.toString(), "file");
            if (problem.length > 0) {
                root.errorText = problem;
                fileErrorDialog.open();
            }
        }
    }

    Dialog {
        id: fileErrorDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: Theme.spaceXl
        title: "Could not add file"

        background: Rectangle {
            radius: Theme.radiusPanel
            color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
            border.width: 1
            border.color: Theme.glassBorder
        }
        contentItem: Text {
            width: 320
            text: root.errorText
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            color: Theme.textMuted
        }
        footer: Row {
            spacing: Theme.spaceSm
            TextButton { text: "OK"; primary: true; onClicked: fileErrorDialog.close() }
        }
    }

    // ---------------------------------------------------------------- edit --
    Dialog {
        id: editDialog

        property var entry: null

        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: Theme.spaceXl
        closePolicy: Popup.CloseOnEscape
        implicitWidth: 420
        title: "Edit playlist"

        background: Rectangle {
            radius: Theme.radiusPanel
            color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
            border.width: 1
            border.color: Theme.glassBorder
        }

        contentItem: Column {
            spacing: Theme.spaceMd

            GlassField {
                id: editNameField
                width: parent.width
                placeholderText: "Name"
            }
            GlassField {
                id: editLocationField
                width: parent.width
                placeholderText: "URL or file path"
                onAccepted: editDialog.save()
            }
            Text {
                width: parent.width
                visible: root.errorText.length > 0
                text: root.errorText
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.danger
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.spaceSm

                TextButton { text: "Cancel"; onClicked: editDialog.close() }
                TextButton { text: "Save"; primary: true; onClicked: editDialog.save() }
            }
        }

        function save() {
            if (!entry) { editDialog.close(); return; }
            var ok = root.ctx.updateSource(entry.id, editNameField.text,
                                           editLocationField.text);
            if (!ok) { root.errorText = "Could not save — was this entry removed?"; return; }
            root.errorText = "";
            editDialog.close();
        }
        onOpened: {
            root.errorText = "";
            editNameField.text = entry ? entry.name : "";
            editLocationField.text = entry ? entry.location : "";
            editNameField.forceActiveFocus();
        }
    }

    // -------------------------------------------------------------- delete --
    ConfirmDialog {
        id: deleteDialog

        property var entry: null

        title: "Delete playlist"
        message: entry ? "Remove “" + entry.name + "” from your saved playlists?"
                       : ""
        onConfirmed: if (entry) root.ctx.removeSource(entry.id)
    }
}
