import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui
import Halcyon.Panels

// Settings — the one home, behind the title-bar gear (§P1.4).
// Tabbed layout: General | Shortcuts | Update (§U).
//
// A .qml file has exactly ONE root element, so the tab pages live inside
// the Dialog as inline components (Qt 5.15+ / Qt 6 `component` syntax).
// Declaring them as separate top-level Items is a syntax error at load time.
Dialog {
    id: root

    anchors.centerIn: Overlay.overlay
    width: 560
    height: 600
    modal: true
    padding: 0
    title: "Settings"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    // Current tab state
    property int currentTab: 0

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    // -----------------------------------------------------------------------
    // General Settings page (inline component — see note above)
    // -----------------------------------------------------------------------
    component GeneralSettingsContent: Item {
        ScrollView {
            id: generalScroll
            anchors.fill: parent
            anchors.margins: Theme.spaceMd
            anchors.bottomMargin: 0
            clip: true
            // Same latent width-collapse trap as the Shortcuts tab — pin it
            // instead of relying on the accidental implicit width of the texts.
            contentWidth: width
            ScrollBar.vertical: ThinScrollBar { id: generalScrollBar; enabled: generalScroll.contentHeight > generalScroll.height }

            Column {
                id: generalColumn
                spacing: Theme.spaceLg
                width: parent.width
                anchors.horizontalCenter: parent.horizontalCenter

                SettingRow {
                    width: parent.width
                    label: "Turbo Mode"
                    description: "Hardware decoding for 4K. The transport bar docks below "
                               + "the video instead of floating over it."
                    checked: Settings.get("playback.turboMode", false)
                    onToggled: function(on) { Settings.set("playback.turboMode", on) }
                }

                SettingRow {
                    width: parent.width
                    label: "Resume playback"
                    description: "Offer to continue where you left off."
                    checked: Settings.get("playback.resumeEnabled", true)
                    onToggled: function(on) { Settings.set("playback.resumeEnabled", on) }
                }

                SettingRow {
                    width: parent.width
                    label: "Auto-load subtitles"
                    description: "Load a matching .srt or .ass sitting next to the file."
                    checked: Settings.get("subs.autoLoadSidecar", true)
                    onToggled: function(on) { Settings.set("subs.autoLoadSidecar", on) }
                }

                SettingRow {
                    width: parent.width
                    label: "On-screen display"
                    description: "Volume, seek and track changes shown over the video."
                    checked: Settings.get("ui.osdEnabled", true)
                    onToggled: function(on) { Settings.set("ui.osdEnabled", on) }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

                Row {
                    width: parent.width
                    spacing: Theme.spaceSm

                    Text {
                        width: 120
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Video backend"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeBody
                        color: Theme.text
                    }

                    ComboBox {
                        id: backendCombo
                        width: parent.width - 120 - Theme.spaceSm
                        model: ["auto", "i420", "rv32"]
                        currentIndex: Math.max(0, model.indexOf(Settings.get("video.backend", "auto")))
                        onActivated: Settings.set("video.backend", model[currentIndex])

                        palette.text: Theme.text
                        palette.windowText: Theme.text
                        palette.base: Theme.baseElevated
                        palette.window: Theme.baseElevated
                        palette.highlight: Theme.accentDim
                        palette.highlightedText: Theme.accent
                        palette.button: Theme.baseElevated
                        palette.buttonText: Theme.text

                        background: Rectangle {
                            radius: Theme.radiusSmall
                            color: Theme.glassFill
                            border.width: 1
                            border.color: Theme.glassBorder
                        }
                        contentItem: Text {
                            leftPadding: Theme.spaceMd
                            rightPadding: Theme.spaceMd
                            text: parent.displayText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.text
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        popup: Popup {
                            id: backendPopup
                            y: backendCombo.height
                            width: backendCombo.width
                            implicitHeight: contentItem.implicitHeight
                            padding: Theme.spaceXs
                            topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0

                            palette.text: Theme.text
                            palette.windowText: Theme.text
                            palette.base: Theme.baseElevated
                            palette.window: Theme.baseElevated
                            palette.highlight: Theme.accentDim
                            palette.highlightedText: Theme.accent

                            contentItem: ListView {
                                id: backendPopupList
                                clip: true
                                implicitHeight: contentHeight
                                model: backendPopup.visible ? backendCombo.delegateModel : null
                                currentIndex: backendCombo.highlightedIndex
                                delegate: ItemDelegate {
                                    id: bd
                                    width: backendPopupList.width
                                    text: modelData
                                    font: backendCombo.font
                                    highlighted: backendCombo.highlightedIndex === index
                                    palette.text: Theme.text
                                    palette.windowText: Theme.text
                                    palette.highlight: Theme.accentDim
                                    palette.highlightedText: Theme.accent
                                    contentItem: Text {
                                        leftPadding: Theme.spaceMd
                                        rightPadding: Theme.spaceMd
                                        text: bd.text
                                        font: bd.font
                                        color: bd.highlighted ? Theme.accent : Theme.text
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    background: Rectangle {
                                        color: bd.highlighted ? Theme.glassFillHover : "transparent"
                                        radius: Theme.radiusSmall
                                    }
                                }
                                ScrollIndicator.vertical: ScrollIndicator {}
                            }

                            background: Rectangle {
                                radius: Theme.radiusSmall
                                color: Theme.baseElevated
                                border.width: 1
                                border.color: Theme.glassBorderStrong
                            }
                        }

                        delegate: ItemDelegate {
                            width: backendCombo.width
                            text: modelData
                            font: backendCombo.font
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: "Backend changes take effect on the next launch."
                    wrapMode: Text.WordWrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }

                Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

                Column {
                    width: parent.width
                    spacing: Theme.spaceMd

                    Text {
                        text: "Mobile Remote"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeBody
                        font.weight: Theme.weightBold
                        color: Theme.text
                    }

                    Image {
                        id: remoteQr
                        width: 160
                        height: 160
                        anchors.horizontalCenter: parent.horizontalCenter
                        source: "http://127.0.0.1:" + Settings.get("remote.port", 8765) + "/qr.png"
                        fillMode: Image.PreserveAspectFit
                        onStatusChanged: {
                            if (remoteQr.status === Image.Error) {
                                remoteQr.source = ""
                                remoteUrlText.text = "Remote server unavailable — install aiohttp and qrcode."
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Scan with your phone camera to control Halcyon, or type the address below."
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.textFaint
                    }

                    Text {
                        id: remoteUrlText
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: (typeof RemoteBridge !== "undefined" && RemoteBridge)
                              ? RemoteBridge.serverUrl : "http://<this-PC-IP>:" + Settings.get("remote.port", 8765)
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.accent
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "Same Wi-Fi only. The remote starts automatically with Halcyon."
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.textFaint
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

                Column {
                    width: parent.width
                    spacing: 2
                    Text {
                        text: "Halcyon v1.0.0 — Every format. One pane of glass."
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.weight: Theme.weightBold
                        color: Theme.text
                    }
                    Text {
                        text: "Personal, non-commercial media player. Powered by libVLC 3.0.21 & Edge WebView2."
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.textFaint
                    }
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Shortcuts page (inline component — see note above)
    // -----------------------------------------------------------------------
    component ShortcutsTabContent: Item {
        id: shortcutsRoot

        // Shortcut data model
        ListModel {
            id: shortcutsModel

            // Global shortcuts
            ListElement { category: "Global"; keys: "Alt + 1 / 2 / 3"; action: "Switch mode (Local / M3U / Web)"; modeContext: "Works everywhere" }
            ListElement { category: "Global"; keys: "Ctrl + 1 / 2 / 3"; action: "Switch mode (Local / M3U / Web)"; modeContext: "Non-Web modes only" }
            ListElement { category: "Global"; keys: "F"; action: "Toggle fullscreen"; modeContext: "Works everywhere" }
            ListElement { category: "Global"; keys: "Escape"; action: "Exit fullscreen / close panels / exit mini mode"; modeContext: "Works everywhere" }
            ListElement { category: "Global"; keys: "Ctrl + L"; action: "Toggle playlist panel"; modeContext: "Local / M3U modes" }
            ListElement { category: "Global"; keys: "Ctrl + I"; action: "Toggle info panel"; modeContext: "Local / M3U modes" }
            ListElement { category: "Global"; keys: "Ctrl + O"; action: "Open file"; modeContext: "Local mode" }

            // Playback shortcuts
            ListElement { category: "Playback"; keys: "Space"; action: "Play / Pause"; modeContext: "" }
            ListElement { category: "Playback"; keys: "←"; action: "Seek back 10 seconds"; modeContext: "" }
            ListElement { category: "Playback"; keys: "→"; action: "Seek forward 10 seconds"; modeContext: "" }
            ListElement { category: "Playback"; keys: "Shift + ←"; action: "Seek back 60 seconds"; modeContext: "" }
            ListElement { category: "Playback"; keys: "Shift + →"; action: "Seek forward 60 seconds"; modeContext: "" }
            ListElement { category: "Playback"; keys: "↑"; action: "Volume up 5%"; modeContext: "" }
            ListElement { category: "Playback"; keys: "↓"; action: "Volume down 5%"; modeContext: "" }
            ListElement { category: "Playback"; keys: "M"; action: "Toggle mute"; modeContext: "" }
            ListElement { category: "Playback"; keys: "N"; action: "Next track"; modeContext: "" }
            ListElement { category: "Playback"; keys: "Shift + N"; action: "Previous track"; modeContext: "" }
            ListElement { category: "Playback"; keys: "P"; action: "Previous track"; modeContext: "Local mode" }
            ListElement { category: "Playback"; keys: "L"; action: "Cycle repeat (off / one / all)"; modeContext: "" }
            ListElement { category: "Playback"; keys: "S"; action: "Cycle subtitles"; modeContext: "" }
            ListElement { category: "Playback"; keys: "A"; action: "Cycle audio tracks"; modeContext: "" }
            ListElement { category: "Playback"; keys: "["; action: "Decrease playback speed"; modeContext: "" }
            ListElement { category: "Playback"; keys: "]"; action: "Increase playback speed"; modeContext: "" }
            ListElement { category: "Playback"; keys: "Delete"; action: "Remove selected from playlist"; modeContext: "Local mode" }

            // Mode-specific shortcuts
            ListElement { category: "Mode-Specific"; keys: "Ctrl + E"; action: "Open equalizer"; modeContext: "Local mode" }
            ListElement { category: "Mode-Specific"; keys: "Ctrl + 1 / 2 / 3"; action: "Switch mode"; modeContext: "Non-Web only (Web uses for tabs)" }
            ListElement { category: "Mode-Specific"; keys: "Alt + 1 / 2 / 3"; action: "Switch mode"; modeContext: "Works even in Web" }

            // Web Browser shortcuts (handled by WebView2)
            ListElement { category: "Web Browser"; keys: "Ctrl + T"; action: "New tab"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Ctrl + W"; action: "Close tab"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Ctrl + Tab"; action: "Next tab"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Ctrl + Shift + Tab"; action: "Previous tab"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Ctrl + 1-9"; action: "Switch to tab 1-9"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Alt + ←"; action: "Go back"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Alt + →"; action: "Go forward"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Ctrl + R"; action: "Refresh page"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "F5"; action: "Refresh page"; modeContext: "Web mode only" }
            ListElement { category: "Web Browser"; keys: "Alt + Home"; action: "Go to homepage"; modeContext: "Web mode only" }

            // System shortcuts
            ListElement { category: "System"; keys: "Title-bar button"; action: "Toggle mini player mode"; modeContext: "Local mode, media loaded" }
        }

        // Categories with their default expanded state. The model is the single
        // source of truth for `expanded` — delegates bind to it and the click
        // handler only writes the role (so nothing fights a broken binding).
        ListModel {
            id: categoriesModel
            ListElement { name: "Global"; expanded: true }
            ListElement { name: "Playback"; expanded: true }
            ListElement { name: "Mode-Specific"; expanded: false }
            ListElement { name: "Web Browser"; expanded: false }
            ListElement { name: "System"; expanded: false }
        }

        // Search query
        property string searchQuery: ""

        // Filtered shortcuts by category
        function getShortcutsForCategory(category) {
            var result = [];
            for (var i = 0; i < shortcutsModel.count; i++) {
                var item = shortcutsModel.get(i);
                if (item.category !== category)
                    continue;

                if (searchQuery.length > 0) {
                    var query = searchQuery.toLowerCase();
                    var keys = item.keys.toLowerCase();
                    var action = item.action.toLowerCase();
                    var context = item.modeContext.toLowerCase();

                    if (keys.indexOf(query) === -1 &&
                        action.indexOf(query) === -1 &&
                        context.indexOf(query) === -1) {
                        continue;
                    }
                }
                result.push(item);
            }
            return result;
        }

        // Header with title and search
        Rectangle {
            id: shortcutsHeader
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 44
            color: "transparent"

            Text {
                id: shortcutsTitle
                anchors.left: parent.left
                anchors.leftMargin: Theme.spaceMd
                anchors.verticalCenter: parent.verticalCenter
                text: "Keyboard Shortcuts"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarge
                font.weight: Theme.weightBold
                color: Theme.text
            }

            // Search field
            Rectangle {
                id: searchContainer
                anchors.right: parent.right
                anchors.rightMargin: Theme.spaceMd
                anchors.verticalCenter: parent.verticalCenter
                width: 160
                height: 30
                radius: Theme.radiusSmall
                color: Theme.glassFill
                border.width: 1
                border.color: searchField.activeFocus ? Theme.accentDim : Theme.glassBorder

                Behavior on border.color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spaceSm
                    anchors.verticalCenter: parent.verticalCenter
                    text: Glyphs.search
                    font.family: Theme.fontFamilyIcons
                    font.pixelSize: 14
                    color: Theme.textMuted
                }

                TextField {
                    id: searchField
                    anchors.fill: parent
                    anchors.leftMargin: 28
                    anchors.rightMargin: 26   // leave room for the clear (×) glyph
                    placeholderText: "Search..."
                    placeholderTextColor: Theme.textFaint
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                    background: Rectangle { color: "transparent" }
                    clip: true
                    onTextChanged: shortcutsRoot.searchQuery = text
                }

                // Clear button — only while there is text to clear
                Text {
                    id: searchClearIcon
                    objectName: "searchClearIcon"
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.spaceSm
                    anchors.verticalCenter: parent.verticalCenter
                    text: Glyphs.cancel
                    font.family: Theme.fontFamilyIcons
                    font.pixelSize: 12
                    color: searchClearMouse.containsMouse ? Theme.text : Theme.textMuted
                    visible: searchField.text.length > 0

                    Behavior on color {
                        ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }

                    MouseArea {
                        id: searchClearMouse
                        anchors.fill: parent
                        anchors.margins: -Theme.spaceXs
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            searchField.clear();
                            searchField.forceActiveFocus();
                        }
                    }
                }
            }
        }

        // Scrollable shortcut list
        ScrollView {
            id: shortcutsScroll
            anchors.top: shortcutsHeader.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.spaceMd
            anchors.bottomMargin: Theme.spaceSm
            clip: true
            // ScrollView auto-derives contentWidth from the child's implicit
            // width. The delegates here are plain Items (implicitWidth 0) plus
            // a 1-px spacer, so the whole list collapses to one pixel wide and
            // the cards render stacked on top of each other. Pin the content
            // width like InfoTab/SubtitleDownloadDialog/TrackPopover already do.
            contentWidth: width
            ScrollBar.vertical: ThinScrollBar { id: shortcutsScrollBar; enabled: shortcutsScroll.contentHeight > shortcutsScroll.height }

            Column {
                id: shortcutsList
                width: parent.width
                spacing: Theme.spaceSm
                anchors.horizontalCenter: parent.horizontalCenter

                // Generate category sections
                Repeater {
                    model: categoriesModel

                    delegate: Item {
                        id: categoryDelegate
                        width: shortcutsList.width
                        // The delegate sits in a Column, so it must size itself;
                        // missing height collapses every section on top of the next.
                        height: categoryHeader.height
                              + (shortcutItems.visible ? Theme.spaceXs + shortcutItems.implicitHeight : 0)

                        property string categoryName: model.name
                        property bool isExpanded: model.expanded
                        property int shortcutCount: shortcutsRoot.getShortcutsForCategory(model.name).length

                        // Category header
                        Rectangle {
                            id: categoryHeader
                            width: parent.width
                            height: 36
                            radius: Theme.radiusSmall
                            color: categoryHeaderMouse.containsMouse ? Theme.glassFillHover : Theme.glassFill

                            Behavior on color {
                                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                            }

                            // Expanded/collapsed indicator
                            Text {
                                id: categoryIndicator
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.spaceMd
                                anchors.verticalCenter: parent.verticalCenter
                                text: categoryDelegate.isExpanded ? Glyphs.chevronDown : "\u203A"
                                font.family: categoryDelegate.isExpanded ? Theme.fontFamilyIcons : Theme.fontFamily
                                font.pixelSize: categoryDelegate.isExpanded ? 12 : 16
                                font.weight: categoryDelegate.isExpanded ? Font.Normal : Font.Bold
                                color: Theme.textMuted
                            }

                            Text {
                                id: categoryTitle
                                anchors.left: categoryIndicator.right
                                anchors.leftMargin: Theme.spaceSm
                                anchors.verticalCenter: parent.verticalCenter
                                text: categoryDelegate.categoryName
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeBody
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }

                            Text {
                                id: categoryCount
                                anchors.left: categoryTitle.right
                                anchors.leftMargin: Theme.spaceSm
                                anchors.verticalCenter: parent.verticalCenter
                                text: "(" + categoryDelegate.shortcutCount + ")"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeTiny
                                color: Theme.textFaint
                            }

                            MouseArea {
                                id: categoryHeaderMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: categoriesModel.setProperty(index, "expanded", !model.expanded)
                            }
                        }

                        // Shortcut items (only visible when expanded)
                        Column {
                            id: shortcutItems
                            anchors.top: categoryHeader.bottom
                            anchors.topMargin: Theme.spaceXs
                            width: parent.width
                            spacing: Theme.spaceSm
                            visible: categoryDelegate.isExpanded

                            // Two-column grid of shortcuts
                            Grid {
                                id: shortcutGrid
                                width: parent.width
                                columns: 2
                                spacing: Theme.spaceSm
                                visible: categoryDelegate.shortcutCount > 0

                                // Generate shortcut items
                                Repeater {
                                    model: shortcutsRoot.getShortcutsForCategory(categoryDelegate.categoryName)

                                    delegate: Rectangle {
                                        id: shortcutItem
                                        property string shortcutKeys: modelData ? modelData.keys : ""
                                        property string shortcutAction: modelData ? modelData.action : ""
                                        property string shortcutContext: modelData ? modelData.modeContext : ""

                                        width: (shortcutGrid.width - shortcutGrid.spacing) / 2
                                        height: shortcutContent.implicitHeight + Theme.spaceSm * 2
                                        radius: Theme.radiusSmall
                                        color: Theme.glassFill
                                        border.width: 1
                                        border.color: Theme.glassBorder

                                        Column {
                                            id: shortcutContent
                                            anchors.fill: parent
                                            anchors.margins: Theme.spaceSm
                                            spacing: Theme.spaceXs

                                            // Key badge — Column children cannot anchor, so
                                            // centre the pill via a full-width wrapper Item.
                                            Item {
                                                width: parent.width
                                                height: 26

                                                Rectangle {
                                                    id: keyBadge
                                                    anchors.centerIn: parent
                                                    width: keyBadgeText.implicitWidth + Theme.spaceMd
                                                    height: 26
                                                    radius: Theme.radiusPill
                                                    color: Theme.accentDim

                                                    Text {
                                                        id: keyBadgeText
                                                        anchors.centerIn: parent
                                                        text: shortcutItem.shortcutKeys
                                                        font.family: Theme.fontFamilyMono
                                                        font.pixelSize: Theme.fontSizeSmall
                                                        font.weight: Theme.weightMedium
                                                        color: Theme.accent
                                                    }
                                                }
                                            }

                                            // Action text
                                            Text {
                                                width: parent.width
                                                text: shortcutItem.shortcutAction
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeSmall
                                                color: Theme.text
                                                wrapMode: Text.WordWrap
                                                horizontalAlignment: Text.AlignHCenter
                                            }

                                            // Mode context (if any)
                                            Text {
                                                width: parent.width
                                                text: shortcutItem.shortcutContext
                                                font.family: Theme.fontFamily
                                                font.pixelSize: Theme.fontSizeTiny
                                                color: Theme.textFaint
                                                font.italic: true
                                                wrapMode: Text.WordWrap
                                                horizontalAlignment: Text.AlignHCenter
                                                visible: shortcutItem.shortcutContext.length > 0
                                            }
                                        }
                                    }
                                }
                            }

                            // Empty state when no matches
                            Text {
                                width: parent.width
                                visible: categoryDelegate.shortcutCount === 0 && shortcutsRoot.searchQuery.length > 0
                                text: "No matching shortcuts"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.textFaint
                                font.italic: true
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }
                }

                // Bottom spacing
                Item { width: 1; height: Theme.spaceSm }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Update page (inline component — §U)
    // -----------------------------------------------------------------------
    component UpdateTabContent: Item {
        id: updateRoot

        property string updateState: "idle"  // idle | checking | result
        property var updateResult: ({
            anyUpdate: false,
            checkedOnline: false,
            vlc: { update: false, current: "…", latest: "…", online: false },
            webview2: { update: false, current: "…", latest: "…", online: false }
        })
        // Keep the detailed update instructions behind both the backend's
        // comparison result and a display-value check. This prevents a
        // mismatched source from showing download guidance when the two
        // normalized versions are already identical.
        property bool vlcNeedsUpdate: updateResult.vlc.update
                                      && updateResult.vlc.current !== updateResult.vlc.latest
        property bool webview2NeedsUpdate: updateResult.webview2.update
                                           && updateResult.webview2.current !== updateResult.webview2.latest
        property bool anyVisibleUpdate: vlcNeedsUpdate || webview2NeedsUpdate

        Connections {
            target: UpdateChecker
            function onCheckStarted() {
                updateRoot.updateState = "checking"
            }
            function onCheckFinished(result) {
                if (updateRoot.updateState === "checking") {
                    updateRoot.updateResult = result
                    updateRoot.updateState = "result"
                }
            }
            function onCheckCancelled() {
                updateRoot.updateState = "idle"
            }
        }

        Column {
            anchors.fill: parent
            spacing: 0

            // ── Button bar ─────────────────────────────────────────────
            Row {
                id: buttonBar
                width: parent.width
                spacing: Theme.spaceSm
                leftPadding: Theme.spaceMd
                rightPadding: Theme.spaceMd
                topPadding: Theme.spaceSm
                bottomPadding: Theme.spaceSm

                IconButton {
                    glyph: Glyphs.refresh
                    tooltip: "Check for updates"
                    iconSize: 18
                    enabled: updateRoot.updateState !== "checking"
                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: parent.pressed ? Qt.darker(Theme.accent, 1.2)
                             : parent.hovered ? Qt.lighter(Theme.accent, 1.08)
                             : Theme.accent
                        Behavior on color {
                            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                        }
                    }
                    iconColor: Theme.textOnAccent
                    showRing: false
                    onClicked: UpdateChecker.checkUpdates()
                }

                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    iconSize: 18
                    enabled: updateRoot.updateState === "checking"
                    onClicked: UpdateChecker.cancelCheck()
                }
            }

            Rectangle { id: updateDivider; width: parent.width; height: 1; color: Theme.glassBorder }

            // ── Scrollable content ─────────────────────────────────────
            ScrollView {
                id: updateScroll
                width: parent.width
                height: parent.height - buttonBar.height - updateDivider.height
                clip: true
                contentWidth: width
                ScrollBar.vertical: ThinScrollBar {
                    id: updateScrollBar
                    enabled: updateScroll.contentHeight > updateScroll.height
                }

                Column {
                    width: parent.width
                    spacing: Theme.spaceLg
                    padding: Theme.spaceMd

                    // ── IDLE state ─────────────────────────────────────
                    Column {
                        visible: updateRoot.updateState === "idle"
                        width: parent.width - Theme.spaceMd * 2
                        spacing: Theme.spaceSm
                        anchors.horizontalCenter: parent.horizontalCenter

                        Text {
                            width: parent.width
                            text: "Check online sources for newer VLC and WebView2 releases."
                            wrapMode: Text.WordWrap
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeBody
                            color: Theme.textMuted
                        }
                        Text {
                            width: parent.width
                            text: "Installed path: " + UpdateChecker.appRootPath
                            wrapMode: Text.WordWrap
                            font.family: Theme.fontFamilyMono
                            font.pixelSize: Theme.fontSizeTiny
                            color: Theme.textFaint
                        }
                    }

                    // ── CHECKING state ─────────────────────────────────
                    Row {
                        visible: updateRoot.updateState === "checking"
                        spacing: Theme.spaceSm
                        anchors.horizontalCenter: parent.horizontalCenter

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Glyphs.refresh
                            font.family: Theme.fontFamilyIcons
                            font.pixelSize: 16
                            color: Theme.accent

                            NumberAnimation on rotation {
                                running: updateRoot.updateState === "checking"
                                from: 0; to: 360
                                duration: 1000
                                loops: Animation.Infinite
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Checking online sources for updates…"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeBody
                            color: Theme.textMuted
                        }
                    }

                    // ── RESULT: All up to date ─────────────────────────
                    Column {
                        visible: updateRoot.updateState === "result" && !updateRoot.anyVisibleUpdate
                        width: parent.width - Theme.spaceMd * 2
                        spacing: Theme.spaceMd
                        anchors.horizontalCenter: parent.horizontalCenter

                        Row {
                            spacing: Theme.spaceSm
                            anchors.horizontalCenter: parent.horizontalCenter

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: Glyphs.check
                                font.family: Theme.fontFamilyIcons
                                font.pixelSize: 22
                                color: Theme.success
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "All components are up to date"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeLarge
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }
                        }

                        // Version summary table
                        Column {
                            width: parent.width
                            spacing: Theme.spaceXs

                            Row {
                                width: parent.width
                                Text {
                                    width: 110
                                    text: "VLC"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    font.weight: Theme.weightBold
                                    color: Theme.text
                                }
                                Text {
                                    width: 80
                                    text: updateRoot.updateResult.vlc.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: "✓ Up to date"
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.success
                                }
                            }
                            Row {
                                width: parent.width
                                Text {
                                    width: 110
                                    text: "WebView2"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    font.weight: Theme.weightBold
                                    color: Theme.text
                                }
                                Text {
                                    width: 80
                                    text: updateRoot.updateResult.webview2.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: "✓ Up to date"
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.success
                                }
                            }
                        }
                    }

                    // ── RESULT: Update available ───────────────────────
                    Column {
                        visible: updateRoot.updateState === "result" && updateRoot.anyVisibleUpdate
                        width: parent.width - Theme.spaceMd * 2
                        spacing: Theme.spaceLg
                        anchors.horizontalCenter: parent.horizontalCenter

                        Text {
                            width: parent.width
                            text: "Update Available"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeLarge
                            font.weight: Theme.weightBold
                            color: Theme.warning
                        }

                        // ── VLC section ────────────────────────────────
                        Column {
                            visible: updateRoot.vlcNeedsUpdate
                            width: parent.width
                            spacing: Theme.spaceSm

                            Text {
                                text: "VLC Media Player"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeBody
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }

                            Row {
                                spacing: Theme.spaceSm
                                Text {
                                    text: "Current: "
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: updateRoot.updateResult.vlc.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.text
                                }
                                Text {
                                    text: "  →  Latest: "
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: updateRoot.updateResult.vlc.latest
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.accent
                                }
                            }

                            // Download link
                            Row {
                                spacing: Theme.spaceXs
                                width: parent.width
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: Glyphs.link
                                    font.family: Theme.fontFamilyIcons
                                    font.pixelSize: 12
                                    color: Theme.accent
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: UpdateChecker.vlcDownloadUrl + "  ↗"
                                    width: parent.width - 20
                                    wrapMode: Text.WrapAnywhere
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.accent
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: UpdateChecker.openVlcDownload()
                                    }
                                }
                            }

                            // Extraction guide
                            Text {
                                width: parent.width
                                text: UpdateChecker.vlcExtractionGuide
                                wrapMode: Text.WordWrap
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Theme.weightBold
                                color: Theme.textMuted
                            }

                            Repeater {
                                model: UpdateChecker.vlcFiles
                                delegate: Row {
                                    spacing: Theme.spaceSm
                                    width: parent.width
                                    leftPadding: Theme.spaceMd

                                    Text {
                                        text: "•"
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.textMuted
                                    }
                                    Text {
                                        text: modelData.name
                                        font.family: Theme.fontFamilyMono
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.text
                                    }
                                    Text {
                                        text: "← " + modelData.location
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeTiny
                                        color: Theme.textFaint
                                    }
                                }
                            }

                            // Place-at paths
                            Text {
                                width: parent.width
                                text: "Place at:"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Theme.weightBold
                                color: Theme.textMuted
                            }

                            Repeater {
                                model: UpdateChecker.vlcPlacePaths
                                delegate: Row {
                                    spacing: Theme.spaceSm
                                    width: parent.width
                                    leftPadding: Theme.spaceMd

                                    Text {
                                        text: modelData.path
                                        font.family: Theme.fontFamilyMono
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.text
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "(" + modelData.files + ")"
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeTiny
                                        color: Theme.textFaint
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    IconButton {
                                        glyph: Glyphs.addFolder
                                        tooltip: "Open folder in Explorer"
                                        iconSize: 14
                                        implicitWidth: 28
                                        implicitHeight: 28
                                        onClicked: UpdateChecker.openFolder(modelData.path)
                                    }
                                }
                            }
                        }

                        // ── VLC up to date summary (when WebView2 needs update but VLC does not) ─
                        Column {
                            visible: !updateRoot.vlcNeedsUpdate
                            width: parent.width
                            spacing: Theme.spaceSm

                            Text {
                                text: "VLC Media Player"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeBody
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }

                            Row {
                                width: parent.width
                                spacing: Theme.spaceSm
                                Text {
                                    width: 110
                                    text: "VLC"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    font.weight: Theme.weightBold
                                    color: Theme.text
                                }
                                Text {
                                    text: updateRoot.updateResult.vlc.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: "✓ Up to date"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.success
                                }
                            }
                        }

                        // Divider between VLC and WebView2 sections
                        Rectangle {
                            width: parent.width
                            height: 1
                            color: Theme.glassBorder
                        }

                        // ── WebView2 section ───────────────────────────
                        Column {
                            visible: updateRoot.webview2NeedsUpdate
                            width: parent.width
                            spacing: Theme.spaceSm

                            Text {
                                text: "WebView2 Runtime"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeBody
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }

                            Row {
                                spacing: Theme.spaceSm
                                Text {
                                    text: "Current: "
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: updateRoot.updateResult.webview2.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.text
                                }
                                Text {
                                    text: "  →  Latest: "
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: updateRoot.updateResult.webview2.latest
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.accent
                                }
                            }

                            // Download link
                            Row {
                                spacing: Theme.spaceXs
                                width: parent.width
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: Glyphs.link
                                    font.family: Theme.fontFamilyIcons
                                    font.pixelSize: 12
                                    color: Theme.accent
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: UpdateChecker.webview2DownloadUrl + "  ↗"
                                    width: parent.width - 20
                                    wrapMode: Text.WrapAnywhere
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.accent
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: UpdateChecker.openWebview2Download()
                                    }
                                }
                            }

                            // Extraction guide
                            Text {
                                width: parent.width
                                text: UpdateChecker.webview2ExtractionGuide
                                wrapMode: Text.WordWrap
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Theme.weightBold
                                color: Theme.textMuted
                            }

                            Repeater {
                                model: UpdateChecker.webview2Files
                                delegate: Row {
                                    spacing: Theme.spaceSm
                                    width: parent.width
                                    leftPadding: Theme.spaceMd

                                    Text {
                                        text: "•"
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.textMuted
                                    }
                                    Text {
                                        text: modelData.name
                                        font.family: Theme.fontFamilyMono
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.text
                                    }
                                    Text {
                                        text: "← " + modelData.location
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeTiny
                                        color: Theme.textFaint
                                    }
                                }
                            }

                            // Place-at paths
                            Text {
                                width: parent.width
                                text: "Place at:"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Theme.weightBold
                                color: Theme.textMuted
                            }

                            Repeater {
                                model: UpdateChecker.webview2PlacePaths
                                delegate: Row {
                                    spacing: Theme.spaceSm
                                    width: parent.width
                                    leftPadding: Theme.spaceMd

                                    Text {
                                        text: modelData.path
                                        font.family: Theme.fontFamilyMono
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.text
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        text: "(" + modelData.files + ")"
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeTiny
                                        color: Theme.textFaint
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    IconButton {
                                        glyph: Glyphs.addFolder
                                        tooltip: "Open folder in Explorer"
                                        iconSize: 14
                                        implicitWidth: 28
                                        implicitHeight: 28
                                        onClicked: UpdateChecker.openFolder(modelData.path)
                                    }
                                }
                            }
                        }

                        // ── WebView2 up to date summary (when VLC needs update but WebView2 does not) ─
                        Column {
                            visible: !updateRoot.webview2NeedsUpdate
                            width: parent.width
                            spacing: Theme.spaceSm

                            Text {
                                text: "WebView2 Runtime"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeBody
                                font.weight: Theme.weightBold
                                color: Theme.text
                            }

                            Row {
                                width: parent.width
                                spacing: Theme.spaceSm
                                Text {
                                    width: 110
                                    text: "WebView2"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    font.weight: Theme.weightBold
                                    color: Theme.text
                                }
                                Text {
                                    text: updateRoot.updateResult.webview2.current
                                    font.family: Theme.fontFamilyMono
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.textMuted
                                }
                                Text {
                                    text: "✓ Up to date"
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeBody
                                    color: Theme.success
                                }
                            }
                        }
                    }

                    // Bottom spacing
                    Item { width: 1; height: Theme.spaceSm }
                }
            }
        }
    }

    // Tab bar
    Rectangle {
        id: headerBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 48
        radius: Theme.radiusPanel
        color: "transparent"
        z: 2

        // Bottom border
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 1
            color: Theme.glassBorder
        }

        Row {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spaceMd
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            Repeater {
                model: [
                    { label: "General", icon: Glyphs.settings, tabIndex: 0 },
                    { label: "Shortcuts", icon: Glyphs.keyboard, tabIndex: 1 },
                    { label: "Update", icon: Glyphs.refresh, tabIndex: 2 }
                ]

                delegate: Item {
                    id: tabDelegate
                    width: 120
                    height: 40
                    property bool active: root.currentTab === modelData.tabIndex
                    property bool hovered: tabMouse.containsMouse
                    property int tabIndex: modelData.tabIndex

                    Rectangle {
                        id: tabBg
                        anchors.fill: parent
                        anchors.topMargin: 4
                        anchors.bottomMargin: 4
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        radius: Theme.radiusSmall
                        // Bound (not imperatively assigned) so hover never
                        // destroys the active-state colour binding.
                        color: tabDelegate.active ? Theme.glassFill
                             : tabDelegate.hovered ? Theme.glassFillHover : "transparent"
                        border.width: tabDelegate.active ? 1 : 0
                        border.color: Theme.glassBorder

                        Behavior on color {
                            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                        }
                    }

                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.currentTab = tabDelegate.tabIndex
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: Theme.spaceSm

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.icon
                            font.family: Theme.fontFamilyIcons
                            font.pixelSize: 16
                            color: tabDelegate.active ? Theme.accent : Theme.textMuted

                            Behavior on color {
                                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                            }
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeBody
                            font.weight: tabDelegate.active ? Theme.weightBold : Theme.weightNormal
                            color: tabDelegate.active ? Theme.accent : Theme.textMuted

                            Behavior on color {
                                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                            }
                        }
                    }
                }
            }
        }
    }

    // Tab content. Children of a Dialog land in its contentItem, which already
    // ends above the footer — no cross-item anchoring to `footer` needed.
    Item {
        id: tabContent
        anchors.fill: parent
        anchors.topMargin: headerBar.height

        // General Tab
        GeneralSettingsContent {
            id: generalContent
            anchors.fill: parent
            visible: root.currentTab === 0
        }

        // Shortcuts Tab
        ShortcutsTabContent {
            id: shortcutsContent
            anchors.fill: parent
            visible: root.currentTab === 1
        }

        // Update Tab (§U)
        UpdateTabContent {
            id: updateContent
            anchors.fill: parent
            visible: root.currentTab === 2
        }
    }

    // Footer
    footer: Item {
        implicitHeight: Theme.hitTarget

        IconButton {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceMd
            anchors.verticalCenter: parent.verticalCenter
            glyph: Glyphs.check
            tooltip: "Done"
            showRing: false
            iconColor: Theme.textOnAccent
            background: Rectangle {
                radius: Theme.radiusSmall
                color: parent.pressed ? Qt.darker(Theme.accent, 1.2)
                     : parent.hovered ? Qt.lighter(Theme.accent, 1.08) : Theme.accent
                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }
            }
            onClicked: root.close()
        }
    }
}
