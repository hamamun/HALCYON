import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Online subtitle search — the one home for it (§4.1).
//
// Reached from the gear popover's "Search online…"; the popover holds the
// trigger, this holds the behaviour, and `Subtitles` (core/subtitles.py) holds
// the network work. Nothing here talks to opensubtitles.com directly.
//
// Why a dialog and not more popover: a useful result row is release name +
// language + downloads + an exact/partial badge, and you need a dozen of them
// side by side to choose between "Andor.S02E01.1080p.WEB-DL-GRP" and
// "Andor.S02E01.HDTV". That does not fit a flyout over the video.
//
// The language and match-mode controls here default to the Settings values and
// override them **for this search only** — the saved preference is what you
// want nine times in ten, and the tenth time you should not have to go change
// a global setting and come back.
Dialog {
    id: root

    property string language: Settings.get("subs.online.language", "en")
    property string matchMode: Settings.get("subs.online.matchMode", "best")

    anchors.centerIn: Overlay.overlay
    width: 620
    height: 560
    modal: true
    padding: Theme.spaceXl
    title: "Search subtitles"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function openFor() {
        // Re-read the saved preferences each time: Settings may have changed
        // since this dialog was last constructed.
        language = Settings.get("subs.online.language", "en");
        matchMode = Settings.get("subs.online.matchMode", "best");
        queryField.text = Subtitles.suggestedQuery();
        open();
        if (Subtitles.configured && queryField.text !== "")
            Subtitles.search(queryField.text, language, matchMode);
    }

    background: Rectangle {
        radius: Theme.radiusPanel
        color: Qt.rgba(0.067, 0.086, 0.129, 0.98)
        border.width: 1
        border.color: Theme.glassBorder
    }

    header: Column {
        padding: Theme.spaceXl
        bottomPadding: Theme.spaceSm
        spacing: 2

        Text {
            text: root.title
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Theme.weightBold
            color: Theme.text
        }
        Text {
            width: root.width - Theme.spaceXl * 2
            text: Subtitles.mediaName !== "" ? Subtitles.mediaName : "Nothing playing"
            elide: Text.ElideMiddle
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
    }

    contentItem: Item {

        // ------------------------------------------- not configured yet --
        // A first-run state, not an error. It says what is missing, where the
        // key comes from and where it goes — three facts that otherwise cost a
        // web search each.
        Column {
            anchors.centerIn: parent
            width: parent.width - Theme.spaceXl * 2
            spacing: Theme.spaceLg
            visible: !Subtitles.configured

            Text {
                width: parent.width
                text: "Online subtitle search needs a free OpenSubtitles API key"
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                font.weight: Theme.weightMedium
                color: Theme.text
            }
            Text {
                width: parent.width
                text: "Register at opensubtitles.com, create a consumer under "
                    + "your profile, then paste the key into Settings \u203a "
                    + "Online subtitles. Halcyon does not ship a shared key: "
                    + "one would be rate-limited across every install."
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.textMuted
            }
            TextButton {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Open Settings"
                primary: true
                glyph: Glyphs.settings
                onClicked: { root.close(); Actions.showSettings(); }
            }
        }

        // ---------------------------------------------------- search UI --
        Column {
            anchors.fill: parent
            spacing: Theme.spaceMd
            visible: Subtitles.configured

            // query row
            Row {
                width: parent.width
                spacing: Theme.spaceSm

                TextField {
                    id: queryField
                    width: parent.width - searchButton.width - Theme.spaceSm
                    placeholderText: "Title, or leave as detected"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeBody
                    color: Theme.text
                    placeholderTextColor: Theme.textFaint
                    selectByMouse: true
                    onAccepted: Subtitles.search(text, root.language, root.matchMode)

                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: Theme.glassFill
                        border.width: 1
                        border.color: queryField.activeFocus ? Theme.accent : Theme.glassBorder
                    }
                }
                TextButton {
                    id: searchButton
                    text: Subtitles.busy ? "Searching\u2026" : "Search"
                    primary: true
                    enabled: !Subtitles.busy
                    onClicked: Subtitles.search(queryField.text, root.language, root.matchMode)
                }
            }

            // language + match mode
            Row {
                width: parent.width
                spacing: Theme.spaceSm

                ComboBox {
                    id: languageBox
                    width: 220
                    // The list comes from the service, so Settings and this
                    // dialog cannot drift apart (§B.1).
                    model: Subtitles.languages
                    textRole: "name"
                    valueRole: "code"
                    currentIndex: indexOfValue(root.language)
                    onActivated: root.language = currentValue

                    background: Rectangle {
                        radius: Theme.radiusSmall
                        color: Theme.glassFill
                        border.width: 1
                        border.color: Theme.glassBorder
                    }
                    contentItem: Text {
                        leftPadding: Theme.spaceMd
                        text: languageBox.displayText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.text
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                // Two states, one control. "Best" is the default because for a
                // file on disk the hash match is nearly always right; "All"
                // exists for the cases where it is not — an odd release, a
                // re-encode, a language with thin coverage.
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.spaceXs

                    Repeater {
                        model: [
                            { id: "best", label: "Best match" },
                            { id: "all",  label: "All results" }
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool isCurrent: root.matchMode === modelData.id

                            width: 96
                            height: 30
                            radius: Theme.radiusSmall
                            color: isCurrent ? Theme.accentDim
                                 : modeMouse.containsMouse ? Theme.glassFillHover
                                 : Theme.glassFill
                            border.width: 1
                            border.color: isCurrent ? Theme.accent : Theme.glassBorder

                            Behavior on color {
                                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                            }

                            Text {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                color: parent.isCurrent ? Theme.accent : Theme.textMuted
                            }

                            MouseArea {
                                id: modeMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.matchMode = modelData.id;
                                    if (queryField.text !== "" || Subtitles.mediaName !== "")
                                        Subtitles.search(queryField.text, root.language, root.matchMode);
                                }
                            }
                        }
                    }
                }
            }

            // status line
            Text {
                width: parent.width
                text: Subtitles.status
                visible: text !== ""
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.textFaint
            }

            // ------------------------------------------------- results --
            ListView {
                id: results
                width: parent.width
                height: parent.height - y
                clip: true
                model: Subtitles.results
                spacing: 2
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 6
                }

                delegate: ListRow {
                    required property var modelData
                    width: ListView.view.width - Theme.spaceSm
                    height: 46
                    // Double-click is the shortcut; the explicit button below
                    // is the discoverable path. Same action either way.
                    onDoubleClicked: Subtitles.download(modelData.fileId)

                    Row {
                        anchors.fill: parent
                        anchors.rightMargin: Theme.spaceSm
                        spacing: Theme.spaceSm

                        // match badge — the whole point of "best vs all"
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 58
                            height: 20
                            radius: Theme.radiusSmall
                            color: modelData.matchKind === "hash" ? Theme.accentDim : Theme.glassFill
                            border.width: 1
                            border.color: modelData.matchKind === "hash"
                                          ? Theme.accent : Theme.glassBorder

                            Text {
                                anchors.centerIn: parent
                                text: modelData.matchKind === "hash" ? "exact"
                                    : modelData.matchKind === "title" ? "match" : "partial"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeTiny
                                color: modelData.matchKind === "hash" ? Theme.accent : Theme.textFaint
                            }
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 58 - 84 - Theme.spaceSm * 3
                            spacing: 1

                            Text {
                                width: parent.width
                                text: modelData.release
                                elide: Text.ElideMiddle
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.text
                            }
                            Text {
                                width: parent.width
                                text: modelData.language.toUpperCase()
                                    + "  \u00b7  " + modelData.downloads + " downloads"
                                    + (modelData.hearingImpaired ? "  \u00b7  SDH" : "")
                                    + (modelData.trusted ? "  \u00b7  trusted" : "")
                                    + (modelData.machineTranslated ? "  \u00b7  machine" : "")
                                elide: Text.ElideRight
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeTiny
                                color: Theme.textFaint
                            }
                        }

                        TextButton {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 84
                            text: "Download"
                            enabled: !Subtitles.busy
                            onClicked: Subtitles.download(modelData.fileId)
                        }
                    }
                }
            }
        }
    }

    footer: Item {
        implicitHeight: 56

        Text {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            text: Subtitles.quota
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.textFaint
        }
        TextButton {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spaceXl
            anchors.verticalCenter: parent.verticalCenter
            text: "Close"
            onClicked: root.close()
        }
    }

    // A finished download is already attached to the player by the time this
    // fires (main.py wires downloadFinished -> the same add_slave path a
    // dropped .srt takes), so the dialog's job is done: get out of the way.
    Connections {
        target: (typeof Subtitles !== "undefined" && Subtitles) ? Subtitles : null
        enabled: target !== null

        function onDownloadFinished(path) {
            Actions.osd("Subtitle loaded", Glyphs.subtitles);
            root.close();
        }
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1
                              duration: Theme.durNormal; easing.type: Theme.easing }
            NumberAnimation { property: "scale"; from: 0.96; to: 1
                              duration: Theme.durNormal; easing.type: Theme.easing }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0
                          duration: Theme.durFast; easing.type: Theme.easing }
    }
}
