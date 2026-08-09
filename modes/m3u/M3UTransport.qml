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

    // Buffering progress from VLC (0–100). -1 = idle; the hairline only shows
    // while a stream is genuinely filling its cache.
    property real bufferingPercent: -1

    property bool pipOpen: false

    //: Reflects the left dock's state so the playlist button can light up.
    //: Bound by the shell in Main.qml — see bindTransport().
    property bool playlistVisible: false

    implicitHeight: 52
    height: implicitHeight

    TransportScrim {
        anchors.fill: parent
        anchors.topMargin: -24        // same fade as Local's bar
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

    // ---------------------------------------------------- the seven, centred --
    Row {
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
