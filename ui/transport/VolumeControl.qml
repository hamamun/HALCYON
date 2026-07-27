import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// Mute/level icon plus a slider. Clicking the icon toggles mute, and the icon
// *is* the level readout — one target, no separate indicator.
//
// The slider used to be hidden until hover ("icon only at rest, expands
// rightward"). Two things were wrong with that in practice:
//
//   1. It never actually expanded. The hover MouseArea sat *behind* an
//      IconButton, and AbstractButton has hoverEnabled: true, so the button
//      swallowed the hover events. `hoverArea.containsMouse` stayed false
//      forever and the slider's container stayed 0px wide — the reported
//      "no volume slider".
//   2. Even working, a volume control you cannot see is a volume control most
//      people never find.
//
// So the slider is always present. Hover still has an effect — the track
// brightens and the handle appears — but visibility no longer depends on it.
//
// Used by Local and by M3U (§P2.3).
Item {
    id: root

    property int volume: 80
    property bool muted: false
    property int sliderWidth: 84

    signal volumeRequested(int value)
    signal muteToggled()

    implicitHeight: Theme.hitTarget
    implicitWidth: Theme.hitTarget + sliderWidth + Theme.spaceXs
    width: implicitWidth
    height: implicitHeight

    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        spacing: Theme.spaceXs

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            glyph: root.muted || root.volume === 0 ? Glyphs.volumeMute
                 : root.volume < 34 ? Glyphs.volumeLow
                 : root.volume < 67 ? Glyphs.volumeMid
                 : Glyphs.volumeHigh
            tooltip: root.muted ? "Unmute (M)" : "Mute (M)"
            active: root.muted
            activeColor: Theme.textMuted
            onClicked: root.muteToggled()
        }

        HSlider {
            id: slider
            anchors.verticalCenter: parent.verticalCenter
            width: root.sliderWidth
            from: 0
            to: 100
            // A muted player reads as 0 so the slider agrees with the icon,
            // but the underlying volume is not destroyed — unmuting restores it.
            value: root.muted ? 0 : root.volume
            trackHeight: 4
            handleSize: 11
            // `moved` fires only for user interaction, never for the binding
            // above — so a volume change arriving from a hotkey or the OSD
            // cannot echo back out and fight the value it just set.
            onMoved: root.volumeRequested(Math.round(value))
        }
    }
}
