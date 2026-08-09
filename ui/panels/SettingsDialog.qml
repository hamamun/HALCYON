import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui
import Halcyon.Panels

// Settings — the one home, behind the title-bar gear (§P1.4).
// Tabbed layout: General | Shortcuts
Dialog {
    id: root

    anchors.centerIn: Overlay.overlay
    width: 520
    height: 560
    modal: true
    padding: 0
    title: "Settings"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    // Tab bar
    Rectangle {
        id: headerBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 48
        radius: parent.radius
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
                    { label: "Shortcuts", icon: Glyphs.keyboard, tabIndex: 1 }
                ]

                delegate: Item {
                    id: tabDelegate
                    width: 120
                    height: 40
                    property bool active: root.currentTab === modelData.tabIndex
                    property int tabIndex: modelData.tabIndex

                    Rectangle {
                        id: tabBg
                        anchors.fill: parent
                        anchors.topMargin: 4
                        anchors.bottomMargin: 4
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        radius: Theme.radiusSmall
                        color: tabDelegate.active ? Theme.glassFill : "transparent"
                        border.width: tabDelegate.active ? 1 : 0
                        border.color: Theme.glassBorder

                        Behavior on color {
                            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.currentTab = tabDelegate.tabIndex
                        onEntered: if (!tabDelegate.active) tabBg.color = Theme.glassFillHover
                        onExited: tabBg.color = tabDelegate.active ? Theme.glassFill : "transparent"
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

    // Current tab state
    property int currentTab: 0

    // Tab content
    Item {
        id: tabContent
        anchors.top: headerBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: footer.top
        anchors.topMargin: Theme.spaceMd

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

// ---------------------------------------------------------------------------
// General Settings Content
// ---------------------------------------------------------------------------
Item {
    id: generalContent

    ScrollView {
        id: generalScroll
        anchors.fill: parent
        anchors.margins: Theme.spaceMd
        anchors.bottomMargin: 0
        clip: true
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

// ---------------------------------------------------------------------------
// Shortcuts Tab Content
// ---------------------------------------------------------------------------
Item {
    id: shortcutsContent

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
        ListElement { category: "Playback"; keys: "\u2190"; action: "Seek back 10 seconds"; modeContext: "" }
        ListElement { category: "Playback"; keys: "\u2192"; action: "Seek forward 10 seconds"; modeContext: "" }
        ListElement { category: "Playback"; keys: "Shift + \u2190"; action: "Seek back 60 seconds"; modeContext: "" }
        ListElement { category: "Playback"; keys: "Shift + \u2192"; action: "Seek forward 60 seconds"; modeContext: "" }
        ListElement { category: "Playback"; keys: "\u2191"; action: "Volume up 5%"; modeContext: "" }
        ListElement { category: "Playback"; keys: "\u2193"; action: "Volume down 5%"; modeContext: "" }
        ListElement { category: "Playback"; keys: "M"; action: "Toggle mute"; modeContext: "" }
        ListElement { category: "Playback"; keys: "N"; action: "Next track"; modeContext: "" }
        ListElement { category: "Playback"; keys: "Shift + N"; action: "Previous track"; modeContext: "" }
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
        ListElement { category: "Web Browser"; keys: "Alt + \u2190"; action: "Go back"; modeContext: "Web mode only" }
        ListElement { category: "Web Browser"; keys: "Alt + \u2192"; action: "Go forward"; modeContext: "Web mode only" }
        ListElement { category: "Web Browser"; keys: "Ctrl + R"; action: "Refresh page"; modeContext: "Web mode only" }
        ListElement { category: "Web Browser"; keys: "F5"; action: "Refresh page"; modeContext: "Web mode only" }
        ListElement { category: "Web Browser"; keys: "Alt + Home"; action: "Go to homepage"; modeContext: "Web mode only" }

        // System shortcuts
        ListElement { category: "System"; keys: "Mini mode"; action: "Enter mini player mode"; modeContext: "Local mode, media loaded" }
    }

    // Categories with their default expanded state
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
                anchors.rightMargin: Theme.spaceSm
                placeholderText: "Search..."
                placeholderTextColor: Theme.textFaint
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.text
                background: Rectangle { color: "transparent" }
                clip: true
                onTextChanged: shortcutsContent.searchQuery = text
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
                    property string categoryName: model.name
                    property bool isExpanded: model.expanded
                    property int shortcutCount: shortcutsContent.getShortcutsForCategory(model.name).length

                    // Category header
                    Rectangle {
                        id: categoryHeader
                        width: parent.width
                        height: 36
                        radius: Theme.radiusSmall
                        color: Theme.glassFill

                        // Expanded/collapsed indicator
                        Text {
                            id: categoryIndicator
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.spaceMd
                            anchors.verticalCenter: parent.verticalCenter
                            text: categoryDelegate.isExpanded ? Glyphs.chevronDown : Glyphs.chevronRight
                            font.family: Theme.fontFamilyIcons
                            font.pixelSize: 12
                            color: Theme.textMuted
                        }

                        Text {
                            id: categoryTitle
                            anchors.left: categoryIndicator.right
                            anchors.leftMargin: Theme.spaceSm
                            anchors.verticalCenter: parent.verticalCenter
                            text: categoryName
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
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: categoryHeader.color = Theme.glassFillHover
                            onExited: categoryHeader.color = Theme.glassFill
                            onClicked: {
                                categoryDelegate.isExpanded = !categoryDelegate.isExpanded;
                                categoriesModel.setProperty(index, "expanded", categoryDelegate.isExpanded);
                            }
                        }
                    }

                    // Shortcut items (only visible when expanded)
                    Column {
                        id: shortcutItems
                        anchors.top: categoryHeader.bottom
                        anchors.topMargin: Theme.spaceXs
                        width: parent.width
                        visible: categoryDelegate.isExpanded

                        // Two-column grid of shortcuts
                        Grid {
                            id: shortcutGrid
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width
                            columns: 2
                            spacing: Theme.spaceSm

                            // Generate shortcut items
                            Repeater {
                                model: shortcutsContent.getShortcutsForCategory(categoryName)

                                delegate: Rectangle {
                                    id: shortcutItem
                                    property string shortcutKeys: modelData ? modelData.keys : ""
                                    property string shortcutAction: modelData ? modelData.action : ""
                                    property string shortcutContext: modelData ? modelData.modeContext : ""

                                    width: (parent.width - parent.spacing) / 2
                                    height: shortcutContent.implicitHeight + Theme.spaceMd * 2
                                    radius: Theme.radiusSmall
                                    color: Theme.glassFill
                                    border.width: 1
                                    border.color: Theme.glassBorder

                                    Column {
                                        id: shortcutContent
                                        anchors.fill: parent
                                        anchors.margins: Theme.spaceSm
                                        spacing: Theme.spaceXs

                                        // Key badge
                                        Rectangle {
                                            id: keyBadge
                                            width: keyBadgeText.implicitWidth + Theme.spaceMd
                                            height: 26
                                            radius: Theme.radiusPill
                                            color: Theme.accentDim
                                            anchors.horizontalCenter: parent.horizontalCenter

                                            Text {
                                                id: keyBadgeText
                                                anchors.centerIn: parent
                                                text: shortcutKeys
                                                font.family: Theme.fontFamilyMono
                                                font.pixelSize: Theme.fontSizeSmall
                                                font.weight: Theme.weightMedium
                                                color: Theme.accent
                                            }
                                        }

                                        // Action text
                                        Text {
                                            id: actionText
                                            width: parent.width
                                            text: shortcutAction
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            color: Theme.text
                                            wrapMode: Text.WordWrap
                                            horizontalAlignment: Text.AlignHCenter
                                        }

                                        // Mode context (if any)
                                        Text {
                                            id: contextText
                                            width: parent.width
                                            text: shortcutContext
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeTiny
                                            color: Theme.textFaint
                                            font.italic: true
                                            wrapMode: Text.WordWrap
                                            horizontalAlignment: Text.AlignHCenter
                                            visible: shortcutContext.length > 0
                                        }
                                    }
                                }
                            }
                        }

                        // Empty state when no matches
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.topMargin: Theme.spaceMd
                            visible: categoryDelegate.shortcutCount === 0 && shortcutsContent.searchQuery.length > 0
                            text: "No matching shortcuts"
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.textFaint
                            font.italic: true
                        }
                    }
                }
            }

            // Bottom spacing
            Item { width: 1; height: Theme.spaceSm }
        }
    }
}
