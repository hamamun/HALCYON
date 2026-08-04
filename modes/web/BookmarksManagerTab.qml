import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Bookmarks Manager internal tab (§P3.5).
// Add manual (title + URL) · edit · delete (with confirm) · reorder · search.
Rectangle {
    id: bookmarksManager
    color: "#0E121A"

    property var browser: modeContext_web
    property var bookmarksModel: browser ? browser.bookmarks : null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        Text {
            text: "Bookmarks Manager"
            color: "#FFFFFF"
            font.family: Theme.fontFamily
            font.pixelSize: 22
            font.bold: true
        }

        // Search bar & Manual Add form (§P3.5)
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            TextField {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: "Search bookmarks by title or URL..."
            }

            TextField {
                id: manualTitle
                Layout.preferredWidth: 160
                placeholderText: "Title"
            }

            TextField {
                id: manualUrl
                Layout.preferredWidth: 200
                placeholderText: "https://..."
            }

            Button {
                text: "Add Bookmark"
                onClicked: {
                    if (bookmarksManager.bookmarksModel && manualUrl.text) {
                        bookmarksManager.bookmarksModel.addBookmark(manualTitle.text, manualUrl.text)
                        manualTitle.text = ""
                        manualUrl.text = ""
                    }
                }
            }
        }

        // Bookmarks table / list (§P3.5)
        ListView {
            id: managerList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: {
                if (!bookmarksManager.bookmarksModel) return []
                return bookmarksManager.bookmarksModel.search(searchInput.text)
            }

            delegate: Rectangle {
                width: managerList.width
                height: 54
                color: index % 2 === 0 ? "rgba(255, 255, 255, 0.03)" : "transparent"
                radius: 6
                border.color: "rgba(255, 255, 255, 0.08)"
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 12

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: modelData.title || modelData.url
                            color: "#FFFFFF"
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }

                        Text {
                            text: modelData.url
                            color: "rgba(255, 255, 255, 0.6)"
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                        }
                    }

                    // Reorder up/down
                    Button {
                        text: "↑"
                        enabled: index > 0
                        onClicked: {
                            if (bookmarksManager.bookmarksModel) {
                                bookmarksManager.bookmarksModel.reorder(index, index - 1)
                            }
                        }
                    }

                    Button {
                        text: "↓"
                        enabled: index < (managerList.model.length - 1)
                        onClicked: {
                            if (bookmarksManager.bookmarksModel) {
                                bookmarksManager.bookmarksModel.reorder(index, index + 1)
                            }
                        }
                    }

                    // Delete button with confirmation (§P3.5)
                    Button {
                        text: "Delete"
                        onClicked: {
                            deleteConfirmDialog.targetUrl = modelData.url
                            deleteConfirmDialog.open()
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: deleteConfirmDialog
        width: 300
        height: 140
        anchors.centerIn: parent
        modal: true
        focus: true
        property string targetUrl: ""

        background: Rectangle {
            color: "#161B24"
            radius: 12
            border.color: "rgba(255, 255, 255, 0.2)"
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 12

            Text {
                text: "Delete this bookmark?"
                color: "#FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.bold: true
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                Button {
                    text: "Cancel"
                    onClicked: deleteConfirmDialog.close()
                }
                Button {
                    text: "Delete"
                    onClicked: {
                        if (bookmarksManager.bookmarksModel && deleteConfirmDialog.targetUrl) {
                            bookmarksManager.bookmarksModel.removeBookmark(deleteConfirmDialog.targetUrl)
                        }
                        deleteConfirmDialog.close()
                    }
                }
            }
        }
    }
}
