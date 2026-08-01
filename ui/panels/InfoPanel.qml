import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// The right dock — Info / Lyrics / Equalizer (§P1.5).
//
// Shared, not Local's: M3U reaches the *same* equalizer through the *same*
// panel via Ctrl+I (§P2.4). One implementation, reached the same way from every
// mode — not a copy per mode.
//
// Lyrics tab expand: clicking the expand button (visible only on the Lyrics tab)
// smoothly animates the panel from the normal width to a wider reading width,
// and back again. The rest of the UI is unaffected — panels float over the video.
Item {
    id: root

    property bool open: false
    property Item blurSource: null
    property int currentTab: 0        // 0 Info, 1 Lyrics, 2 Equalizer
    property bool lyricsExpanded: false

    //: A .lrc sidecar was found for the current track — dots the Lyrics tab
    //: button so the user knows the words are waiting. Guarded for qmlscene /
    //: tests, where the Lyrics context property may not exist.
    readonly property bool lyricsAvailable: (typeof Lyrics !== "undefined" && Lyrics)
                                            ? Lyrics.lines.length > 0 : false

    // Width: expanded only when on the Lyrics tab AND the user toggled expand.
    readonly property real expandedWidth: Math.min(Theme.rightPanelExpandedWidth, parent ? parent.width * 0.45 : Theme.rightPanelExpandedWidth)
    readonly property real normalWidth: Theme.rightPanelWidth
    readonly property real targetWidth: (currentTab === 1 && lyricsExpanded) ? expandedWidth : normalWidth

    width: open ? targetWidth : 0
    clip: true
    visible: width > 0

    Behavior on width {
        NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
    }

    // Returning to a non-Lyrics tab resets the expanded state. The next time the
    // user switches back to Lyrics it opens at normal width — the preference
    // resets per session rather than sticking silently.
    onCurrentTabChanged: {
        if (currentTab !== 1)
            lyricsExpanded = false;
    }

    GlassPanel {
        width: root.targetWidth
        height: parent.height
        blurSource: root.blurSource
        radius: 0
        showBorder: false

        // Smooth reflow when the panel width changes — content follows the
        // animated width rather than snapping.
        Behavior on width {
            NumberAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
        }

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
            badges: [false, root.lyricsAvailable, false]

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
                    badge: Array.isArray(tabs.badges) && tabs.badges.length > index
                           ? tabs.badges[index] === true : false
                    onClicked: root.currentTab = index
                }
            }

            // Expand/collapse toggle — only visible on the Lyrics tab.
            // Sits on the right edge of the toolbar so it does not crowd the
            // centred tab buttons.
            IconButton {
                anchors.right: parent.right
                anchors.rightMargin: Theme.spaceXs
                anchors.verticalCenter: parent.verticalCenter
                visible: root.currentTab === 1
                glyph: root.lyricsExpanded ? Glyphs.collapsePanel : Glyphs.expandPanel
                tooltip: root.lyricsExpanded ? "Collapse lyrics" : "Expand lyrics"
                active: false
                onClicked: root.lyricsExpanded = !root.lyricsExpanded
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
