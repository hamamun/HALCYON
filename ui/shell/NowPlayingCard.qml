import QtQuick
import QtQuick.Effects
import Halcyon.Ui

// The audio idle visual — §7, CHECKLIST 1.8 "Audio-only idle visual".
//
// When the media has no video track there is nothing to draw on the stage, so
// Halcyon showed a black rectangle and the aurora. Everything the user might
// want to read — cover, title, artist, album — was hidden in the right dock,
// which is closed by default. This puts it in the middle of the stage where
// there is nothing else competing for the space.
//
// Shown only when the stage has no picture (see VideoStage.qml), so it never
// covers video.
//
// Ken Burns: a very slow scale drift on the artwork. Deliberately cheap — one
// animated scale on one Image, no shaders, because this runs for the entire
// duration of an album.
Item {
    id: root

    //: Metadata source. Defaults to the context property, but injectable so
    //: this file stays loadable on its own (qmlscene, tests).
    property var meta: typeof Metadata !== "undefined" ? Metadata : null

    property bool animate: true

    readonly property string artwork: meta && meta.artworkUrl ? meta.artworkUrl : ""
    readonly property string trackTitle: meta && meta.title ? meta.title : ""
    readonly property string trackArtist: meta && meta.artist ? meta.artist : ""
    readonly property string trackAlbum: meta && meta.album ? meta.album : ""

    // Cover edge, clamped so it stays sensible in a very small or very large
    // window. Uses the shorter axis so it never overflows.
    readonly property real coverSize:
        Math.max(120, Math.min(280, Math.min(width, height) * 0.42))

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - Theme.spaceXl * 2, 460)
        spacing: Theme.spaceLg

        // ------------------------------------------------------- cover --
        Item {
            id: coverFrame
            width: root.coverSize
            height: root.coverSize
            anchors.horizontalCenter: parent.horizontalCenter

            Rectangle {
                id: coverPlate
                anchors.fill: parent
                radius: Theme.radiusPanel
                color: Theme.glassFill
                border.width: 1
                border.color: Theme.glassBorder
                clip: true

                Image {
                    id: cover
                    anchors.fill: parent
                    source: root.artwork
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: true
                    visible: status === Image.Ready

                    // Ken Burns — a slow breath in and out. Restarts whenever
                    // the artwork changes so each track gets a fresh pass.
                    SequentialAnimation on scale {
                        running: root.animate && cover.status === Image.Ready
                        loops: Animation.Infinite
                        NumberAnimation {
                            from: 1.0; to: 1.08
                            duration: 24000
                            easing.type: Easing.InOutSine
                        }
                        NumberAnimation {
                            to: 1.0
                            duration: 24000
                            easing.type: Easing.InOutSine
                        }
                    }
                }

                // Fallback when the file carries no embedded cover — most
                // loose MP3s do not. A glyph reads better than an empty box.
                Text {
                    anchors.centerIn: parent
                    visible: cover.status !== Image.Ready
                    text: Glyphs.music
                    font.pixelSize: root.coverSize * 0.34
                    color: Theme.textFaint
                }
            }
        }

        // ------------------------------------------------------ title --
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.trackTitle !== "" ? root.trackTitle : "Nothing playing"
            elide: Text.ElideRight
            maximumLineCount: 2
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeTitle
            font.weight: Theme.weightBold
            color: Theme.text
        }

        // ----------------------------------------------------- artist --
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            visible: root.trackArtist !== ""
            text: root.trackArtist
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            color: Theme.textMuted
        }

        // ------------------------------------------------------ album --
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            visible: root.trackAlbum !== ""
            text: root.trackAlbum
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeBody
            color: Theme.textFaint
        }
    }
}
