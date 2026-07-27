import QtQuick
import Halcyon.Ui
import Halcyon.Transport

// Local's control bar — §B.4, §P1.5.
//
// TWO ROWS, ~72px, arranged for Local's fourteen controls:
//
//   ●━━━━━━━━━━━━━━○···········································
//   ▶ ⏹ ⏮ ⏪ ⏩ ⏭   🔊━━━    12:34 / 45:67        ⚙ 🔁 🔀 ⛶
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
    property bool showRemaining: false
    property var audioTracks: []
    property var subtitleTracks: []
    property int currentAudioId: -1
    property int currentSubtitleId: -1
    property int subtitleDelayMs: 0

    // The bar must never auto-hide while the gear popover is open (§P1.4).
    readonly property bool popoverOpen: trackPopover.opened
    readonly property bool scrubbing: seekBar.scrubbing

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
            onSeekRequested: function(fraction) { Actions.seekFraction(fraction) }
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
                    anchors.verticalCenter: parent.verticalCenter
                    volume: root.player ? root.player.volume : 80
                    muted: root.player ? root.player.muted : false
                    onVolumeRequested: function(v) { Actions.setVolume(v) }
                    onMuteToggled: Actions.toggleMute()
                }

                TimeDisplay {
                    anchors.verticalCenter: parent.verticalCenter
                    elapsed: root.player ? root.player.time : 0
                    duration: root.player ? root.player.duration : 0
                    showRemaining: root.showRemaining
                    onToggled: root.showRemaining = !root.showRemaining
                }
            }

            // right cluster: options and view
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spaceXs

                IconButton {
                    id: gearButton
                    glyph: Glyphs.settings
                    tooltip: "Speed, audio and subtitles"
                    active: trackPopover.opened
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
        x: gearButton ? gearButton.x + root.width - width - Theme.spaceLg : 0
        y: -implicitHeight - Theme.spaceSm
        rate: root.player ? root.player.rate : 1.0
        audioTracks: root.audioTracks
        subtitleTracks: root.subtitleTracks
        currentAudioId: root.currentAudioId
        currentSubtitleId: root.currentSubtitleId
        subtitleDelayMs: root.subtitleDelayMs
    }
}
