import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The right dock — Info / Lyrics / Equalizer (§P1.5).
//
// Shared, not Local's: M3U reaches the *same* equalizer through the *same*
// panel via Ctrl+I (§P2.4). One implementation, reached the same way from every
// mode — not a copy per mode.
Item {
    id: root

    property bool open: false
    property Item blurSource: null
    property int currentTab: 0        // 0 Info, 1 Lyrics, 2 Equalizer

    width: open ? Theme.rightPanelWidth : 0
    clip: true
    visible: width > 0

    Behavior on width {
        NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
    }

    GlassPanel {
        width: Theme.rightPanelWidth
        height: parent.height
        blurSource: root.blurSource
        radius: 0
        showBorder: false

        Rectangle {
            anchors.left: parent.left
            width: 1
            height: parent.height
            color: Theme.glassBorder
        }

        // ------------------------------------------------------- tabs --
        PanelToolbar {
            id: tabs
            width: parent.width
            anchors.top: parent.top
            alignment: Qt.AlignHCenter

            Repeater {
                model: [
                    { label: "Info",      glyph: Glyphs.info },
                    { label: "Lyrics",    glyph: Glyphs.lyrics },
                    { label: "Equalizer", glyph: Glyphs.equalizer }
                ]

                delegate: IconButton {
                    required property var modelData
                    required property int index
                    glyph: modelData.glyph
                    tooltip: modelData.label
                    active: root.currentTab === index
                    onClicked: root.currentTab = index
                }
            }
        }

        StackLayoutLite {
            anchors.top: tabs.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.spaceMd
            currentIndex: root.currentTab

            InfoTab {}
            LyricsTab {}
            EqualizerTab {}
        }
    }
}
