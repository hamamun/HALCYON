import QtQuick
import Halcyon.Ui
import Halcyon.Transport

// Local's control bar — §B.4, §P1.5.
//
// TWO ROWS, ~72px, arranged for Local's fourteen controls:
//
//   ●━━━━━━━━━━━━━━○···········································
//   ▶ ⏹ ⏮ ⏪ ⏩ ⏭  🔊━━━  -01:23 · 04:56 · 06:19    ☰ CC 🔁 🔀 ⛶
//
// Every control here is a SHARED part from ui/transport/ or a shared IconButton.
// This file contributes arrangement only — no new colours, no new radii, no new
// durations (§B.1). M3U will arrange the same parts differently, for six
// controls, in a single row (§B.2) — and that is not an inconsistency, it is the
// point.
Item {
    id: root

    property var player: null
    property int repeatMode: 0        // 0 off, 1 one, 2 all
    property bool shuffle: false
    //: Reflects the left dock's state so the playlist button can light up.
    //: Bound by the shell in Main.qml — see bindTransport().
    property bool playlistVisible: false
    property var audioTracks: []
    property var embeddedSubtitleTracks: []
    property var localSubtitleTracks: []
    property int currentAudioId: -1
    property int currentSubtitleId: -1
    property int subtitleDelayMs: 0
    property bool hasVideo: true

    // The bar must never auto-hide while the subtitle popover or the download
    // flyout is open (§P1.4).
    readonly property bool popoverOpen: trackPopover.opened || subDownload.opened
    readonly property bool scrubbing: seekBar.scrubbing

    // The attached Window, captured in the bar's own scope (the only valid
    // place — attached properties don't resolve through an id from a child).
    // Null until the bar is in a window; popups cap their height from it.
    readonly property real windowHeight: Window ? Window.height : 0

    implicitHeight: 72
    height: implicitHeight

    TransportScrim {
        anchors.fill: parent
        anchors.topMargin: -24        // fade begins above the bar
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceLg
        anchors.rightMargin: Theme.spaceLg
        spacing: 0

        // -------------------------------------------------- row 1: seek --
        SeekBar {
            id: seekBar
            width: parent.width
            height: 26
            position: root.player ? root.player.position : 0
            duration: root.player ? root.player.duration : 0
            // Only seekable once we know how long the media is; a live stream
            // or a not-yet-parsed file renders as a plain inert track.
            enabled: root.player ? root.player.duration > 0 : false
            onSeekRequested: function(fraction) { Actions.seekFraction(fraction) }
            // Suspend the engine's position polling for the duration of the
            // drag, so the knob follows the pointer instead of snapping back
            // to whatever VLC last reported.
            onScrubStarted: Actions.beginScrub()
            onScrubEnded: Actions.endScrub()
        }

        // ----------------------------------------------- row 2: controls --
        Item {
            width: parent.width
            height: Theme.hitTarget

            // left cluster: transport proper
            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceXs

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
                    glyph: Glyphs.previous
                    tooltip: "Previous"
                    onClicked: Actions.previous()
                }
                IconButton {
                    glyph: Glyphs.rewind
                    tooltip: "Back 10s (\u2190)"
                    onClicked: Actions.seekRelative(-10000)
                }
                IconButton {
                    glyph: Glyphs.fastForward
                    tooltip: "Forward 10s (\u2192)"
                    onClicked: Actions.seekRelative(10000)
                }
                IconButton {
                    glyph: Glyphs.next
                    tooltip: "Next"
                    onClicked: Actions.next()
                }

                Item { width: Theme.spaceMd; height: 1 }

                VolumeControl {
                    id: volumeControl
                    anchors.verticalCenter: parent.verticalCenter
                    volume: root.player ? root.player.volume : 80
                    muted: root.player ? root.player.muted : false
                    onVolumeRequested: function(v) { Actions.setVolume(v) }
                    onMuteToggled: Actions.toggleMute()
                }

                // Remaining · playback · media — all three, always, in that
                // order. No toggle (see TimeDisplay.qml).
                TimeDisplay {
                    anchors.verticalCenter: parent.verticalCenter
                    elapsed: root.player ? root.player.time : 0
                    duration: root.player ? root.player.duration : 0
                }
            }

            // right cluster: options and view
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceXs

                // Show/hide the queue. The left dock had no on-screen toggle
                // at all — Ctrl+L was the only way to reach it, which is not
                // discoverable. This is a *trigger* for the existing action,
                // not a second implementation (§4.1).
                IconButton {
                    glyph: Glyphs.playlist
                    tooltip: "Playlist (Ctrl+L)"
                    active: root.playlistVisible
                    onClicked: Actions.toggleLeftPanel()
                }
                IconButton {
                    id: subsButton
                    glyph: Glyphs.subtitles
                    tooltip: "Speed, audio and subtitles"
                    active: trackPopover.opened || subDownload.opened
                    onClicked: trackPopover.opened ? trackPopover.close() : trackPopover.open()
                }
                IconButton {
                    glyph: root.repeatMode === 1 ? Glyphs.repeatOne : Glyphs.repeatAll
                    tooltip: root.repeatMode === 0 ? "Repeat off (L)"
                           : root.repeatMode === 1 ? "Repeat one (L)" : "Repeat all (L)"
                    active: root.repeatMode !== 0
                    onClicked: Actions.cycleRepeat()
                }
                IconButton {
                    glyph: Glyphs.shuffle
                    tooltip: "Shuffle"
                    active: root.shuffle
                    onClicked: Actions.toggleShuffle()
                }
                IconButton {
                    glyph: Glyphs.fullscreen
                    tooltip: "Fullscreen (F)"
                    onClicked: Actions.toggleFullscreen()
                }
            }
        }
    }

    TrackPopover {
        id: trackPopover

        // Parented to the subtitle button so positioning happens in its own
        // coordinate frame — no mapToItem race across nested Rows. The right
        // edge sits under the button, the bottom rests just above it.
        //
        // Popup coords are relative to `parent`, so `x = parent.width - width`
        // aligns the right edges; the shell's 860px minimum width (Shell.qml)
        // guarantees the 336px popover always fits, so no clamp is needed.
        parent: subsButton
        x: subsButton.width - width
        y: -implicitHeight - Theme.spaceSm
        maxHeight: root.windowHeight > 0 ? Math.max(320, root.windowHeight - 160) : 0

        rate: root.player ? root.player.rate : 1.0
        audioTracks: root.audioTracks
        subtitleTracks: root.embeddedSubtitleTracks
        localSubtitleTracks: root.localSubtitleTracks
        currentAudioId: root.currentAudioId
        currentSubtitleId: root.currentSubtitleId
        subtitleDelayMs: root.subtitleDelayMs
        hasVideo: root.hasVideo

        onDownloadRequested: {
            close();
            subDownload.open();
        }
    }

    SubtitleDownloadDialog {
        id: subDownload
        x: Math.max(Theme.spaceLg,
                    Math.min((root.width - width) / 2, root.width - width - Theme.spaceLg))
        y: -implicitHeight - Theme.spaceSm
        maxHeight: root.windowHeight > 0 ? Math.max(320, root.windowHeight - 160) : 0
    }
}
