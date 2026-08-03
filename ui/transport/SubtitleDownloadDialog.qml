import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic
import Halcyon.Ui

// Shared transport part — §B.4/§P1.5. The subtitle download flyout.
//
// Opened from the subtitle popover's download button. Behaviour lives in
// core/subtitles.py (QML context property Subs); this file is layout and
// state, in the same glass as every other panel.
//
//   ┌──────────────────────────────────────────┐
//   │ Download subtitles                     ✕ │
//   │ ⚙ API key & languages              ▼/▲   │   one collapsible home for
//   │   **********************  👁              │   the two things you set
//   │   [en] [bn] [ar] …                       │   once and forget
//   │ ──────────────────────────────────────── │
//   │ Movie.Name.2024.1080p            🔍      │
//   │ Best matches                             │
//   │   rel name · EN · 12,340 ↓ · HD    ⬇     │  (max 3)
//   │ More results                             │
//   │   …scrollable, each with ⬇               │
//   └──────────────────────────────────────────┘
//
// The API key and language picks persist via Settings and survive restarts;
// the collapse state does too, so a configured user never sees the panel.
Popover {
    id: root

    // 0 = natural height; the transport bar passes a window-derived cap.
    property real maxHeight: 0

    // The backend. Guarded so the component still instantiates where main.py
    // never ran (tools, focused QML tests).
    readonly property var subs: (typeof Subs !== "undefined") ? Subs : null

    // Show OSD when download status changes
    Connections {
        target: subs
        function onStatusChanged() {
            if (subs && subs.status.length > 0) {
                var glyph = subs.statusIsError ? Glyphs.volumeMute : Glyphs.download;
                Actions.osd(subs.status, glyph);
            }
        }
    }

    // Session state — deliberate choices about what persists:
    //   settingsExpanded, apiKey, languages → Settings (once, forever);
    //   query, keyVisible, searched           → die with the window.
    property bool settingsExpanded: false
    property bool keyVisible: false
    property string queryText: ""
    property bool searched: false

    implicitWidth: 404

    Component.onCompleted: {
        root.settingsExpanded = Settings.get("subs.downloadBoxExpanded", false);
    }
    onSettingsExpandedChanged: {
        Settings.set("subs.downloadBoxExpanded", root.settingsExpanded);
    }

    onOpened: {
        if (root.queryText.trim() === "" && root.subs && root.subs.mediaName !== "")
            root.queryText = root.subs.mediaName;
        queryField.forceActiveFocus();
    }

    function doSearch() {
        if (!root.subs || root.queryText.trim() === "" || root.subs.searching)
            return;
        root.searched = true;
        root.subs.search(root.queryText.trim());
    }

    function toggleLanguage(code) {
        if (!root.subs)
            return;
        var langs = root.subs.languages.slice();
        var at = langs.indexOf(code);
        if (at === -1)
            langs.push(code);
        else
            langs.splice(at, 1);
        root.subs.languages = langs;
    }

    function languageSelected(code) {
        return !!root.subs && root.subs.languages.indexOf(code) !== -1;
    }

    function formatCount(n) {
        return Number(n || 0).toLocaleString();
    }

    // The languages offered as chips. Codes are ISO 639-1, what the REST API
    // expects; the order nearby speakers actually reach for first.
    readonly property var languageCatalog: [
        { code: "en", label: "English" },
        { code: "bn", label: "বাংলা" },
        { code: "hi", label: "हिन्दी" },
        { code: "ur", label: "اردو" },
        { code: "ar", label: "العربية" },
        { code: "fa", label: "فارسی" },
        { code: "tr", label: "Türkçe" },
        { code: "es", label: "Español" },
        { code: "fr", label: "Français" },
        { code: "de", label: "Deutsch" },
        { code: "pt", label: "Português" },
        { code: "ru", label: "Русский" },
        { code: "id", label: "Indonesia" },
        { code: "ja", label: "日本語" },
        { code: "ko", label: "한국어" },
        { code: "zh", label: "中文" }
    ]

    // One row implementation for both result sections (§4.1) — a Repeater in
    // Best matches and the ListView in More results both delegate to this.
    //
    // The download button is a *sibling* of the ListRow rather than a child of
    // its content. ListRow's own MouseArea stacks beneath the content slot
    // (see ListRow.qml), so a nested button would work too — but keeping the
    // button at the same level as the row keeps the row reusable as pure
    // background + selection and makes the hit areas explicit: one interactive
    // rectangle per row, no overlap.
    Component {
        id: resultRow

        Item {
            id: rowWrap
            required property var modelData
            width: ListView.view ? ListView.view.width : (parent ? parent.width : 0)
            height: 40

            ListRow {
                id: rowBg
                anchors.fill: parent

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    // Leave room for the download button that sits over the
                    // row's right edge (30 px button + a small breathing gap).
                    anchors.right: parent.right
                    anchors.rightMargin: 40
                    spacing: 1

                    Text {
                        width: parent.width
                        text: rowWrap.modelData.name
                        elide: Text.ElideMiddle
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.text
                    }
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: rowWrap.modelData.lang.toUpperCase()
                            + "  ·  " + root.formatCount(rowWrap.modelData.downloads) + " downloads"
                            + (rowWrap.modelData.hd ? "  ·  HD" : "")
                            + (rowWrap.modelData.trusted ? "  ·  trusted" : "")
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.textFaint
                    }
                }
            }

            IconButton {
                id: downloadButton
                anchors.right: parent.right
                anchors.rightMargin: Theme.spaceXs
                anchors.verticalCenter: parent.verticalCenter
                z: 1
                glyph: Glyphs.download
                iconSize: 15
                implicitWidth: 30
                implicitHeight: 30
                tooltip: "Download and load"
                active: root.subs ? root.subs.busyIndex === rowWrap.modelData.idx : false
                enabled: root.subs ? root.subs.busyIndex === -1 : false
                onClicked: {
                    if (root.subs) root.subs.download(rowWrap.modelData.idx)
                }
            }
        }
    }

    contentItem: Flickable {
        id: flick

        implicitWidth: root.implicitWidth - root.leftPadding - root.rightPadding
        implicitHeight: root.maxHeight > 0
                        ? Math.min(column.implicitHeight,
                                   root.maxHeight - root.topPadding - root.bottomPadding)
                        : column.implicitHeight

        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        interactive: contentHeight > height + 1
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: column
            width: flick.width - (dialogScroll.visible ? 12 : 0)
            spacing: Theme.spaceMd

            // -------------------------------------------------- header --
            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: "Download subtitles"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                    font.weight: Theme.weightBold
                    color: Theme.text
                    Layout.fillWidth: true
                }
                IconButton {
                    glyph: Glyphs.close
                    iconSize: 13
                    implicitWidth: 28
                    implicitHeight: 28
                    tooltip: "Close"
                    onClicked: root.close()
                }
            }

            // ------------------------- settings: API key & languages --
            // One collapsible group for the set-once items (§P1.5).
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 30
                    radius: Theme.radiusSmall
                    color: groupHover.containsMouse ? Theme.glassFill : "transparent"

                    Behavior on color {
                        ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spaceMd
                        spacing: Theme.spaceSm

                        Text {
                            text: "API key & languages"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.weight: Theme.weightBold
                            color: Theme.textMuted
                            Layout.fillWidth: true
                        }
                        Text {
                            text: root.settingsExpanded ? Glyphs.chevronUp : Glyphs.chevronDown
                            font.family: Theme.fontFamilyIcons
                            font.pixelSize: 12
                            color: Theme.textFaint
                        }
                    }

                    MouseArea {
                        id: groupHover
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.settingsExpanded = !root.settingsExpanded
                    }
                }

                // -------- the collapsible body --------
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: root.settingsExpanded
                    spacing: Theme.spaceSm

                    Text {
                        text: "OpenSubtitles API key"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        font.weight: Theme.weightBold
                        color: Theme.textFaint
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spaceXs

                        GlassField {
                            Layout.fillWidth: true
                            text: root.subs ? root.subs.apiKey : ""
                            enabled: root.subs !== null
                            echoMode: root.keyVisible ? TextInput.Normal : TextInput.Password
                            placeholderText: "Paste your API key"
                            onTextEdited: if (root.subs) root.subs.apiKey = text
                        }
                        IconButton {
                            glyph: root.keyVisible ? Glyphs.eyeHide : Glyphs.eyeShow
                            iconSize: 13
                            implicitWidth: 28
                            implicitHeight: 28
                            tooltip: root.keyVisible ? "Hide key" : "Show key"
                            onClicked: root.keyVisible = !root.keyVisible
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Free key at opensubtitles.com → your profile → API consumers"
                        wrapMode: Text.WordWrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.textFaint
                    }

                    Text {
                        text: "Preferred languages"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        font.weight: Theme.weightBold
                        color: Theme.textFaint
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.spaceXs

                        Repeater {
                            model: root.languageCatalog
                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool chosen: root.languageSelected(modelData.code)

                                implicitWidth: chipText.implicitWidth + Theme.spaceMd * 2
                                implicitHeight: 24
                                radius: Theme.radiusPill
                                color: chosen ? Theme.accentDim
                                     : chipMouse.containsMouse ? Theme.glassFillHover
                                     : Theme.glassFill
                                border.width: 1
                                border.color: chosen ? Theme.accent : Theme.glassBorder

                                Behavior on color {
                                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                                }

                                Text {
                                    id: chipText
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeTiny
                                    color: parent.chosen ? Theme.accent : Theme.textMuted
                                }

                                MouseArea {
                                    id: chipMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.toggleLanguage(modelData.code)
                                }
                            }
                        }
                    }
                }

            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.glassBorder }

            // ------------------------------------------------ search row --
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceXs

                GlassField {
                    id: queryField
                    Layout.fillWidth: true
                    text: root.queryText
                    placeholderText: "Movie or series name"
                    onTextEdited: root.queryText = text
                    onAccepted: root.doSearch()
                }
                IconButton {
                    glyph: Glyphs.search
                    iconSize: 16
                    implicitWidth: 36
                    implicitHeight: 36
                    tooltip: "Search OpenSubtitles"
                    active: root.subs ? root.subs.searching : false
                    enabled: root.subs !== null && root.queryText.trim().length > 0
                             && !root.subs.searching
                    onClicked: root.doSearch()
                }
            }

            // -------------------------------------------------- status --
            Text {
                Layout.fillWidth: true
                visible: root.subs !== null && root.subs.status.length > 0
                text: root.subs ? root.subs.status : ""
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                color: root.subs && root.subs.statusIsError ? Theme.warning : Theme.textFaint
            }

            // -------------------------------------------- best matches --
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.subs !== null && root.subs.bestResults.length > 0
                spacing: Theme.spaceXs

                Text {
                    text: "Best matches"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    font.weight: Theme.weightBold
                    color: Theme.textFaint
                }
                // At most three by construction (core/subtitles._rank_and_split),
                // so a plain column — no scrolling inside the top picks.
                Column {
                    Layout.fillWidth: true
                    spacing: Theme.spaceXs

                    Repeater {
                        model: root.subs ? root.subs.bestResults : []
                        delegate: resultRow
                    }
                }
            }

            // -------------------------------------------- more results --
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.subs !== null && root.subs.otherResults.length > 0
                spacing: Theme.spaceXs

                Text {
                    text: "More results"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    font.weight: Theme.weightBold
                    color: Theme.textFaint
                }
                Item {
                    Layout.fillWidth: true
                    readonly property int visibleRows: Math.min(5, moreList.count)
                    implicitHeight: visibleRows * 40 + Math.max(0, visibleRows - 1) * Theme.spaceXs

                    ListView {
                        id: moreList
                        anchors.fill: parent
                        anchors.rightMargin: needsScroll ? 12 : 0
                        readonly property bool needsScroll: count > 5

                        model: root.subs ? root.subs.otherResults : []
                        delegate: resultRow
                        spacing: Theme.spaceXs
                        clip: true
                        interactive: needsScroll
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ThinScrollBar { }
                    }
                }
            }

            // ------------------------------------------- initial hint --
            Text {
                Layout.fillWidth: true
                visible: !root.searched && root.subs !== null && root.subs.status.length === 0
                         && root.subs.bestResults.length === 0
                text: "Search by the file's name. Best matches prefer your languages."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.textFaint
            }
        }

        ScrollBar.vertical: ThinScrollBar { id: dialogScroll }
    }
}
