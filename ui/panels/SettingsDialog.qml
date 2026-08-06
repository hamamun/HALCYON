import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Settings — the one home, behind the title-bar gear (§P1.4).
Dialog {
    id: root

    anchors.centerIn: Overlay.overlay
    width: 460
    modal: true
    padding: Theme.spaceXl
    title: "Settings"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    header: Text {
        text: root.title
        padding: Theme.spaceXl
        bottomPadding: Theme.spaceSm
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Theme.weightBold
        color: Theme.text
    }

    contentItem: Column {
        spacing: Theme.spaceLg

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

                // Force a dark palette on the popup so the system (light)
                // palette cannot leak into the option rows — the same fix
                // as the Clear Browsing Data dialog (§4.1).
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
                        // Delegate declared inline so the ListView cannot
                        // fall back to Qt's default system-themed delegate
                        // (which paints text with the OS palette color and
                        // makes the options unreadable on a dark panel).
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

    footer: Item {
        implicitHeight: 56
        TextButton {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            text: "Done"
            primary: true
            onClicked: root.close()
        }
    }
}
