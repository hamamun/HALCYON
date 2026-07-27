import QtQuick
import Halcyon.Ui

// The OSD — §6.2, §P1.5. Local only.
//
// A transient overlay drawn *in the scene graph over the video*. This is only
// possible because of §0.3 — with a native video window there is nothing to draw
// on top of.
//
// Behaviour that matters:
//   * 800 ms hold + 250 ms fade
//   * repeats RESET the timer instead of stacking
//   * never covers the subtitle safe area (bottom 20%)
//   * suppressed while a menu or panel has focus
//   * driven by ModeSpec.osd_enabled — M3U and Web never fire it
Item {
    id: root

    property bool enabled: true
    property bool suppressed: false     // set while a popover/menu owns focus

    // Bottom 20% is the subtitle safe area. Nothing here may enter it.
    readonly property real safeBottom: height * 0.20

    // ------------------------------------------------------------- API --
    // One entry point per shape of message; Actions.osd() routes here.
    function show(text, glyph) {
        if (!_can()) return;
        statusText.text = text || "";
        statusGlyph.text = glyph || "";
        statusPill.visible = true;
        statusPill.opacity = 1;
        statusTimer.restart();          // restart, not stack
    }

    function showLevel(text, glyph, level) {
        if (!_can()) return;
        levelText.text = text || "";
        levelGlyph.text = glyph || "";
        levelBar.value = Math.max(0, Math.min(1, level));
        levelPill.visible = true;
        levelPill.opacity = 1;
        levelTimer.restart();
    }

    function showGlyph(glyph) {
        if (!_can()) return;
        bigGlyph.text = glyph || "";
        bigGlyph.visible = true;
        bigGlyph.opacity = 1;
        bigGlyph.scale = 0.8;
        bigIn.restart();
        bigTimer.restart();
    }

    function _can() {
        return root.enabled && !root.suppressed;
    }

    // ----------------------------------------------- top-left status line --
    Rectangle {
        id: statusPill
        visible: false
        opacity: 0
        x: Theme.spaceXl
        y: Theme.spaceXl
        width: statusRow.implicitWidth + Theme.spaceLg * 2
        height: 40
        radius: Theme.radiusPill
        color: Qt.rgba(0.043, 0.055, 0.078, 0.72)
        border.width: 1
        border.color: Theme.glassBorder

        Behavior on opacity {
            NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
        }

        Row {
            id: statusRow
            anchors.centerIn: parent
            spacing: Theme.spaceSm

            Text {
                id: statusGlyph
                anchors.verticalCenter: parent.verticalCenter
                font.pixelSize: Theme.iconSize
                color: Theme.accent
                visible: text.length > 0
            }
            Text {
                id: statusText
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeOsd
                color: Theme.text
            }
        }

        Timer {
            id: statusTimer
            interval: Theme.durOsdHold
            onTriggered: statusPill.opacity = 0
        }
        onOpacityChanged: if (opacity === 0) hideDelay.start()
        Timer {
            id: hideDelay
            interval: Theme.durOsdFade
            onTriggered: if (statusPill.opacity === 0) statusPill.visible = false
        }
    }

    // ------------------------------------------- top-left level indicator --
    Rectangle {
        id: levelPill
        visible: false
        opacity: 0
        x: Theme.spaceXl
        y: Theme.spaceXl
        width: 220
        height: 56
        radius: Theme.radiusControl
        color: Qt.rgba(0.043, 0.055, 0.078, 0.72)
        border.width: 1
        border.color: Theme.glassBorder

        Behavior on opacity {
            NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
        }

        Column {
            anchors.centerIn: parent
            spacing: Theme.spaceSm
            width: parent.width - Theme.spaceLg * 2

            Row {
                spacing: Theme.spaceSm
                Text {
                    id: levelGlyph
                    font.pixelSize: Theme.iconSize
                    color: Theme.accent
                }
                Text {
                    id: levelText
                    anchors.verticalCenter: parent.verticalCenter
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }
            }

            Rectangle {
                id: levelBar
                property real value: 0
                width: parent.width
                height: 4
                radius: 2
                color: Theme.trackRest

                Rectangle {
                    width: parent.width * parent.value
                    height: parent.height
                    radius: parent.radius
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.accent }
                        GradientStop { position: 1.0; color: Theme.accentAlt }
                    }
                    Behavior on width {
                        NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                    }
                }
            }
        }

        Timer {
            id: levelTimer
            interval: Theme.durOsdHold
            onTriggered: levelPill.opacity = 0
        }
        onOpacityChanged: if (opacity === 0) levelHide.start()
        Timer {
            id: levelHide
            interval: Theme.durOsdFade
            onTriggered: if (levelPill.opacity === 0) levelPill.visible = false
        }
    }

    // -------------------------------------------------- centre big glyph --
    // Vertically centred in the area ABOVE the subtitle safe zone, never in it.
    Text {
        id: bigGlyph
        visible: false
        opacity: 0
        anchors.horizontalCenter: parent.horizontalCenter
        y: (parent.height - root.safeBottom) / 2 - height / 2
        font.pixelSize: 72
        color: Theme.text

        Behavior on opacity {
            NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
        }

        NumberAnimation {
            id: bigIn
            target: bigGlyph
            property: "scale"
            from: 0.8
            to: 1.0
            duration: Theme.durNormal
            easing.type: Theme.easing
        }

        Timer {
            id: bigTimer
            interval: 450          // play/pause glyphs read faster than text
            onTriggered: bigGlyph.opacity = 0
        }
        onOpacityChanged: if (opacity === 0) bigHide.start()
        Timer {
            id: bigHide
            interval: Theme.durOsdFade
            onTriggered: if (bigGlyph.opacity === 0) bigGlyph.visible = false
        }
    }
}
