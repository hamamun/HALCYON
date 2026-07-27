import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// THREE READOUTS, ALWAYS VISIBLE, ALWAYS IN THIS ORDER:
//
//     -01:23   ·   04:56   ·   06:19
//     remaining    playback    media
//
// This replaces the old click-to-toggle elapsed↔remaining control. The toggle
// was a deliberate design choice (one target, two states) but it failed the
// only test that matters: you could not see remaining time and elapsed time at
// the same moment, and most people never discovered the readout was clickable
// at all. Showing all three costs about sixty pixels and removes a hidden mode.
//
// There is no interaction here now — it is a readout, not a control, so it has
// no MouseArea and no cursor change to imply otherwise.
Item {
    id: root

    property int elapsed: 0        // ms, playback time
    property int duration: 0       // ms, media time

    // Remaining never goes negative, and reads 0 until a duration is known.
    readonly property int remaining: duration > 0
                                     ? Math.max(0, duration - elapsed)
                                     : 0

    implicitWidth: layout.implicitWidth + Theme.spaceMd
    implicitHeight: Theme.hitTarget
    width: implicitWidth
    height: implicitHeight

    // Zero-padded so the row does not jitter as digits change width. Mono font
    // does most of the work; this handles the minute rollover.
    function format(ms) {
        if (!isFinite(ms) || ms < 0) ms = 0;
        var total = Math.floor(ms / 1000);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = (m < 10 ? "0" : "") + m;
        var ss = (s < 10 ? "0" : "") + s;
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }

    Row {
        id: layout
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceSm
        spacing: Theme.spaceSm

        // -------------------------------------------------- remain time --
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "-" + root.format(root.remaining)
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textMuted
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "\u00B7"
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
        }

        // ------------------------------------------------ playback time --
        // The one you look at most, so it gets full-strength text.
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.format(root.elapsed)
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.text
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "\u00B7"
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textFaint
        }

        // --------------------------------------------------- media time --
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.format(root.duration)
            font.family: Theme.fontFamilyMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textMuted
        }
    }
}
