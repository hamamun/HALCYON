import QtQuick
import Halcyon.Ui
import Halcyon.Transport
import QtQuick.Window

// M3U's control bar — §B.4, §P2.3, owner decision 2026-08-02.
//
// ONE ROW, ~52px, designed for EIGHT controls — not Local's two-row bar with
// holes punched in it (§B.2: no reserved gaps, no ghost slots):
//
//        ⏮   ▶/⏸   ⏹   ⏭   🔊━━━   ☰   PiP   ⛶
//
// Every control is a SHARED part from ui/transport/ or the shared IconButton —
// same hit targets, same icons, same hover ring as Local (§B.1). There is no
// seek bar, no time display, no repeat/shuffle, no track menus — absent, not
// greyed. The buffering hairline at the top is this bar's one extra: slow
// streams show progress instead of looking dead (§M2.4).
Item {
    id: root

    property var player: null

    //: The M3U mode context, reached exactly as M3UPanel.qml reaches it —
    //: exposed by main.py as <id-capitalised>Playlist. Read directly rather
    //: than pushed in by the shell's bindTransport(): the shell's
    //: `modeContext` is Local's queue, and teaching it about M3U would put an
    //: M3U-only concern in a shared file for no gain (§A.1, §A.3).
    property var ctx: typeof M3uPlaylist !== "undefined" ? M3uPlaylist : null

    // Buffering progress from VLC (0–100). -1 = idle; the hairline only shows
    // while a stream is genuinely filling its cache.
    property real bufferingPercent: -1

    property bool pipOpen: false

    //: Reflects the left dock's state so the playlist button can light up.
    //: Bound by the shell in Main.qml — see bindTransport().
    property bool playlistVisible: false
    // Bound by the shell for Turbo; M3U never takes that route, so this
    // stays false. Declared so bindTransport() can set it without a warning.
    property bool solidChrome: false

    implicitHeight: 52
    height: implicitHeight

    TransportScrim {
        anchors.fill: parent
        anchors.topMargin: -24        // same fade as Local's bar
        solid: root.solidChrome
    }

    // Buffering hairline — accent gradient, exactly the family look of the
    // fullscreen progress hairline. Hidden the instant playback is running.
    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        width: parent.width * Math.min(100, Math.max(0, root.bufferingPercent)) / 100
        height: 2
        visible: root.bufferingPercent >= 0 && root.bufferingPercent < 100
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Theme.accent }
            GradientStop { position: 1.0; color: Theme.accentAlt }
        }
    }

    Connections {
        target: root.player
        enabled: target !== null && target !== undefined

        function onBuffering(percent) { root.bufferingPercent = percent; }
        function onMediaChanged()     { root.bufferingPercent = 0; }
        function onStateChanged() {
            if (root.player && root.player.isPlaying)
                root.bufferingPercent = -1;
        }
    }

    // ------------------------------------------------ now playing, left --
    // The channel you are watching, readable without opening the playlist.
    // Same information and same visual language as the pinned strip at the
    // foot of M3UPanel.qml, and driven by the same model properties, so the
    // two can never disagree.
    //
    // Three rules keep it out of the way of the controls:
    //
    //   1. it sits on the SAME row, in the empty space left of the centred
    //      cluster — this bar is deliberately one row of ~52px, not Local's
    //      two-row bar (§B.2), and a label stacked above the buttons would
    //      quietly make it two;
    //   2. its width is whatever is actually free between the panel edge and
    //      the buttons, never a fixed guess. The controls are interactive and
    //      always win the space; the label ellipsises, then drops its group
    //      line, then hides entirely as the window narrows;
    //   3. it shows nothing at all until a channel has been chosen — an idle
    //      grey placeholder floating over the picture is noise, which is why
    //      this differs from the panel strip (a solid surface, where an empty
    //      row would look broken instead).
    Item {
        id: nowPlaying

        // The gap to the left edge of the button cluster, less a breathing
        // margin. `controls.x` is live, so this re-measures on every resize.
        readonly property real available:
            controls.x - Theme.spaceMd - Theme.spaceLg

        // Below this there is not enough room to say anything useful, so the
        // label stands down rather than crowding the controls.
        readonly property bool roomy: available >= 96

        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceMd
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, Math.min(260, available))
        height: 34
        visible: roomy && root.ctx !== null && root.ctx.channels.hasCurrent

        Row {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            spacing: Theme.spaceSm

            // Not the channel logo: this is a status marker, and it must not
            // pull a picture over a slow link just to sit on the video. The
            // panel's strip carries the artwork.
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Glyphs.play
                font.family: Theme.fontFamilyIcons
                font.pixelSize: 11
                color: Theme.accent
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 11 - Theme.spaceSm
                spacing: 0

                Text {
                    width: parent.width
                    text: root.ctx ? root.ctx.channels.currentName : ""
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    font.weight: Theme.weightMedium
                    color: Theme.accent
                }
                Text {
                    width: parent.width
                    // The second line is the first thing to go when space runs
                    // short — the channel name matters more than its group.
                    visible: nowPlaying.available >= 150
                             && root.ctx && root.ctx.channels.currentGroup.length > 0
                    text: root.ctx ? root.ctx.channels.currentGroup : ""
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                }
            }
        }
    }

    // ---------------------------------------------------- the seven, centred --
    Row {
        id: controls
        anchors.centerIn: parent
        spacing: Theme.spaceSm

        IconButton {
            glyph: Glyphs.previous
            tooltip: "Previous channel"
            onClicked: Actions.previous()
        }
        IconButton {
            glyph: root.player && root.player.isPlaying ? Glyphs.pause : Glyphs.play
            tooltip: root.player && root.player.isPlaying ? "Pause (Space)" : "Play (Space)"
            onClicked: Actions.playPause()
        }
        IconButton {
            glyph: Glyphs.stop
            tooltip: "Stop"
            onClicked: Actions.stop()
        }
        IconButton {
            glyph: Glyphs.next
            tooltip: "Next channel"
            onClicked: Actions.next()
        }

        Item { width: Theme.spaceXs; height: 1 }

        VolumeControl {
            anchors.verticalCenter: parent.verticalCenter
            volume: root.player ? root.player.volume : 80
            muted: root.player ? root.player.muted : false
            onVolumeRequested: function(v) { Actions.setVolume(v) }
            onMuteToggled: Actions.toggleMute()
        }

        Item { width: Theme.spaceXs; height: 1 }

        IconButton {
            glyph: Glyphs.playlist
            tooltip: "Playlist (Ctrl+L)"
            active: root.playlistVisible
            onClicked: Actions.toggleLeftPanel()
        }

        IconButton {
            glyph: Glyphs.pictureInPicture
            tooltip: "Picture in Picture"
            active: root.pipOpen
            onClicked: root.pipOpen = !root.pipOpen
        }
        IconButton {
            glyph: Glyphs.fullscreen
            tooltip: "Fullscreen (F)"
            onClicked: Actions.toggleFullscreen()
        }
    }

    // PiP — owned by this bar (§P2.5: Phase 2 owns ui/overlay/PipWindow.qml).
    // Shared ring buffer: the window binds the SAME VideoOutput as the stage,
    // so there is no second decode (~0 extra CPU). Closing the window — from
    // its own ✕, a double-click restore, this toggle, or a mode switch —
    // lands back here as pipOpen = false.
    Loader {
        id: pipLoader
        active: root.pipOpen
        source: "../../ui/overlay/PipWindow.qml"
        onLoaded: {
            item.mainWindow = root.Window.window;
            item.closing.connect(function() { root.pipOpen = false; });
        }
    }

    // Phase R mobile remote (v1.2): the phone's PiP button flips the same
    // flag this bar's own PiP button flips — one state, two doorways (§4.1).
    property var remoteBridge: typeof RemoteBridge !== "undefined" ? RemoteBridge : null
    Connections {
        target: root.remoteBridge
        function onTogglePipRequested() { root.pipOpen = !root.pipOpen }
    }

    // ----------------------------------------------------- keyboard — M3U §P2
    // P toggles PiP in M3U only (Local uses P for Previous, so avoid conflict
    // by scoping this Shortcut to this bar's lifetime, i.e. M3U mode active)
    Shortcut {
        sequence: "P"
        context: Qt.WindowShortcut
        onActivated: root.pipOpen = !root.pipOpen
    }
    // Ctrl+P also toggles PiP — secondary, no conflict
    Shortcut {
        sequence: "Ctrl+P"
        context: Qt.WindowShortcut
        onActivated: root.pipOpen = !root.pipOpen
    }
}
