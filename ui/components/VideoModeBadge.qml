import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The video-route badge — §V.7.
//
// A two-character read-out in the title bar saying which video path the media
// playing right now is actually on: "T" Turbo, "S" Soft, with an "A" prefix
// when *Auto* made the choice rather than the user.
//
// It reports the achieved route, never the request. A user who selected Turbo
// and got Soft — audio-only media, an unsupported system, a Turbo attempt that
// failed and fell back (§V.4) — sees "S", because a badge that claimed "T"
// while the CPU did the decoding would be lying about the one thing it exists
// to report. The reason lives in the hover tooltip, so the glance stays a
// glance and the explanation is one hover away.
//
// Deliberately *not* a button: it reports, it does not act. No click handler,
// no route to Settings — the dropdown that owns the setting is the only place
// the setting changes (§V.1).
Control {
    id: root

    //: "AT", "AS", "T" or "S" — see core/video_mode.badge().
    property string text: ""
    //: The full sentence shown on hover, reason included.
    property string tooltip: ""
    //: Turbo tints with the accent; Soft stays quiet. Soft is the ordinary,
    //: correct state for most media, so it must not read as a warning.
    readonly property bool turbo: root.text.slice(-1) === "T"

    //: Hover is the whole interaction, so an empty badge must not occupy space
    //: or swallow the pointer near the window buttons.
    visible: root.text !== ""
    enabled: visible

    padding: 0
    implicitWidth: Math.max(label.implicitWidth + Theme.spaceSm * 2, Theme.hitTarget * 0.7)
    implicitHeight: Math.round(Theme.hitTarget * 0.55)

    hoverEnabled: true

    background: Rectangle {
        radius: Theme.radiusPill
        color: hoverHandler.hovered ? Theme.glassFillHover : Theme.glassFill
        border.width: 1
        border.color: root.turbo ? Qt.alpha(Theme.accent, 0.45) : Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    contentItem: Text {
        id: label
        text: root.text
        // Tabular-ish spacing: "AT" and "S" differ by a character, and letter
        // spacing keeps the one-character form from looking like a stray mark.
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeTiny
        font.weight: Font.DemiBold
        font.letterSpacing: 0.8
        color: root.turbo ? Theme.accent : Theme.textMuted
        opacity: Theme.opacityRest
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    HoverHandler {
        id: hoverHandler
        cursorShape: Qt.ArrowCursor      // not clickable, so not a hand
    }

    ToolTip.visible: hoverHandler.hovered && root.tooltip.length > 0
    ToolTip.delay: 500
    ToolTip.text: root.tooltip
}
