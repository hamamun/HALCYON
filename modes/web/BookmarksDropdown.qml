import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Edge-style bookmarks dropdown (§P3.5).
// Anchored under the menu icon; closes on same icon, outside click, or Esc.
// Manage Bookmarks pinned at top. Text rows (title + URL); click navigates.
Popup {
    id: bookmarksDropdown
    width: 280
    height: Math.min(360, 48 + 50 * (bookmarksModel ? bookmarksModel.count : 0))
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    property var browser: modeContext_web
    property var bookmarksModel: browser ? browser.bookmarks : null

    background: Rectangle {
        color: "#131720"
        radius: 12
        border.color: "rgba(255, 255, 255, 0.2)"
        border.width: 1
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        // Manage Bookmarks pinned at top (§P3.5)
        Rectangle {
            Layout.fillWidth: true
            height: 34
            radius: 8
            color: manageArea.containsMouse ? "rgba(255, 255, 255, 0.12)" : "transparent"

            Text {
                anchors.centerIn: parent
                text: "⚙  Manage Bookmarks"
                color: "#5EEAD4"
                font.family: Theme.fontFamily
                font.pixelSize: 13
                font.bold: true
            }

            MouseArea {
                id: manageArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    if (bookmarksDropdown.browser) {
                        bookmarksDropdown.browser.navigateActive("halcyon://bookmarks")
                    }
                    bookmarksDropdown.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: "rgba(255, 255, 255, 0.12)"
        }

        ListView {
            id: bookmarksList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: bookmarksDropdown.bookmarksModel ? bookmarksDropdown.bookmarksModel.getAll() : []

            delegate: Rectangle {
                width: bookmarksList.width
                height: 44
                radius: 6
                color: rowArea.containsMouse ? "rgba(255, 255, 255, 0.08)" : "transparent"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: modelData.title || modelData.url
                        color: "#FFFFFF"
                        font.family: Theme.fontFamily
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: modelData.url
                        color: "rgba(255, 255, 255, 0.55)"
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }

                MouseArea {
                    id: rowArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (bookmarksDropdown.browser) {
                            bookmarksDropdown.browser.navigateActive(modelData.url)
                        }
                        bookmarksDropdown.close()
                    }
                }
            }
        }
    }
}
