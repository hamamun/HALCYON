import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Web mode stage (§P3.1, §P3.2, §P3.4).
// Layout: title bar -> tabs row -> address bar -> page.
// The page is a native child window (HWND) BELOW Halcyon chrome.
// No media controls / no EQ / no right panel / no OSD / no PiP.
Rectangle {
    id: webStage
    color: "#0B0E14"

    property var browser: modeContext_web

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // 1. Tabs Row (§P3.1, §P3.4)
        TabsRow {
            id: tabsRow
            Layout.fillWidth: true
            Layout.preferredHeight: 38
        }

        // 2. Address Bar (§P3.1, §P3.4, §P3.5)
        AddressBar {
            id: addressBar
            Layout.fillWidth: true
            Layout.preferredHeight: 42
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: "rgba(255, 255, 255, 0.12)"
        }

        // 3. Page Content Area (§P3.1, §P3.2)
        // Either internal Bookmarks Manager tab, WebView2 native child window,
        // or 'WebView2 is not available' message when runtime missing.
        Item {
            id: pageArea
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Internal Bookmarks Manager Tab (§P3.5)
            BookmarksManagerTab {
                anchors.fill: parent
                visible: (webStage.browser && webStage.browser.activeTab && webStage.browser.activeTab.url === "halcyon://bookmarks")
            }

            // Fallback stage text when WebView2 runtime is not available (§P3.2)
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                visible: !bookmarksManagerVisible && isRuntimeMissing

                property bool bookmarksManagerVisible: (webStage.browser && webStage.browser.activeTab && webStage.browser.activeTab.url === "halcyon://bookmarks")
                property bool isRuntimeMissing: true // On Linux CI / when WebView2 missing, displays this clear message without crash

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 12

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: "WebView2 is not available"
                        color: "#FFFFFF"
                        font.family: Theme.fontFamily
                        font.pixelSize: 20
                        font.bold: true
                    }

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: "Microsoft Edge WebView2 Runtime was not detected on this system."
                        color: "rgba(255, 255, 255, 0.6)"
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                    }
                }
            }
        }
    }
}
