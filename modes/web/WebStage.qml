import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import Halcyon.Ui

Item {
    id: root

    property var ctx: typeof WebPlaylist !== "undefined" ? WebPlaylist : null

    function submitAddress() {
        if (!root.ctx)
            return;
        root.ctx.navigate(addressField.text);
        addressField.selectAll();
    }

    // WebView2 is a native child window. Keep its native-pixel bounds aligned
    // with this unchanged QML browser rectangle.
    function syncBrowserRect() {
        if (!root.ctx || !browserRect)
            return;
        var p = browserRect.mapToItem(null, 0, 0);
        root.ctx.setBrowserRect(p.x, p.y, browserRect.width, browserRect.height,
                                root.visible && browserRect.visible);
    }

    Component.onCompleted: {
        if (root.ctx && root.Window.window)
            root.ctx.attachWindow(root.Window.window);
        Qt.callLater(root.syncBrowserRect);
    }
    onVisibleChanged: syncBrowserRect()
    onWindowChanged: {
        if (root.ctx && root.Window.window)
            root.ctx.attachWindow(root.Window.window);
        syncBrowserRect();
    }
    Component.onDestruction: {
        if (root.ctx) {
            root.ctx.setOverlayOpen(false);
            root.ctx.setBrowserRect(0, 0, 0, 0, false);
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.base
    }

    // --------------------------------------------------------------- tabs --
    Rectangle {
        id: tabsBar
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 42
        color: Theme.baseElevated
        border.color: Theme.glassBorder
        border.width: 1

        Flickable {
            id: tabFlick
            anchors.left: parent.left
            anchors.right: newTabButton.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: Theme.spaceSm
            contentWidth: tabRow.width
            boundsBehavior: Flickable.StopAtBounds
            clip: true

            Row {
                id: tabRow
                height: parent.height
                spacing: Theme.spaceXs

                Repeater {
                    model: root.ctx ? root.ctx.tabs : null

                    delegate: Rectangle {
                        id: tab
                        required property int index
                        required property string title
                        required property string url
                        required property string favicon
                        required property bool isActive
                        required property bool isManager

                        width: 220
                        height: tabsBar.height - Theme.spaceSm
                        anchors.verticalCenter: parent.verticalCenter
                        radius: Theme.radiusControl
                        color: isActive ? Theme.glassFillHover : (tabMouse.containsMouse ? Theme.glassFill : "transparent")
                        border.width: isActive ? 1 : 0
                        border.color: Theme.glassBorder

                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.spaceSm
                            anchors.rightMargin: Theme.spaceXs
                            spacing: Theme.spaceSm

                            Image {
                                width: 18
                                height: 18
                                anchors.verticalCenter: parent.verticalCenter
                                source: tab.favicon
                                visible: !tab.isManager && tab.favicon.length > 0
                                asynchronous: true
                            }
                            Text {
                                visible: tab.isManager || tab.favicon.length === 0
                                anchors.verticalCenter: parent.verticalCenter
                                text: tab.isManager ? Glyphs.bookmarkManager : Glyphs.globe
                                font.family: Theme.fontFamilyIcons
                                font.pixelSize: 16
                                color: tab.isActive ? Theme.accent : Theme.textMuted
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 18 - 30 - Theme.spaceSm * 3
                                text: tab.title.length > 0 ? tab.title : "New tab"
                                elide: Text.ElideRight
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                color: tab.isActive ? Theme.text : Theme.textMuted
                            }
                            IconButton {
                                width: 28
                                height: 28
                                iconSize: 12
                                glyph: Glyphs.close
                                tooltip: "Close tab"
                                showRing: hovered
                                onClicked: if (root.ctx) root.ctx.closeTab(tab.index)
                            }
                        }

                        MouseArea {
                            id: tabMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton
                            z: -1
                            onClicked: if (root.ctx) root.ctx.activateTab(tab.index)
                        }
                    }
                }
            }
        }

        IconButton {
            id: newTabButton
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceSm
            anchors.verticalCenter: parent.verticalCenter
            glyph: Glyphs.add
            tooltip: "New tab"
            onClicked: if (root.ctx) root.ctx.newTab()
        }
    }

    // ---------------------------------------------------------- address bar --
    Rectangle {
        id: addressBar
        anchors.top: tabsBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 54
        color: Qt.rgba(0.043, 0.055, 0.078, 0.96)
        border.color: Theme.glassBorder
        border.width: 1

        Row {
            anchors.fill: parent
            anchors.leftMargin: Theme.spaceMd
            anchors.rightMargin: Theme.spaceMd
            spacing: Theme.spaceSm

            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: Glyphs.back
                tooltip: "Back"
                enabled: root.ctx && root.ctx.canGoBack
                onClicked: if (root.ctx) root.ctx.goBack()
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: Glyphs.forward
                tooltip: "Forward"
                enabled: root.ctx && root.ctx.canGoForward
                onClicked: if (root.ctx) root.ctx.goForward()
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: Glyphs.refresh
                tooltip: "Reload"
                enabled: root.ctx && root.ctx.hasActiveTab
                onClicked: if (root.ctx) root.ctx.reload()
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: Glyphs.home
                tooltip: "Home"
                onClicked: if (root.ctx) root.ctx.home()
            }

            GlassField {
                id: addressField
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - Theme.hitTarget * 6 - Theme.spaceSm * 7
                placeholderText: "Search or enter URL"
                text: ""
                Component.onCompleted: text = root.ctx ? root.ctx.activeDisplayUrl : ""
                onAccepted: root.submitAddress()
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_L && (event.modifiers & Qt.ControlModifier)) {
                        selectAll();
                        forceActiveFocus();
                        event.accepted = true;
                    }
                }
            }

            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                glyph: root.ctx && root.ctx.activeBookmarked ? Glyphs.bookmarkFilled : Glyphs.bookmark
                active: root.ctx && root.ctx.activeBookmarked
                tooltip: root.ctx && root.ctx.activeBookmarked ? "Edit bookmark" : "Add bookmark"
                enabled: root.ctx && root.ctx.hasActiveTab && !root.ctx.activeIsManager
                onClicked: {
                    if (!root.ctx)
                        return;
                    bookmarkTitle.text = root.ctx.activeTitle;
                    bookmarkUrl.text = root.ctx.activeUrl;
                    bookmarkPopup.open();
                    bookmarkTitle.forceActiveFocus();
                }
            }
            IconButton {
                id: bookmarkMenuButton
                anchors.verticalCenter: parent.verticalCenter
                glyph: Glyphs.more
                tooltip: "Bookmarks"
                onClicked: bookmarkMenu.opened ? bookmarkMenu.close() : bookmarkMenu.open()
            }
        }
    }

    // ---------------------------------------------------------- web content --
    Rectangle {
        id: browserRect
        anchors.top: addressBar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        color: "#0E1118"
        border.width: 1
        border.color: Theme.glassBorder
        onXChanged: root.syncBrowserRect()
        onYChanged: root.syncBrowserRect()
        onWidthChanged: root.syncBrowserRect()
        onHeightChanged: root.syncBrowserRect()
        onVisibleChanged: root.syncBrowserRect()

        BookmarkManager {
            anchors.fill: parent
            visible: root.ctx && root.ctx.activeIsManager
            ctx: root.ctx
        }

        Column {
            anchors.centerIn: parent
            width: Math.min(parent.width - Theme.spaceXl * 2, 620)
            spacing: Theme.spaceMd
            visible: !root.ctx || !root.ctx.hasActiveTab

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Glyphs.globe
                font.family: Theme.fontFamilyIcons
                font.pixelSize: 48
                color: Theme.textFaint
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "Type a URL or search above, or press + to open a new tab."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.textMuted
            }
        }

        Column {
            anchors.centerIn: parent
            width: Math.min(parent.width - Theme.spaceXl * 2, 720)
            spacing: Theme.spaceMd
            visible: root.ctx && root.ctx.hasActiveTab && !root.ctx.activeIsManager
                     && !root.ctx.nativeBrowserVisible

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Glyphs.globe
                font.family: Theme.fontFamilyIcons
                font.pixelSize: 42
                color: Theme.accent
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.ctx ? root.ctx.activeTitle : ""
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarge
                font.weight: Theme.weightBold
                color: Theme.text
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.ctx ? root.ctx.activeDisplayUrl : ""
                elide: Text.ElideMiddle
                font.family: Theme.fontFamilyMono
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textFaint
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: root.ctx && root.ctx.webView2InitError.length > 0
                      ? root.ctx.webView2InitError
                      : (root.ctx && root.ctx.webView2Available
                         ? "WebView2 runtime detected. Native browser content attaches in this rectangle."
                         : (root.ctx ? root.ctx.webView2Status : "Web context not available."))
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textMuted
            }
        }
    }

    // ------------------------------------------------------------- popups --
    BookmarkMenu {
        id: bookmarkMenu
        ctx: root.ctx
        x: Math.max(Theme.spaceMd, addressBar.width - width - Theme.spaceMd)
        y: tabsBar.height + addressBar.height - Theme.spaceXs
        onBookmarkPicked: function(sourceIndex) { if (root.ctx) root.ctx.openBookmark(sourceIndex) }
        onManageRequested: if (root.ctx) root.ctx.openBookmarkManager()
        onOpened: if (root.ctx) root.ctx.setOverlayOpen(true)
        onClosed: if (root.ctx) root.ctx.setOverlayOpen(false)
    }

    Popover {
        id: bookmarkPopup
        width: 420
        height: root.ctx && root.ctx.activeBookmarked ? 190 : 150
        x: Math.max(Theme.spaceMd, root.width - width - Theme.spaceXl)
        y: tabsBar.height + addressBar.height - Theme.spaceXs
        onOpened: if (root.ctx) root.ctx.setOverlayOpen(true)
        onClosed: if (root.ctx) root.ctx.setOverlayOpen(false)

        Column {
            anchors.fill: parent
            spacing: Theme.spaceMd

            GlassField {
                id: bookmarkTitle
                width: parent.width
                placeholderText: "Title"
            }
            GlassField {
                id: bookmarkUrl
                width: parent.width
                placeholderText: "URL"
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.spaceSm
                IconButton {
                    visible: root.ctx && root.ctx.activeBookmarked
                    glyph: Glyphs.deleteItem
                    tooltip: "Remove bookmark"
                    onClicked: {
                        if (root.ctx && root.ctx.removeCurrentBookmark())
                            bookmarkPopup.close();
                    }
                }
                IconButton {
                    glyph: Glyphs.cancel
                    tooltip: "Cancel"
                    onClicked: bookmarkPopup.close()
                }
                IconButton {
                    glyph: Glyphs.save
                    tooltip: "Save bookmark"
                    onClicked: {
                        if (!root.ctx)
                            return;
                        var ok = root.ctx.activeBookmarked
                                 ? root.ctx.updateCurrentBookmark(bookmarkTitle.text, bookmarkUrl.text)
                                 : root.ctx.saveBookmark(bookmarkTitle.text, bookmarkUrl.text);
                        if (ok)
                            bookmarkPopup.close();
                    }
                }
            }
        }
    }

    // Normal app toast for Web-only messages (tab limit, bookmark saved). This
    // is deliberately not the media OSD.
    Rectangle {
        id: webToast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.spaceXl
        width: toastText.implicitWidth + Theme.spaceXl * 2
        height: 42
        radius: Theme.radiusPill
        color: Qt.rgba(0.043, 0.055, 0.078, 0.94)
        border.width: 1
        border.color: Theme.glassBorder
        opacity: 0
        visible: opacity > 0

        Text {
            id: toastText
            anchors.centerIn: parent
            text: ""
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.text
        }

        Behavior on opacity {
            NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
        }

        Timer {
            id: toastTimer
            interval: 1400
            onTriggered: webToast.opacity = 0
        }
    }

    Connections {
        target: root.ctx
        enabled: target !== null
        function onActiveChanged() {
            addressField.text = root.ctx ? root.ctx.activeDisplayUrl : "";
        }
        function onToastRequested(message) {
            toastText.text = message;
            webToast.opacity = 1;
            toastTimer.restart();
        }
    }
}
