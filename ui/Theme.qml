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

    // ------------------------------------------------------------- mode ----
    // §Appearance — Color (default, the animated Aurora look) or Dark (full
    // black, glossy-glass, monochrome). One flag drives every token below;
    // nothing else in the app should ever branch on it directly (§B.1).
    property bool darkMode: (typeof Settings !== "undefined" && Settings)
                             ? Settings.get("ui.theme", "color") === "dark"
                             : false

    // Live updates: Settings.get() is a plain call, not a bindable property,
    // so QML would otherwise only read it once at startup. Listen for the
    // one key that matters and flip the flag — every color below is a normal
    // binding on `darkMode` and repaints itself automatically.
    property QtObject _themeWatcher: Connections {
        target: (typeof Settings !== "undefined") ? Settings : null
        function onChanged(key, value) {
            if (key === "ui.theme")
                theme.darkMode = (value === "dark")
        }
    }

    // ---------------------------------------------------------------- base --
    property color base:          darkMode ? "#000000" : "#0B0E14"
    property color baseElevated:  darkMode ? "#0A0A0A" : "#111621"
    readonly property color scrimTop:      "#00000000"
    readonly property color scrimBottom:   "#B8000000"   // rgba(0,0,0,0.72)

    // --------------------------------------------------------------- glass --
    // Same translucent-white recipe in both modes — it is what reads as a
    // frosted, glossy surface over whatever sits behind it, colour or black.
    readonly property color glassFill:     Qt.rgba(1, 1, 1, 0.06)
    readonly property color glassFillHover: Qt.rgba(1, 1, 1, 0.10)
    readonly property color glassFillPressed: Qt.rgba(1, 1, 1, 0.14)
    readonly property color glassBorder:   Qt.rgba(1, 1, 1, 0.12)
    readonly property color glassBorderStrong: Qt.rgba(1, 1, 1, 0.20)
    // When there is nothing to blur (Turbo's native video HWND), the 6%
    // glass tint is invisible over a bright picture. Docks and the
    // transport bar use this instead so text and controls stay readable.
    property color glassFillSolid: darkMode ? Qt.rgba(0, 0, 0, 0.88)
                                            : Qt.rgba(0.043, 0.055, 0.078, 0.88)

    // ---------------------------------------------------------------- text --
    property color text:          darkMode ? "#EDEDED" : "#F2F5F9"
    readonly property color textMuted:     Qt.rgba(1, 1, 1, 0.62)
    readonly property color textFaint:     Qt.rgba(1, 1, 1, 0.38)
    // Sits on top of `accent` — accent goes light grey/white in Dark mode,
    // so this has to flip dark for the same contrast Color mode gets.
    property color textOnAccent:  darkMode ? "#101010" : "#06120F"

    // -------------------------------------------------------------- accent --
    // Dark mode is monochrome by design — no teal/purple, soft white-grey
    // only. This is what the seek bar, volume slider, toggles and every
    // "active/selected" state read their colour from.
    property color accent:        darkMode ? "#E4E4E4" : "#5EEAD4"
    property color accentAlt:     darkMode ? "#AFAFAF" : "#A78BFA"
    property color accentDim:     darkMode ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(0.369, 0.918, 0.831, 0.24)
    readonly property Gradient accentGradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: theme.accent }
        GradientStop { position: 1.0; color: theme.accentAlt }
    }

    // ------------------------------------------------------------- status --
    // Left as-is on purpose: these carry meaning (error/warn/success), not
    // decoration, in both modes.
    readonly property color danger:        "#F87171"
    readonly property color warning:       "#FBBF24"
    readonly property color success:       "#4ADE80"

    // --------------------------------------------------------- transport ---
    // The seek bar and volume slider container/fill — soft white-grey,
    // a touch brighter than Color mode so it still reads clearly on
    // true black (§ progress/volume bars, fullscreen + mini mode).
    property color trackRest:     darkMode ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.16)
    property color trackBuffered: darkMode ? Qt.rgba(1, 1, 1, 0.36) : Qt.rgba(1, 1, 1, 0.28)

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
    //: Hold time for the transient pills (status text + volume level).
    //: Long enough to read a seek readout like "1:23:45 / 2:00:00"; repeats
    //: restart the timer, so rapid actions keep the pill alive while used.
    readonly property int durOsdHold: 1500
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
