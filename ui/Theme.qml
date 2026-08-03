pragma Singleton
import QtQuick

// Design tokens — §7. Aurora glass.
//
// THE RULE (§B.1): nothing anywhere else defines a colour, a blur radius, a
// corner radius, a duration or an easing curve. If a component needs a value
// that is not here, the value belongs here, not in the component.
//
// This is what makes three modes look like one product instead of three
// programs wearing the same skin.
QtObject {
    id: theme

    // ---------------------------------------------------------------- base --
    readonly property color base:          "#0B0E14"
    readonly property color baseElevated:  "#111621"
    readonly property color scrimTop:      "#00000000"
    readonly property color scrimBottom:   "#B8000000"   // rgba(0,0,0,0.72)

    // --------------------------------------------------------------- glass --
    readonly property color glassFill:     Qt.rgba(1, 1, 1, 0.06)
    readonly property color glassFillHover: Qt.rgba(1, 1, 1, 0.10)
    readonly property color glassFillPressed: Qt.rgba(1, 1, 1, 0.14)
    readonly property color glassBorder:   Qt.rgba(1, 1, 1, 0.12)
    readonly property color glassBorderStrong: Qt.rgba(1, 1, 1, 0.20)

    // ---------------------------------------------------------------- text --
    readonly property color text:          "#F2F5F9"
    readonly property color textMuted:     Qt.rgba(1, 1, 1, 0.62)
    readonly property color textFaint:     Qt.rgba(1, 1, 1, 0.38)
    readonly property color textOnAccent:  "#06120F"

    // -------------------------------------------------------------- accent --
    readonly property color accent:        "#5EEAD4"
    readonly property color accentAlt:     "#A78BFA"
    readonly property color accentDim:     Qt.rgba(0.369, 0.918, 0.831, 0.24)
    readonly property Gradient accentGradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: theme.accent }
        GradientStop { position: 1.0; color: theme.accentAlt }
    }

    // ------------------------------------------------------------- status --
    readonly property color danger:        "#F87171"
    readonly property color warning:       "#FBBF24"
    readonly property color success:       "#4ADE80"

    // --------------------------------------------------------- transport ---
    readonly property color trackRest:     Qt.rgba(1, 1, 1, 0.16)
    readonly property color trackBuffered: Qt.rgba(1, 1, 1, 0.28)

    // ----------------------------------------------------------------- blur --
    readonly property real blurPanel:  32
    readonly property real blurModal:  48
    readonly property real blurOsd:    8

    // --------------------------------------------------------------- radius --
    readonly property real radiusPanel:   18
    readonly property real radiusControl: 12
    readonly property real radiusPill:    999
    readonly property real radiusSmall:   8

    // -------------------------------------------------------------- spacing --
    readonly property real spaceXs: 4
    readonly property real spaceSm: 8
    readonly property real spaceMd: 12
    readonly property real spaceLg: 16
    readonly property real spaceXl: 24

    // ------------------------------------------------------------- metrics --
    readonly property real titleBarHeight:   44
    readonly property real leftPanelWidth:   340
    readonly property real rightPanelWidth:  320
    readonly property real rightPanelExpandedWidth: 560
    readonly property real hitTarget:        40      // §B.1 — every icon button
    readonly property real iconSize:         20
    // The "available" indicator dot on a transport button (subtitles/lyrics).
    // Small enough to read as a hint, large enough to spot at a glance.
    readonly property real badgeSize:        7
    readonly property real listRowHeight:    38
    readonly property real toolbarRowHeight: 44
    readonly property real seekBarRest:      4       // §P1.5
    readonly property real seekBarHover:     6

    // ----------------------------------------------------------------- type --
    readonly property string fontFamily: "Segoe UI Variable Text, Segoe UI, Inter, sans-serif"
    readonly property string fontFamilyMono: "Cascadia Mono, Consolas, monospace"

    // The icon font — §B.1. Every Glyphs.* codepoint MUST be rendered with
    // this family and nothing else.
    //
    // Glyphs.qml holds private-use codepoints (U+E7xx…) from Segoe Fluent
    // Icons. Drawing them with `fontFamily` asks Segoe UI *Text* for a
    // character it does not have, so Qt walks the entire installed font list
    // hunting for a fallback. That is the source of the
    //
    //     qt.text.font.db: OpenType support missing for "Tahoma", script 12
    //     ... Arial / MS UI Gothic / SimSun / Segoe UI Emoji / Segoe UI Symbol
    //
    // wall in the log — one line per candidate font, per glyph — and the
    // search ends in a blank box or nothing at all, which is why transport
    // icons were missing. Naming the icon font directly fixes both.
    readonly property string fontFamilyIcons: "Segoe Fluent Icons, Segoe MDL2 Assets"
    readonly property int fontSizeTiny:  10
    readonly property int fontSizeSmall: 12
    readonly property int fontSizeBody:  13
    readonly property int fontSizeLarge: 16
    readonly property int fontSizeTitle: 20
    readonly property int fontSizeOsd:   15
    readonly property int weightNormal:  Font.Normal
    readonly property int weightMedium:  Font.Medium
    readonly property int weightBold:    Font.DemiBold

    // --------------------------------------------------------------- motion --
    // §B.1: nothing uses a different duration or curve without a reason.
    readonly property int durFast:    120
    readonly property int durNormal:  220        // the Halcyon duration
    readonly property int durSlow:    380
    readonly property int durOsdFade: 250
    readonly property int durOsdHold: 800
    //: Hold time for an OSD pill that carries a control the user may click
    //: (the resume toast's Start Over). A transient pill is read; this one has
    //: to be noticed, aimed at and hit.
    readonly property int durOsdHoldAction: 8000
    readonly property int durAutoHide: 180
    readonly property int easing:     Easing.OutCubic
    readonly property int easingOsd:  Easing.OutQuad

    // --------------------------------------------------------------- opacity --
    readonly property real opacityDisabled: 0.35
    readonly property real opacityHover:    1.0
    readonly property real opacityRest:     0.82
}
