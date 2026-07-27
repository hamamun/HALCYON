import QtQuick
import Halcyon.Ui

// Shared transport part — §B.4.
//
// Icon only at rest; the slider expands rightward on hover (§P1.5). The icon
// reflects both level and mute state, and clicking it toggles mute — one
// target, and the icon *is* the state readout.
//
// Used by Local and by M3U. M3U was missing volume in earlier plan drafts; that
// was an oversight (§P2.3), and the fix is simply that M3U's bar includes this
// same part.
Item {
    id: root

    property int volume: 80
    property bool muted: false
    property int expandedWidth: 92

    signal volumeRequested(int value)
    signal muteToggled()

    readonly property bool expanded: hoverArea.containsMouse || slider.pressed

    implicitHeight: Theme.hitTarget
    implicitWidth: Theme.hitTarget + (expanded ? expandedWidth : 0)
    width: implicitWidth

    Behavior on width {
        NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
    }

    MouseArea {
        id: hoverArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }

    Row {
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0

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

        Item {
            width: root.expanded ? root.expandedWidth : 0
            height: Theme.hitTarget
            clip: true
            opacity: root.expanded ? 1 : 0

            Behavior on width {
                NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
            }
            Behavior on opacity {
                NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
            }

            HSlider {
                id: slider
                anchors.verticalCenter: parent.verticalCenter
                width: root.expandedWidth - Theme.spaceSm
                from: 0
                to: 100
                value: root.muted ? 0 : root.volume
                trackHeight: 4
                handleSize: 11
                onMoved: root.volumeRequested(Math.round(value))
            }
        }
    }
}
