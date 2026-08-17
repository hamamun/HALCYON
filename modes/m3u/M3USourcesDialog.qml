import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import Halcyon.Ui

// The Playlists manager — §P2.4, owner decision 2026-08-02.
//
// ONE dialog, ONE home (§4.1) for every way a source enters M3U: add a stream
// URL, add a saved .m3u/.m3u8/.pls file, edit, delete — up to seven saved sources.
// Clicking a row loads it (and stops the current stream, per the same owner
// decision). At seven, the Add buttons disable with the hint "Remove one to
// add another" — never a silent cap.
Dialog {
    id: root

    property var ctx: null
    property string errorText: ""
    property string infoText: ""
    title: "Playlists"

    anchors.centerIn: Overlay.overlay
    modal: true
    padding: Theme.spaceXl
    closePolicy: Popup.CloseOnEscape
    implicitWidth: 540
    implicitHeight: 520

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(Theme.baseElevated.r, Theme.baseElevated.g, Theme.baseElevated.b, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    onOpened: {
        root.errorText = "";
        sourceList.currentIndex = -1;
    }

    contentItem: Item {
        implicitHeight: 340

        Rectangle {
            id: infoBanner
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: visible ? 56 : 0
            visible: root.infoText.length > 0
            radius: Theme.radiusSmall
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.10)
            border.width: 1
            border.color: Theme.accentDim

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.spaceSm
                spacing: Theme.spaceSm

                Text {
                    Layout.alignment: Qt.AlignVCenter
                    text: Glyphs.bookmark
                    font.family: Theme.fontFamilyIcons
                    font.pixelSize: 16
                    color: Theme.accent
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 1

                    Text {
                        Layout.fillWidth: true
                        text: root.infoText
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.weight: Theme.weightMedium
                        color: Theme.text
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: root.errorText.length > 0
                                 || (root.ctx && root.ctx.canSaveCurrentSource)
                        text: root.errorText.length > 0
                              ? root.errorText
                              : "After saving, click the bookmark again."
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: root.errorText.length > 0 ? Theme.danger : Theme.textFaint
                    }
                }
                IconButton {
                    Layout.alignment: Qt.AlignVCenter
                    visible: root.ctx && root.ctx.canSaveCurrentSource
                    glyph: Glyphs.save
                    tooltip: "Save current"
                    onClicked: root.saveCurrentForFavourites()
                }
            }
        }

        Text {
            id: countLabel
            anchors.top: infoBanner.bottom
            anchors.topMargin: infoBanner.visible ? Theme.spaceSm : 0
            anchors.right: parent.right
            text: root.ctx ? sourceList.count + " / " + root.ctx.sourcesMaxCount : ""
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }

        // ---------------------------------------------------- source list --
        ListView {
            id: sourceList
            anchors.top: countLabel.bottom
            anchors.topMargin: Theme.spaceXs
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            clip: true
            spacing: 2
            model: root.ctx ? root.ctx.sources : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ThinScrollBar { }

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
                            glyph: Glyphs.edit
                            tooltip: "Edit playlist"
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
            anchors.centerIn: sourceList
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
                text: "No playlists saved yet.\nAdd a stream URL or a saved .m3u/.m3u8/.pls file."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textFaint
                lineHeight: 1.35
            }
            IconButton {
                anchors.horizontalCenter: parent.horizontalCenter
                glyph: Glyphs.link
                tooltip: "Add URL…"
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

            IconButton {
                glyph: Glyphs.link
                tooltip: "Add URL…"
                enabled: root.ctx && !root.ctx.sourcesFull
                onClicked: addUrlDialog.open()
            }
            IconButton {
                glyph: Glyphs.openFile
                tooltip: "Add File…"
                enabled: root.ctx && !root.ctx.sourcesFull
                onClicked: fileDialog.open()
            }
            IconButton {
                // A selected row reaches the same load function as a
                // double-click (§4.1), now through the shared icon vocabulary.
                glyph: Glyphs.load
                tooltip: "Load playlist"
                enabled: sourceList.currentIndex >= 0
                onClicked: {
                    var entry = sourceList.model[sourceList.currentIndex];
                    if (entry) { root.ctx.loadSource(entry.id); root.close(); }
                }
            }
            IconButton {
                glyph: Glyphs.close
                tooltip: "Close"
                onClicked: root.close()
            }
        }
    }

    // Open helpers: normal open clears hints; favourite flow keeps an info banner.
    function openNormal() {
        root.infoText = "";
        root.open();
    }
    function openForFavourites(message) {
        root.errorText = "";
        root.infoText = message;
        root.open();
    }
    function saveCurrentForFavourites() {
        if (!root.ctx)
            return;
        var problem = root.ctx.saveCurrentSourceForFavourites();
        if (problem.length > 0) {
            root.errorText = problem;
            return;
        }
        root.errorText = "";
        root.infoText = "";
        root.close();
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
            color: Qt.rgba(Theme.baseElevated.r, Theme.baseElevated.g, Theme.baseElevated.b, 0.98)
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

                IconButton { glyph: Glyphs.cancel; tooltip: "Cancel"; onClicked: addUrlDialog.close() }
                IconButton { glyph: Glyphs.save; tooltip: "Add URL"; onClicked: addUrlDialog.save() }
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
        nameFilters: ["Playlists (*.m3u *.m3u8 *.pls)", "All files (*)"]
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
            color: Qt.rgba(Theme.baseElevated.r, Theme.baseElevated.g, Theme.baseElevated.b, 0.98)
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
            IconButton { glyph: Glyphs.close; tooltip: "OK"; onClicked: fileErrorDialog.close() }
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
            color: Qt.rgba(Theme.baseElevated.r, Theme.baseElevated.g, Theme.baseElevated.b, 0.98)
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

                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: editDialog.close()
                }
                IconButton {
                    glyph: Glyphs.save
                    tooltip: "Save playlist"
                    onClicked: editDialog.save()
                }
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
        confirmText: "Delete"
        confirmGlyph: Glyphs.deleteItem
        message: entry ? "Remove “" + entry.name + "” from your saved playlists?"
                       : ""
        onConfirmed: if (entry) root.ctx.removeSource(entry.id)
    }
}
