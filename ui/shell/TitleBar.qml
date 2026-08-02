import QtQuick
import QtQuick.Window
import Halcyon.Ui

// The title bar — 44px, §P1.4.
//
// Mode chips render from the registry (`Modes.list`), so Phase 2 and Phase 3 add
// a chip by appending one line to core/modes.py and **never editing this file**
// (§A.2). In Phase 1 exactly one chip renders, and that is correct, not a
// placeholder.
//
// The one home for: mode switching, settings (gear), window buttons.
Item {
    id: root

    property string activeMode: ""
    property bool showModeChips: modeRepeater.count > 1

    //: Metadata source. Injectable so this file stays loadable on its own
    //: (qmlscene, tests), exactly as NowPlayingCard does it.
    property var meta: typeof Metadata !== "undefined" ? Metadata : null
    property var player: typeof Player !== "undefined" ? Player : null

    // What is on air, as one line: "Artist — Title", or just the title when
    // there is no artist tag. Empty when nothing is loaded, which is what makes
    // the bar fall back to the plain "Halcyon" wordmark instead of showing an
    // em-dash on its own.
    //
    // Guarded on `player.currentMedia` rather than on the metadata alone:
    // Metadata keeps the last track's tags until the next one parses, so
    // without this the title bar would advertise a track that has already been
    // stopped.
    readonly property string mediaTitle: {
        if (!player || !player.currentMedia)
            return "";
        var t = meta && meta.title ? meta.title : "";
        var a = meta && meta.artist ? meta.artist : "";
        if (t === "")
            return "";
        return a !== "" ? a + "  \u2014  " + t : t;
    }

    signal modeRequested(string modeId)

    height: Theme.titleBarHeight

    // Drag-to-move. Double-click maximises — the same action the shell exposes,
    // not a second implementation.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: root.Window.window.startSystemMove()
        onDoubleClicked: Actions.toggleMaximized()
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.glassBorder
        opacity: 0.6
    }

    // ------------------------------------------------------------ identity --
    //
    // Wordmark, then whatever is playing. The title sits here rather than in
    // the centre because the centre belongs to the mode chips (§P1.4) and a
    // long film name would collide with them the moment Phase 2 adds a second
    // chip. It is hard-clipped to the space before the chips and elides, so it
    // can never overlap them or the window buttons however long the name is.
    Item {
        id: identity
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceLg
        anchors.verticalCenter: parent.verticalCenter
        height: parent.height
        // Stop short of the chip row; fall back to half the bar if the chips
        // have not been laid out yet.
        width: Math.max(0, (chipRow.width > 0 ? chipRow.x : root.width / 2)
                           - Theme.spaceLg * 2)
        clip: true

        Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            spacing: Theme.spaceSm

            Rectangle {
                width: 10; height: 10; radius: 2
                anchors.verticalCenter: parent.verticalCenter
                rotation: 45
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Theme.accent }
                    GradientStop { position: 1.0; color: Theme.accentAlt }
                }
            }
            Text {
                id: wordmark
                text: "Halcyon"
                anchors.verticalCenter: parent.verticalCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                font.weight: Theme.weightBold
                font.letterSpacing: 0.4
                color: Theme.text
            }

            // Hairline separator, present only when there is a title to separate.
            Rectangle {
                width: 1
                height: 14
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.glassBorder
                visible: root.mediaTitle !== ""
            }

            Text {
                id: nowPlayingLabel
                anchors.verticalCenter: parent.verticalCenter
                visible: root.mediaTitle !== ""
                text: root.mediaTitle
                elide: Text.ElideRight
                // Whatever is left after the diamond, the wordmark, the rule
                // and the three gaps. Clamped at zero so a very narrow window
                // simply shows nothing rather than a negative width warning.
                width: Math.max(0, parent.width - wordmark.width - 10 - 1
                                   - Theme.spaceSm * 3)
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeBody
                color: Theme.textMuted
            }
        }
    }

    // --------------------------------------------------------- mode chips --
    Row {
        id: chipRow
        anchors.centerIn: parent
        spacing: Theme.spaceXs

        Repeater {
            id: modeRepeater
            model: Modes.list

            delegate: Rectangle {
                required property var modelData
                readonly property bool isActive: modelData.id === root.activeMode

                width: chipLabel.implicitWidth + Theme.spaceLg * 2
                height: 28
                radius: Theme.radiusPill
                color: isActive ? Theme.glassFillHover
                     : chipMouse.containsMouse ? Theme.glassFill : "transparent"
                border.width: isActive ? 1 : 0
                border.color: Theme.accentDim

                Behavior on color {
                    ColorAnimation { duration: Theme.durNormal; easing.type: Theme.easing }
                }

                Text {
                    id: chipLabel
                    anchors.centerIn: parent
                    text: modelData.title
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    font.weight: parent.isActive ? Theme.weightBold : Theme.weightNormal
                    color: parent.isActive ? Theme.accent : Theme.textMuted
                }

                MouseArea {
                    id: chipMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.modeRequested(modelData.id)
                }
            }
        }
    }

    // ------------------------------------------------------ window buttons --
    Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: Theme.spaceSm
        spacing: 0

        IconButton {
            glyph: Glyphs.settings
            tooltip: "Settings"
            onClicked: Actions.showSettings()
        }
        Item { width: Theme.spaceSm; height: 1 }
        IconButton {
            glyph: Glyphs.minimize
            tooltip: "Minimise"
            showRing: false
            onClicked: Actions.minimizeWindow()
        }
        IconButton {
            glyph: root.Window.window && root.Window.window.visibility === Window.Maximized
                   ? Glyphs.restore : Glyphs.maximize
            tooltip: root.Window.window && root.Window.window.visibility === Window.Maximized
                     ? "Restore" : "Maximise"
            showRing: false
            onClicked: Actions.toggleMaximized()
        }
        IconButton {
            glyph: Glyphs.close
            tooltip: "Close"
            showRing: false
            iconColor: Theme.danger
            onClicked: Actions.closeWindow()

            background: Rectangle {
                radius: Theme.radiusControl
                color: parent.pressed ? Qt.darker(Theme.danger, 1.3)
                     : parent.hovered ? Theme.danger : "transparent"
                Behavior on color {
                    ColorAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                }
            }
        }
    }
}
