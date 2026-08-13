import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Halcyon.Ui

// Browser tab strip.  No page tab exists on entry: the strip shows only the +
// button until the user opens one or enters an address.
Rectangle {
    id: root
    height: Theme.toolbarRowHeight
    color: Theme.baseElevated

    property var browser: null

    // Borderless mode (§ the borderless toggle) removes the top title bar. In
    // Web mode there is no floating overlay — instead the very same window
    // buttons are hosted inline at the right end of this strip (Edge/Chrome
    // convention), and the empty part of the strip becomes the drag surface.
    // Off by default so ordinary (title-bar) mode is byte-for-byte unchanged.
    property bool borderless: false
    property string activeMode: "web"

    // Drag-to-move over the empty tab-strip area, active only in borderless —
    // this is real Qt chrome (unlike the native page below), so startSystemMove
    // works. Sits behind the controls (z default 0) so tab clicks still win.
    MouseArea {
        anchors.fill: parent
        enabled: root.borderless
        visible: root.borderless
        acceptedButtons: Qt.LeftButton
        onPressed: if (root.Window.window) root.Window.window.startSystemMove()
        onDoubleClicked: Actions.toggleMaximized()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceXs

        // New-tab button sits at the very left edge; page tabs grow rightwards
        // from it, mirroring the address bar's left-to-right reading order.
        IconButton {
            id: addTabButton
            Layout.preferredWidth: Theme.hitTarget
            Layout.preferredHeight: Theme.hitTarget
            glyph: Glyphs.add
            tooltip: root.browser && root.browser.isAtMaxTabs
                     ? "Maximum 15 tabs reached" : "New tab"
            enabled: !root.browser || !root.browser.isAtMaxTabs
            onClicked: if (root.browser) root.browser.addTab("")
        }

        // The title bar is removed in borderless mode, so the shared mode
        // switcher gets a real chrome slot beside New Tab.  Collapse it rather
        // than merely hiding it, leaving normal Web layout untouched.
        ModeChips {
            id: modeChips
            visible: root.borderless
            Layout.preferredWidth: root.borderless ? implicitWidth : 0
            Layout.preferredHeight: root.borderless ? implicitHeight : 0
            activeMode: root.activeMode
            onModeRequested: function(modeId) { Actions.switchMode(modeId) }
        }

        ListView {
            id: tabsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: ListView.Horizontal
            clip: true
            spacing: Theme.spaceXs
            model: root.browser ? root.browser.tabs : []

            delegate: Rectangle {
                id: tabItem
                required property var modelData
                required property int index

                width: Math.min(220, Math.max(132,
                    tabsList.width / Math.max(1, tabsList.count)))
                height: tabsList.height - Theme.spaceSm
                anchors.verticalCenter: parent.verticalCenter
                radius: Theme.radiusSmall
                color: root.browser && root.browser.activeTabIndex === index
                       ? Theme.glassFillHover : Theme.glassFill
                border.width: root.browser && root.browser.activeTabIndex === index ? 1 : 0
                border.color: Theme.accentDim

                RowLayout {
                    anchors.fill: parent
                    z: 1
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceXs
                    spacing: Theme.spaceXs

                    Text {
                        Layout.fillWidth: true
                        text: tabItem.modelData.title || tabItem.modelData.url || "New Tab"
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }

                    IconButton {
                        Layout.preferredWidth: 28
                        Layout.preferredHeight: 28
                        glyph: Glyphs.close
                        iconSize: Theme.iconSize - 5
                        tooltip: "Close tab"
                        showRing: true
                        onClicked: if (root.browser) root.browser.closeTab(tabItem.index)
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: Theme.spaceLg + Theme.spaceXs
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (root.browser) root.browser.setActiveTab(tabItem.index)
                }
            }
        }

        // Window buttons inline at the far right — borderless only. Reserved as
        // its own layout slot (not an overlay), so it can never collide with
        // the tab chips. No Mini button: Web is not a Local playback surface.
        WindowButtons {
            id: webWindowButtons
            visible: root.borderless
            Layout.preferredWidth: root.borderless ? implicitWidth : 0
            Layout.alignment: Qt.AlignVCenter
            activeMode: root.activeMode
            win: root.Window.window
            showMiniButton: false
        }
    }

    // The cap message belongs to browser chrome.  It never overlays a native
    // page, which would be physically impossible/reliability-hostile anyway.
    Rectangle {
        anchors.centerIn: parent
        width: limitText.implicitWidth + Theme.spaceXl
        height: Theme.toolbarRowHeight - Theme.spaceSm
        radius: Theme.radiusPill
        color: Theme.baseElevated
        border.width: 1
        border.color: Theme.glassBorderStrong
        visible: root.browser && root.browser.tabLimitMessageVisible
        z: 2

        Text {
            id: limitText
            anchors.centerIn: parent
            text: "Maximum 15 tabs reached."
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (root.browser) root.browser.dismissTabLimitMessage()
        }
    }

    // Popup-burst protection feedback for ad-heavy sites (e.g. bilibili.tv).
    // Shows when BrowserContext throttles a popup storm that would otherwise
    // crash WebView2 controller creation.
    Rectangle {
        anchors.centerIn: parent
        width: popupText.implicitWidth + Theme.spaceXl
        height: Theme.toolbarRowHeight - Theme.spaceSm
        radius: Theme.radiusPill
        color: Theme.baseElevated
        border.width: 1
        border.color: Theme.glassBorderStrong
        visible: root.browser && root.browser.popupBlockedMessageVisible && !root.browser.tabLimitMessageVisible
        z: 3

        Text {
            id: popupText
            anchors.centerIn: parent
            text: root.browser ? (root.browser.popupBlockedCount <= 1 ? "Pop-up blocked" : "Pop-ups blocked: " + root.browser.popupBlockedCount) : "Pop-up blocked"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (root.browser) root.browser.dismissPopupBlockedMessage()
        }
    }
}
