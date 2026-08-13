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
    // The host window (Main.qml root), resolved once so the TabsRow bindings
    // below can reference its properties directly and stay reactive. A
    // `var w = Window.window` read inside a JS block would not track changes to
    // borderlessEffective/activeMode, so the inline window buttons would never
    // appear on toggle.
    property var hostWindow: webStage.Window.window
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

    // Toggling borderless removes/restores the 44px title bar above this stage,
    // which shifts the page area's on-screen origin without changing any of its
    // local coordinates — so pageArea's own x/y handlers do not fire. Watch the
    // host flag directly and resync the native WebView2 surface to the new
    // position, or the browser viewport would drift by the title-bar height.
    readonly property bool hostBorderless:
        !!webStage.hostWindow && webStage.hostWindow.borderlessEffective === true
    onHostBorderlessChanged: scheduleBrowserSurfaceSync()

    // -------------------- helpers for keyboard shortcuts §P3
    function goNextTab() {
        if (!browser || browser.tabCount <= 1) return
        var next = (browser.activeTabIndex + 1) % browser.tabCount
        browser.setActiveTab(next)
    }
    function goPrevTab() {
        if (!browser || browser.tabCount <= 1) return
        var prev = browser.activeTabIndex - 1
        if (prev < 0) prev = browser.tabCount - 1
        browser.setActiveTab(prev)
    }
    function closeActiveTab() {
        if (!browser || browser.tabCount === 0) return
        browser.closeTab(browser.activeTabIndex)
    }
    function focusAddressBar() {
        if (addressBar && typeof addressBar.focusInput === "function")
            addressBar.focusInput()
    }

    // -------------------- keyboard shortcuts — Web mode only §P3.4
    // All gated on stageActive so they don't fire while Local/M3U is active
    // (keep_stage_alive keeps this stage alive hidden).
    //
    // IMPORTANT: These shortcuts are unique to Web mode and DO NOT conflict with
    // Main.qml shortcuts because:
    // - Ctrl+1/2/3 for mode switching in Main.qml are DISABLED in Web mode
    // - Ctrl+L in Main.qml is DISABLED in Web mode (leftPanelAvailable is false)
    // - Alt+1/2/3 for mode switching in Main.qml are INTENTIONAL for all modes
    // - Other Web shortcuts (Ctrl+T, Ctrl+R, etc.) don't exist in Main.qml
    Item {
        id: webShortcuts

        Shortcut {
            sequence: "Ctrl+T"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.addTab("")
        }
        Shortcut {
            sequence: "Ctrl+N"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.addTab("")
        }
        Shortcut {
            sequence: "Ctrl+W"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount > 0
            onActivated: webStage.closeActiveTab()
        }
        Shortcut {
            sequence: "Ctrl+Tab"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: webStage.goNextTab()
        }
        Shortcut {
            sequence: "Ctrl+Shift+Tab"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: webStage.goPrevTab()
        }
        Shortcut {
            sequence: "Ctrl+PageDown"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: webStage.goNextTab()
        }
        Shortcut {
            sequence: "Ctrl+PageUp"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: webStage.goPrevTab()
        }
        Shortcut {
            sequence: "Ctrl+R"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.reloadOrStop()
        }
        Shortcut {
            sequence: "F5"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.reloadOrStop()
        }
        Shortcut {
            sequence: "Alt+Left"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.goBack()
        }
        Shortcut {
            sequence: "Alt+Right"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser
            onActivated: if (webStage.browser) webStage.browser.goForward()
        }
        Shortcut {
            sequence: "Ctrl+L"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive
            onActivated: webStage.focusAddressBar()
        }
        Shortcut {
            sequence: "Alt+D"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive
            onActivated: webStage.focusAddressBar()
        }
        Shortcut {
            sequence: "Ctrl+D"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && !!webStage.browser.activeTab.url
            onActivated: {
                if (!webStage.browser) return
                var tab = webStage.browser.activeTab
                if (tab && tab.url && !tab.internal)
                    webStage.browser.addBookmark(tab.title || tab.url, tab.url)
            }
        }
        // Ctrl+1..8 = switch to tab N, Ctrl+9 = last tab (Edge/Chrome convention)
        // These are WEB-SPECIFIC and do NOT conflict with Main.qml's mode-switching shortcuts
        // because Main.qml disables Ctrl+1/2/3 when activeMode === "web"
        Shortcut {
            sequence: "Ctrl+1"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 1
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(0)
        }
        Shortcut {
            sequence: "Ctrl+2"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 2
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(1)
        }
        Shortcut {
            sequence: "Ctrl+3"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 3
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(2)
        }
        Shortcut {
            sequence: "Ctrl+4"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 4
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(3)
        }
        Shortcut {
            sequence: "Ctrl+5"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 5
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(4)
        }
        Shortcut {
            sequence: "Ctrl+6"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 6
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(5)
        }
        Shortcut {
            sequence: "Ctrl+7"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 7
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(6)
        }
        Shortcut {
            sequence: "Ctrl+8"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 8
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(7)
        }
        Shortcut {
            sequence: "Ctrl+9"
            context: Qt.WindowShortcut
            enabled: webStage.stageActive && !!webStage.browser && webStage.browser.tabCount >= 2
            onActivated: if (webStage.browser) webStage.browser.setActiveTab(webStage.browser.tabCount - 1)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabsRow {
            id: tabsRow
            browser: webStage.browser
            visible: !webStage.contentFullscreen
            // Host the window buttons inline when the top title bar is gone.
            // Guarded so WebStage still loads standalone (tests): the host
            // window exposes borderlessEffective + activeMode.
            borderless: !!webStage.hostWindow
                        && webStage.hostWindow.borderlessEffective === true
            activeMode: (webStage.hostWindow && webStage.hostWindow.activeMode)
                        ? webStage.hostWindow.activeMode : "web"
            Layout.fillWidth: true
            Layout.preferredHeight: webStage.contentFullscreen ? 0 : Theme.toolbarRowHeight
        }

        AddressBar {
            id: addressBar
            browser: webStage.browser
            stageActive: webStage.stageActive
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
