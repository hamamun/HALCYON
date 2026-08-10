import QtQuick
import QtQuick.Effects
import Halcyon.Ui

// Aurora — §7. Deep charcoal base with slow-drifting colour fields.
//
// Cheap on purpose: three large blurred blobs on a very slow loop. It sits
// behind video (invisible while playing) and behind the idle state (where it
// does the work), so it must never cost frames during playback.
Item {
    id: root

    property bool animate: true
    // Dark mode is flat, static black — no colour, no motion, no blur pass
    // to pay for. The field/vignette below simply don't run.
    readonly property bool darkMode: Theme.darkMode

    Rectangle {
        anchors.fill: parent
        color: Theme.base
    }

    Item {
        id: field
        anchors.fill: parent
        opacity: 0.5
        visible: false

        Rectangle {
            width: parent.width * 0.9
            height: width
            radius: width / 2
            color: Theme.accent
            opacity: 0.30
            x: -parent.width * 0.2
            y: -parent.height * 0.3

            SequentialAnimation on x {
                running: root.animate && !root.darkMode
                loops: Animation.Infinite
                NumberAnimation { to: field.width * 0.25; duration: 32000; easing.type: Easing.InOutSine }
                NumberAnimation { to: -field.width * 0.2; duration: 32000; easing.type: Easing.InOutSine }
            }
        }

        Rectangle {
            width: parent.width * 0.75
            height: width
            radius: width / 2
            color: Theme.accentAlt
            opacity: 0.28
            x: parent.width * 0.45
            y: parent.height * 0.35

            SequentialAnimation on y {
                running: root.animate && !root.darkMode
                loops: Animation.Infinite
                NumberAnimation { to: field.height * 0.05; duration: 41000; easing.type: Easing.InOutSine }
                NumberAnimation { to: field.height * 0.4;  duration: 41000; easing.type: Easing.InOutSine }
            }
        }

        Rectangle {
            width: parent.width * 0.6
            height: width
            radius: width / 2
            color: "#2563EB"
            opacity: 0.22
            x: parent.width * 0.1
            y: parent.height * 0.55

            SequentialAnimation on x {
                running: root.animate && !root.darkMode
                loops: Animation.Infinite
                NumberAnimation { to: field.width * 0.5;  duration: 55000; easing.type: Easing.InOutSine }
                NumberAnimation { to: field.width * 0.05; duration: 55000; easing.type: Easing.InOutSine }
            }
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: field
        visible: !root.darkMode
        blurEnabled: true
        blur: 1.0
        blurMax: 64
        autoPaddingEnabled: false
    }

    // Vignette keeps the centre calm so content reads clearly over it.
    // Skipped in Dark mode — the base rectangle above is already flat black.
    Rectangle {
        anchors.fill: parent
        visible: !root.darkMode
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.043, 0.055, 0.078, 0.35) }
            GradientStop { position: 0.5; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0.043, 0.055, 0.078, 0.55) }
        }
    }
}
