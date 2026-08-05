import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Halcyon.Ui

// Web mode's entire content area.
//
// The tab and address strips are regular Qt Quick chrome.  In ordinary browsing
// only pageArea is handed to the native WebView2 child HWND, so no website
// overlaps Halcyon's chrome.  When a page enters HTML fullscreen (YouTube's
// fullscreen button), the viewport intentionally expands to this whole stage and
// the top-level window enters real fullscreen.  `stageActive` is set by the
// generic Stage cache when this mode is parked while Local/M3U is active.
Rectangle {
    id: webStage
    color: Theme.base

    property var browser: typeof modeContext_web !== "undefined" ? modeContext_web : null
    property bool stageActive: true
    property bool viewportSyncPending: false
    readonly property bool contentFullscreen: !!browser && browser.contentFullscreen
    property bool windowFullscreenEnteredForWeb: false

    function hostWindowIsFullscreen() {
        var hostWindow = webStage.Window.window
        if (!hostWindow)
            return false
        return typeof hostWindow.fullscreen !== "undefined" ? hostWindow.fullscreen
                                                            : hostWindow.visibility === Window.FullScreen
    }

    function setHostWindowFullscreen(on) {
        var hostWindow = webStage.Window.window
        if (!hostWindow)
            return
        if (typeof hostWindow.setFullscreen === "function")
            hostWindow.setFullscreen(on)
        else
            hostWindow.visibility = on ? Window.FullScreen : Window.Windowed
    }

    function applyContentFullscreen() {
        if (contentFullscreen) {
            if (!hostWindowIsFullscreen()) {
                windowFullscreenEnteredForWeb = true
                setHostWindowFullscreen(true)
            } else {
                windowFullscreenEnteredForWeb = false
            }
        } else if (windowFullscreenEnteredForWeb) {
            windowFullscreenEnteredForWeb = false
            setHostWindowFullscreen(false)
        }
        scheduleBrowserSurfaceSync()
    }

    function syncBrowserSurface() {
        viewportSyncPending = false
        if (!browser)
            return

        var hostWindow = webStage.Window.window
        if (!hostWindow)
            return

        browser.attachToWindow(hostWindow)
        var viewportItem = contentFullscreen ? webStage : pageArea
        var point = viewportItem.mapToItem(null, 0, 0)
        var dpr = hostWindow.devicePixelRatio || 1
        browser.setViewport(Math.round(point.x * dpr), Math.round(point.y * dpr),
                            Math.round(viewportItem.width * dpr),
                            Math.round(viewportItem.height * dpr))
        browser.setStageActive(stageActive)
    }

    function scheduleBrowserSurfaceSync() {
        if (viewportSyncPending)
            return
        viewportSyncPending = true
        Qt.callLater(syncBrowserSurface)
    }

    Component.onCompleted: {
        applyContentFullscreen()
        scheduleBrowserSurfaceSync()
    }
    Component.onDestruction: {
        if (browser)
            browser.detachStage()
        if (windowFullscreenEnteredForWeb) {
            windowFullscreenEnteredForWeb = false
            setHostWindowFullscreen(false)
        }
    }
    onContentFullscreenChanged: applyContentFullscreen()
    onStageActiveChanged: scheduleBrowserSurfaceSync()
    onWidthChanged: scheduleBrowserSurfaceSync()
    onHeightChanged: scheduleBrowserSurfaceSync()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabsRow {
            id: tabsRow
            browser: webStage.browser
            visible: !webStage.contentFullscreen
            Layout.fillWidth: true
            Layout.preferredHeight: webStage.contentFullscreen ? 0 : Theme.toolbarRowHeight
        }

        AddressBar {
            id: addressBar
            browser: webStage.browser
            visible: !webStage.contentFullscreen
            Layout.fillWidth: true
            Layout.preferredHeight: webStage.contentFullscreen ? 0 : Theme.toolbarRowHeight
        }

        Rectangle {
            visible: !webStage.contentFullscreen
            Layout.fillWidth: true
            Layout.preferredHeight: webStage.contentFullscreen ? 0 : 1
            color: Theme.glassBorder
        }

        Item {
            id: pageArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            property bool bookmarksManagerVisible: webStage.browser
                                                   && webStage.browser.activeTab.internal
            property bool runtimeUnavailable: webStage.browser
                                               && webStage.browser.runtimeChecked
                                               && !webStage.browser.runtimeAvailable
            property bool blankTabVisible: webStage.browser
                                           && webStage.browser.runtimeChecked
                                           && webStage.browser.runtimeAvailable
                                           && webStage.browser.tabCount > 0
                                           && !webStage.browser.activeTab.internal
                                           && !webStage.browser.activeTab.url

            onXChanged: webStage.scheduleBrowserSurfaceSync()
            onYChanged: webStage.scheduleBrowserSurfaceSync()
            onWidthChanged: webStage.scheduleBrowserSurfaceSync()
            onHeightChanged: webStage.scheduleBrowserSurfaceSync()

            // This is an internal Halcyon page, not a website.  BrowserContext
            // hides any native controller while this tab is active.
            BookmarksManagerTab {
                anchors.fill: parent
                browser: webStage.browser
                visible: pageArea.bookmarksManagerVisible
            }

            // Clear, in-app fallback for missing runtime/bridge/controller.
            // It is deliberately below the chrome and never a blank page.
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - Theme.spaceXl * 2, 460)
                spacing: Theme.spaceMd
                visible: !pageArea.bookmarksManagerVisible && pageArea.runtimeUnavailable

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "WebView2 is not available"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTitle
                    font.weight: Theme.weightBold
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "Halcyon could not start the Microsoft Edge WebView2 Runtime. "
                          + "Check the installed runtime and the two bridge DLLs in vendor/webview2."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                }
            }

            // An empty tab is intentionally not a loaded page.  The prompt
            // leaves pageArea free until the user types an address.
            ColumnLayout {
                anchors.centerIn: parent
                spacing: Theme.spaceSm
                visible: !pageArea.bookmarksManagerVisible && !pageArea.runtimeUnavailable
                         && (webStage.browser && webStage.browser.tabCount === 0 || pageArea.blankTabVisible)

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Open a site"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeLarge
                    font.weight: Theme.weightBold
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: webStage.browser && webStage.browser.tabCount === 0
                          ? "Use + for a blank tab, or type an address above."
                          : "Type an address or search term above."
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                }
            }
        }
    }

    Connections {
        target: webStage.browser
        enabled: target !== null
        function onRuntimeCheckedChanged() { webStage.scheduleBrowserSurfaceSync() }
        function onRuntimeAvailableChanged() { webStage.scheduleBrowserSurfaceSync() }
        function onActiveTabChanged() { webStage.scheduleBrowserSurfaceSync() }
    }

    Connections {
        id: hostWindowConnections
        target: webStage.Window.window
        enabled: target !== null
        function onFullscreenChanged() {
            if (webStage.contentFullscreen
                    && webStage.windowFullscreenEnteredForWeb
                    && !webStage.hostWindowIsFullscreen()
                    && webStage.browser) {
                webStage.browser.exitFullscreen()
            }
        }
    }
}
