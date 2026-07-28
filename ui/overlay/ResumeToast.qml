import QtQuick
import Halcyon.Ui

// The resume notice — §P1.5, "prompt if >30 s in and >5% remaining".
//
// **Not a modal.** The film is already playing, from the resume point, by the
// time this appears. A dialog that has to be dismissed before playback starts
// is worse than no resume: it puts a question between the user and the thing
// they double-clicked, and the answer is "yes, obviously" nine times in ten.
//
// So this is an *undo*, not a question. It states what happened — "Resumed from
// 24:31" — and offers the one action that is not the default. Ignore it and it
// fades; that is the correct outcome, reached by doing nothing.
//
// It sits in the top-left with the OSD's visual language (glass pill, same
// radius, same motion) but its own longer dwell: 800 ms is right for a volume
// bar you already know about, and far too short to read a sentence and decide
// to click a button.
Item {
    id: root

    property string label: ""
    //: Long enough to read the line, notice the button and reach it.
    property int dwellMs: 6000

    signal startOverRequested()

    visible: opacity > 0
    opacity: 0

    implicitWidth: pill.width
    implicitHeight: pill.height

    function show(text) {
        label = text;
        opacity = 1;
        dwell.restart();
    }

    function dismiss() {
        dwell.stop();
        opacity = 0;
    }

    Behavior on opacity {
        NumberAnimation { duration: Theme.durOsdFade; easing.type: Theme.easingOsd }
    }

    Timer {
        id: dwell
        interval: root.dwellMs
        onTriggered: root.opacity = 0
    }

    Rectangle {
        id: pill
        width: row.width + Theme.spaceLg * 2
        height: 40
        radius: Theme.radiusPill
        color: Qt.rgba(0.043, 0.055, 0.078, 0.88)
        border.width: 1
        border.color: Theme.glassBorder

        Row {
            id: row
            anchors.centerIn: parent
            spacing: Theme.spaceMd

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Glyphs.play
                font.family: Theme.fontFamilyIcons
                font.pixelSize: Theme.iconSize - 4
                color: Theme.accent
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.text
            }

            // The escape hatch. Deliberately the only button: "Resume" would be
            // a button for something that has already happened.
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: startText.width + Theme.spaceMd * 2
                height: 26
                radius: Theme.radiusSmall
                color: startMouse.containsMouse ? Theme.glassFillHover : Theme.glassFill
                border.width: 1
                border.color: startMouse.containsMouse ? Theme.accent : Theme.glassBorder

                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }

                Text {
                    id: startText
                    anchors.centerIn: parent
                    text: "Start over"
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: startMouse.containsMouse ? Theme.accent : Theme.textMuted
                }

                MouseArea {
                    id: startMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.startOverRequested();
                        root.dismiss();
                    }
                }
            }
        }
    }
}
