import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The one button — §B.1.
//
// A play button in M3U is *this component* with the same icon, size and hover
// behaviour as Local's. Not a lookalike: the same file. 40x40 hit target, glass
// hover ring, 220 ms OutCubic, tooltip on hover — everywhere, forever.
AbstractButton {
    id: root

    property string glyph: ""              // see ui/components/Glyphs.qml
    // True when `glyph` is a plain Unicode text character (e.g. "›" U+203A)
    // rather than an icon-font codepoint.  The label then renders in the
    // regular UI text font instead of the icon font.  Needed because some
    // codepoints map to *different* glyphs in Segoe MDL2 Assets and Segoe
    // Fluent Icons — E76C is "ChevronRight" in MDL2 (Windows 10) but a
    // euro-like symbol in Fluent Icons (Windows 11) — while a standard text
    // character such as "›" renders as the same clean shape everywhere.
    // Bold + ~4/3 size keeps it optically balanced with the surrounding
    // icon-font glyphs (same treatment as the M3U section-header arrow).
    property bool plainTextGlyph: false
    property string tooltip: ""
    property bool active: false            // "on" state, e.g. shuffle enabled
    property real iconSize: Theme.iconSize
    property color iconColor: Theme.text
    property color activeColor: Theme.accent
    property bool showRing: true
    // A small "something is available" dot in the top-right corner — used by
    // the transport bar's subtitle and lyrics buttons to advertise content the
    // user has not opened yet. Off by default so every other IconButton is
    // unchanged; the dot only appears where a caller opts in.
    property bool showDot: false
    // Colour of the dot. Defaults to the accent so the two transport badges
    // share one look; a caller may override it (e.g. to differentiate kinds).
    property color dotColor: Theme.accent

    implicitWidth: Theme.hitTarget
    implicitHeight: Theme.hitTarget
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    opacity: enabled ? 1.0 : Theme.opacityDisabled

    background: Rectangle {
        anchors.fill: parent
        radius: Theme.radiusControl
        visible: root.showRing
        color: root.pressed ? Theme.glassFillPressed
             : root.hovered ? Theme.glassFillHover
             : "transparent"
        border.width: root.hovered || root.active ? 1 : 0
        border.color: root.active ? Theme.accentDim : Theme.glassBorder

        Behavior on color {
            ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }

    contentItem: Item {
        Text {
            anchors.centerIn: parent
            text: root.glyph
            font.family: root.plainTextGlyph ? Theme.fontFamily : Theme.fontFamilyIcons
            font.pixelSize: root.plainTextGlyph ? Math.round(root.iconSize * 4 / 3)
                                                : root.iconSize
            font.weight: root.plainTextGlyph ? Font.Bold : Font.Normal
            color: root.active ? root.activeColor
                 : root.hovered ? Theme.text
                 : Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, Theme.opacityRest)
            scale: root.pressed ? 0.90 : 1.0

            Behavior on color {
                ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
            Behavior on scale {
                NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
            }
        }
    }

    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.delay: 500
    ToolTip.text: tooltip

    // The availability dot. Anchored to the button's own top-right corner and
    // raised above background/contentItem so it is never covered. A thin ring
    // in the base colour keeps it legible over a bright video frame; the dot
    // itself is the accent. Fades in/out with the same fast curve as the rest
    // of the button so it never pops.
    Rectangle {
        id: availabilityDot
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: Theme.spaceXs
        anchors.rightMargin: Theme.spaceXs
        width: Theme.badgeSize
        height: Theme.badgeSize
        radius: width / 2
        color: root.dotColor
        border.width: 1
        border.color: Theme.base
        z: 1

        opacity: root.showDot ? 1.0 : 0.0
        visible: opacity > 0.0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
        }
    }
}
