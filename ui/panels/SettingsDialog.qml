import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Settings — the one home, behind the title-bar gear (§P1.4).
Dialog {
    id: root

    anchors.centerIn: Overlay.overlay
    width: 480
    // The dialog grew a section; cap it against the window and scroll the
    // content rather than letting it run off the screen on a 768px laptop.
    height: Math.min(implicitHeight, Overlay.overlay ? Overlay.overlay.height - 80 : 640)
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

    // Settings is now taller than a small laptop screen, so the body scrolls.
    // ScrollView rather than a taller dialog: the dialog is capped against the
    // overlay above, and a modal that runs off the bottom of the screen hides
    // its own Done button.
    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        Column {
            width: parent.width
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

            // ============================================ online subtitles ==
            // The configuration half of subtitle download. The *doing* half is
            // the gear popover's "Search online…" — this section never searches
            // and never downloads (§4.1); it only decides what those do.
            Text {
                width: parent.width
                text: "ONLINE SUBTITLES"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                font.weight: Theme.weightBold
                color: Theme.textFaint
            }

            SettingField {
                width: parent.width
                label: "API key"
                placeholder: "Paste your opensubtitles.com key"
                secret: true
                value: Settings.get("subs.online.apiKey", "")
                description: "Free from opensubtitles.com \u203a profile \u203a consumers. "
                           + "Halcyon ships no shared key \u2014 one would be rate-limited "
                           + "across every install. Stored in plain text in settings.json."
                onEdited: function(v) { Settings.set("subs.online.apiKey", v.trim()) }
            }

            SettingSelect {
                width: parent.width
                label: "Preferred language"
                model: (typeof Subtitles !== "undefined" && Subtitles)
                       ? Subtitles.languages : []
                textRole: "name"
                valueRole: "code"
                value: Settings.get("subs.online.language", "en")
                description: "Searches start in this language. The search dialog can "
                           + "override it for one search without changing this."
                onActivated: function(v) { Settings.set("subs.online.language", v) }
            }

            // Two states, not a toggle labelled with a jargon word. The
            // description spells out what each actually returns, because
            // "best" and "all" mean nothing until you have been surprised by
            // an empty result list once.
            //
            // Both the highlight and the paragraph below now hang off
            // SettingChoice's live `value` property. They used to call
            // `Settings.get(...)` inline — a slot, not a property, so QML
            // bound to nothing and never re-evaluated. The picker wrote the
            // setting correctly and then refused to *look* switched, in either
            // direction. See ui/panels/SettingChoice.qml.
            SettingChoice {
                id: matchModeChoice
                width: parent.width
                label: "Search results"
                settingKey: "subs.online.matchMode"
                defaultValue: "best"
                options: [
                    { id: "best", label: "Best match" },
                    { id: "all",  label: "All results" }
                ]
                description: value === "best"
                      ? "Best match \u2014 only subtitles the file\u2019s own checksum (or an "
                        + "exact title and episode) vouches for. Usually one or two rows, "
                        + "and usually the right one."
                      : "All results \u2014 everything the search turned up, partial and "
                        + "approximate matches included, most likely first. Use it when "
                        + "Best match finds nothing."
            }

            SettingRow {
                width: parent.width
                label: "Save next to the video"
                description: "Downloaded subtitles land beside the media file so they "
                           + "auto-load next time. Falls back to Halcyon\u2019s cache when "
                           + "the folder is read-only."
                checked: Settings.get("subs.online.saveAlongsideMedia", true)
                onToggled: function(on) { Settings.set("subs.online.saveAlongsideMedia", on) }
            }

            // Optional, and said to be optional. An account raises the daily
            // download quota; leaving it blank still works.
            SettingField {
                width: parent.width
                label: "Username"
                placeholder: "Optional \u2014 raises the daily quota"
                value: Settings.get("subs.online.username", "")
                onEdited: function(v) { Settings.set("subs.online.username", v.trim()) }
            }

            SettingField {
                width: parent.width
                label: "Password"
                placeholder: "Optional"
                secret: true
                value: Settings.get("subs.online.password", "")
                description: "Only used to sign in for downloads. Anonymous downloads "
                           + "work too, with a smaller daily allowance."
                onEdited: function(v) { Settings.set("subs.online.password", v) }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

            SettingSelect {
                width: parent.width
                label: "Video backend"
                model: ["auto", "i420", "rv32"]
                value: Settings.get("video.backend", "auto")
                description: "Backend changes take effect on the next launch."
                onActivated: function(v) { Settings.set("video.backend", v) }
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
