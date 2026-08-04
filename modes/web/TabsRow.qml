import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Tab strip + '+' button (§P3.1, §P3.4).
// No tabs on entry (+ only); typing in address bar creates first tab.
// Maximum 15 tabs; at 15, '+' greys out and 'Maximum 15 tabs reached.'
// appears inside the tabs row as a glass pill (never over the page).
Rectangle {
    id: tabsRow
    height: 38
    color: "transparent"

    property var browser: modeContext_web

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 4

        ListView {
            id: tabsList
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: ListView.Horizontal
            clip: true
            model: tabsRow.browser ? tabsRow.browser.tabs : []

            delegate: Rectangle {
                id: tabItem
                width: Math.min(200, Math.max(120, tabsList.width / Math.max(1, tabsList.count)))
                height: tabsList.height - 4
                anchors.verticalCenter: parent.verticalCenter
                radius: 8
                color: (tabsRow.browser && tabsRow.browser.activeTabIndex === index)
                       ? "rgba(255, 255, 255, 0.12)"
                       : "rgba(255, 255, 255, 0.04)"
                border.width: 1
                border.color: (tabsRow.browser && tabsRow.browser.activeTabIndex === index)
                              ? "rgba(255, 255, 255, 0.24)"
                              : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 6
                    spacing: 4

                    Text {
                        Layout.fillWidth: true
                        text: modelData.title || modelData.url || "New Tab"
                        color: "#FFFFFF"
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        width: 18
                        height: 18
                        radius: 9
                        color: closeArea.containsMouse ? "rgba(255, 255, 255, 0.2)" : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: "×"
                            color: "#FFFFFF"
                            font.pixelSize: 13
                        }

                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                if (tabsRow.browser) {
                                    tabsRow.browser.closeTab(index)
                                }
                            }
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: 24
                    onClicked: {
                        if (tabsRow.browser) {
                            tabsRow.browser.setActiveTab(index)
                        }
                    }
                }
            }
        }

        // '+' Button
        Rectangle {
            id: addTabButton
            width: 32
            height: 32
            radius: 8
            color: addTabArea.containsMouse ? "rgba(255, 255, 255, 0.12)" : "transparent"
            opacity: (tabsRow.browser && tabsRow.browser.isAtMaxTabs) ? 0.35 : 1.0

            Text {
                anchors.centerIn: parent
                text: "+"
                color: "#FFFFFF"
                font.pixelSize: 18
            }

            MouseArea {
                id: addTabArea
                anchors.fill: parent
                hoverEnabled: true
                enabled: !(tabsRow.browser && tabsRow.browser.isAtMaxTabs)
                onClicked: {
                    if (tabsRow.browser) {
                        tabsRow.browser.addTab("")
                    }
                }
            }
        }
    }

    // In-chrome glass pill for 15-tab cap (§P3.1, §P3.2, §P3.4)
    // Renders inside the tabs row chrome, never over the page.
    Rectangle {
        id: limitPill
        anchors.centerIn: parent
        width: 230
        height: 28
        radius: 14
        color: "#1E2430"
        border.color: "rgba(255, 255, 255, 0.25)"
        border.width: 1
        visible: tabsRow.browser ? tabsRow.browser.tabLimitMessageVisible : false

        Text {
            anchors.centerIn: parent
            text: "Maximum 15 tabs reached."
            color: "#FFFFFF"
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }

        MouseArea {
            anchors.fill: parent
            onClicked: {
                if (tabsRow.browser) {
                    tabsRow.browser.dismissTabLimitMessage()
                }
            }
        }
    }
}
