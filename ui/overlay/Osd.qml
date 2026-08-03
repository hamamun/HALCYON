import QtQuick
import Halcyon.Ui

// The OSD — §6.2, §P1.5. Local media feedback + M3U transport feedback.
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
//   * driven by ModeSpec.osd_enabled — Local and M3U may use it; Web does not
Item {
    id: root

    // Named osdEnabled, not enabled: Item already has an `enabled` property, and
    // shadowing it both trips a QML warning and silently changes input handling
    // for the whole subtree.
    property bool osdEnabled: true
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

    // ------------------------------------------------------- resume toast --
    // "Resuming from 24:31" with a Start Over button (§P1.5, plan §6.2).
    //
    // Held far longer than the other pills because it is the only one that
    // asks the user for a decision — 800 ms is enough to read a volume level,
    // not enough to notice a button, move to it and click it.
    signal startOverClicked(string path)

    //: The file the visible toast refers to. Captured when the toast is shown
    //: rather than read live, so a queue advancing under a still-visible toast
    //: cannot make Start Over rewind the wrong file.
    property string resumePath: ""

    // Lets the now-playing toast yield when an open also carries a resume:
    // both pills live top-left, so firing both would draw them on each other.
    readonly property bool resumeShowing: resumePill.opacity > 0

    //: How the position is rendered. Supplied by the shell so the toast uses
    //: the same formatter as the clock and the seek bar (§4.1) — the local
    //: version this replaced printed 1:14:27 as "74:27" and 0:42 as "42".
    property var formatTime: function(ms) { return Math.round(ms / 1000) + "s" }

    function showResume(path, positionMs) {
        if (!_can()) return;
        root.resumePath = path || "";
        resumeText.text = "Resuming from " + root.formatTime(positionMs);
        resumePill.visible = true;
        resumePill.opacity = 1;
        resumeTimer.restart();
    }

    //: Dismiss without acting — used when the media changes under the toast.
    function hideResume() {
        resumeTimer.stop();
        resumePill.opacity = 0;
    }

    function _can() {
        return root.osdEnabled && !root.suppressed;
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
                font.family: Theme.fontFamilyIcons
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

    // -------------------------------------------------- resume toast pill --
    Rectangle {
        id: resumePill
        visible: false
        opacity: 0
        x: Theme.spaceXl
        y: Theme.spaceXl
        width: resumeRow.implicitWidth + Theme.spaceLg * 2
        height: 40
        radius: Theme.radiusPill
        color: Qt.rgba(0.043, 0.055, 0.078, 0.85)
        border.width: 1
        border.color: Theme.glassBorder

        Behavior on opacity {
            NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
        }

        Row {
            id: resumeRow
            anchors.centerIn: parent
            spacing: Theme.spaceSm

            Text {
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontFamilyIcons
                font.pixelSize: Theme.iconSize
                color: Theme.accent
                // From the shared set, never a literal codepoint (§B.1). The
                // hardcoded \ue8b5 this replaces was not the play glyph at all.
                text: Glyphs.play
            }

            Text {
                id: resumeText
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeOsd
                color: Theme.text
            }

            // Start Over button
            Rectangle {
                width: startOverText.implicitWidth + Theme.spaceLg
                height: 26
                radius: Theme.radiusSmall
                color: startOverArea.containsMouse ? Theme.glassFillHover
                                                   : Theme.glassFill
                border.width: 1
                border.color: startOverArea.containsMouse ? Theme.glassBorderStrong
                                                          : Theme.glassBorder

                anchors.verticalCenter: parent.verticalCenter

                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }

                Text {
                    id: startOverText
                    anchors.centerIn: parent
                    text: "Start Over"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                }

                MouseArea {
                    id: startOverArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.resumePath)
                            root.startOverClicked(root.resumePath);
                        root.hideResume();
                    }
                }
            }
        }

        Timer {
            id: resumeTimer
            // Long enough to read the toast and click the button. The other
            // pills are transient; this one is a prompt.
            interval: Theme.durOsdHoldAction
            onTriggered: resumePill.opacity = 0
        }

        onOpacityChanged: if (opacity === 0) resumeHideDelay.start()

        Timer {
            id: resumeHideDelay
            interval: Theme.durOsdFade
            onTriggered: if (resumePill.opacity === 0) resumePill.visible = false
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
                    font.family: Theme.fontFamilyIcons
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
        font.family: Theme.fontFamilyIcons
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
