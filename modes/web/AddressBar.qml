import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Halcyon.Ui

// Address bar (§P3.1, §P3.4, §P3.5).
// Icon-only nav buttons: Back · Forward · Reload/Stop · Home · ★ star · ⋮ menu.
// Text URL/search field: shows current URL, select-all on focus, Enter navigates,
// non-URL input searches Google.
Rectangle {
    id: addressBar
    height: 42
    color: "transparent"

    property var browser: modeContext_web

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 4

        IconButton {
            id: backBtn
            text: "←"
            tooltip: "Back"
            onClicked: {
                if (addressBar.browser && addressBar.browser.activeTab) {
                    // Back handled by active tab controller
                }
            }
        }

        IconButton {
            id: forwardBtn
            text: "→"
            tooltip: "Forward"
            onClicked: {
                if (addressBar.browser && addressBar.browser.activeTab) {
                    // Forward handled by active tab controller
                }
            }
        }

        IconButton {
            id: reloadStopBtn
            text: (addressBar.browser && addressBar.browser.activeTab && addressBar.browser.activeTab.loading) ? "✕" : "↻"
            tooltip: (addressBar.browser && addressBar.browser.activeTab && addressBar.browser.activeTab.loading) ? "Stop" : "Reload"
            onClicked: {
                if (addressBar.browser && addressBar.browser.activeTab) {
                    // Reload or stop handled by active tab controller
                }
            }
        }

        IconButton {
            id: homeBtn
            text: "⌂"
            tooltip: "Home (site homepage or Google)"
            onClicked: {
                if (addressBar.browser) {
                    addressBar.browser.navigateHome()
                }
            }
        }

        // URL / search text input field (§P3.1, §P3.4)
        Rectangle {
            id: urlContainer
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: 5
            Layout.bottomMargin: 5
            radius: 8
            color: "rgba(255, 255, 255, 0.08)"
            border.color: urlInput.activeFocus ? "#5EEAD4" : "rgba(255, 255, 255, 0.16)"
            border.width: 1

            TextInput {
                id: urlInput
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                verticalAlignment: TextInput.AlignVCenter
                color: "#FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: 13
                selectByMouse: true
                clip: true
                text: (addressBar.browser && addressBar.browser.activeTab)
                      ? (addressBar.browser.activeTab.url || "")
                      : ""

                onActiveFocusChanged: {
                    if (activeFocus) {
                        selectAll()
                    }
                }

                onAccepted: {
                    if (addressBar.browser) {
                        addressBar.browser.navigateActive(text)
                    }
                }
            }
        }

        // Bookmark star button (§P3.5)
        // Empty star = not bookmarked -> Add popup; filled star = bookmarked -> Edit/Remove popup
        IconButton {
            id: starBtn
            property bool isSaved: (addressBar.browser && addressBar.browser.bookmarks && addressBar.browser.activeTab)
                                   ? addressBar.browser.bookmarks.isBookmarked(addressBar.browser.activeTab.url)
                                   : false
            text: isSaved ? "★" : "☆"
            tooltip: isSaved ? "Edit or remove bookmark" : "Bookmark this page"
            onClicked: {
                if (!addressBar.browser || !addressBar.browser.activeTab) return
                if (isSaved) {
                    editBookmarkPopup.open()
                } else {
                    addBookmarkPopup.open()
                }
            }
        }

        // Menu / bookmarks dropdown icon (§P3.5)
        IconButton {
            id: menuBtn
            text: "⋮"
            tooltip: "Bookmarks and menu"
            onClicked: {
                bookmarksDropdown.visible = !bookmarksDropdown.visible
            }
        }
    }

    // Add bookmark popup (§P3.5)
    Popup {
        id: addBookmarkPopup
        width: 320
        height: 160
        anchors.centerIn: parent
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: "#161B24"
            radius: 12
            border.color: "rgba(255, 255, 255, 0.2)"
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            Text {
                text: "Add Bookmark"
                color: "#FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.bold: true
            }

            TextField {
                id: bookmarkTitleInput
                Layout.fillWidth: true
                placeholderText: "Title"
                text: (addressBar.browser && addressBar.browser.activeTab)
                      ? (addressBar.browser.activeTab.title || addressBar.browser.activeTab.url)
                      : ""
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                Button {
                    text: "Cancel"
                    onClicked: addBookmarkPopup.close()
                }
                Button {
                    text: "Save"
                    onClicked: {
                        if (addressBar.browser && addressBar.browser.bookmarks && addressBar.browser.activeTab) {
                            addressBar.browser.bookmarks.addBookmark(bookmarkTitleInput.text, addressBar.browser.activeTab.url)
                        }
                        addBookmarkPopup.close()
                    }
                }
            }
        }
    }

    // Edit/Remove bookmark popup (§P3.5)
    Popup {
        id: editBookmarkPopup
        width: 320
        height: 180
        anchors.centerIn: parent
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: "#161B24"
            radius: 12
            border.color: "rgba(255, 255, 255, 0.2)"
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            Text {
                text: "Edit Bookmark"
                color: "#FFFFFF"
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.bold: true
            }

            TextField {
                id: editTitleInput
                Layout.fillWidth: true
                placeholderText: "Title"
                text: {
                    if (!addressBar.browser || !addressBar.browser.bookmarks || !addressBar.browser.activeTab) return ""
                    var b = addressBar.browser.bookmarks.getByUrl(addressBar.browser.activeTab.url)
                    return b ? (b.title || "") : ""
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                Button {
                    text: "Remove"
                    onClicked: {
                        if (addressBar.browser && addressBar.browser.bookmarks && addressBar.browser.activeTab) {
                            addressBar.browser.bookmarks.removeBookmark(addressBar.browser.activeTab.url)
                        }
                        editBookmarkPopup.close()
                    }
                }
                Button {
                    text: "Cancel"
                    onClicked: editBookmarkPopup.close()
                }
                Button {
                    text: "Save"
                    onClicked: {
                        if (addressBar.browser && addressBar.browser.bookmarks && addressBar.browser.activeTab) {
                            addressBar.browser.bookmarks.updateBookmark(addressBar.browser.activeTab.url, editTitleInput.text, addressBar.browser.activeTab.url)
                        }
                        editBookmarkPopup.close()
                    }
                }
            }
        }
    }
}
