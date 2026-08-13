import QtQuick
import QtQuick.Window
import Halcyon.Ui

// The window-button cluster — one source of truth for the video-route badge
// and the Settings / Mini / Minimise / Maximise / Close controls.
//
// Historically this Row lived only inside TitleBar.qml. Borderless mode (§ the
// borderless toggle) removes the title bar, so the very same controls have to
// appear in a floating overlay (Local/M3U) and inline in the Web tab strip.
// Extracting it here means every home renders *this* component — not a
// lookalike — so a change to the close button, the badge slot or the spacing
// happens once and shows up everywhere (§B.1).
//
// It is deliberately dumb: it reads App/Player only to decide when the badge
// and the Mini-Mode affordance apply, and it routes every click through the
// same Actions entries the title bar always used. It never owns window state.
Row {
    id: root

    // Which mode is on screen — decides badge visibility and Mini availability,
    // exactly as the title bar computed them.
    property string activeMode: ""

    // Injectable sources so the file still loads standalone (qmlscene, tests),
    // matching the pattern TitleBar/NowPlayingCard already use.
    property var app: typeof App !== "undefined" ? App : null
    property var player: typeof Player !== "undefined" ? Player : null

    // The window this cluster controls. Provided by the host so a Window.window
    // lookup is not required (the overlay may live in a different item tree).
    property var win: null

    // Lets the host hide the Mini-Mode button where it makes no sense (e.g. the
    // Web tab strip, which is never a Local playback surface).
    property bool showMiniButton: true

    spacing: 0

    readonly property bool hasMedia:
        player && (player.duration > 0
                   || (player.currentMedia !== undefined
                       && player.currentMedia !== null
                       && player.currentMedia !== ""))
    readonly property bool isFullscreen: !!win && win.fullscreen
    readonly property bool miniEnabled:
        activeMode === "local" && hasMedia && !isFullscreen

    // Same rule as the title bar: the route badge is a playback read-out, so it
    // shows only on a mode that has a player (Local/M3U) with media loaded.
    readonly property bool videoBadgeVisible:
        (activeMode === "local" || activeMode === "m3u") && hasMedia && !isFullscreen

    VideoModeBadge {
        anchors.verticalCenter: parent.verticalCenter
        text: root.videoBadgeVisible && root.app ? root.app.videoModeBadge : ""
        tooltip: root.app ? root.app.videoModeTooltip : ""
    }
    Item {
        width: root.videoBadgeVisible ? Theme.spaceSm : 0
        height: 1
    }

    IconButton {
        glyph: Glyphs.settings
        tooltip: "Settings"
        onClicked: Actions.showSettings()
    }
    Item { width: root.showMiniButton ? Theme.spaceSm : 0; height: 1 }

    // Mini Mode toggle — v1.1 §M.5 — Local + media only. Hidden entirely where
    // the host opts out (Web).
    IconButton {
        visible: root.showMiniButton
        width: root.showMiniButton ? implicitWidth : 0
        glyph: Glyphs.miniMode
        tooltip: root.miniEnabled ? "Mini Mode" : "Mini Mode (Local playback only)"
        showRing: false
        enabled: root.miniEnabled
        onClicked: Actions.toggleMiniMode()
    }

    IconButton {
        glyph: Glyphs.minimize
        tooltip: "Minimise"
        showRing: false
        onClicked: Actions.minimizeWindow()
    }
    IconButton {
        glyph: root.win && root.win.visibility === Window.Maximized
               ? Glyphs.restore : Glyphs.maximize
        tooltip: root.win && root.win.visibility === Window.Maximized
                 ? "Restore" : "Maximise"
        showRing: false
        onClicked: Actions.toggleMaximized()
    }
    IconButton {
        glyph: Glyphs.close
        tooltip: "Close"
        showRing: false
        iconColor: Theme.danger
        onClicked: Actions.closeWindow()

        background: Rectangle {
            radius: Theme.radiusControl
            color: parent.pressed ? Qt.darker(Theme.danger, 1.3)
                 : parent.hovered ? Theme.danger : "transparent"
            Behavior on color {
                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }
    }
}
