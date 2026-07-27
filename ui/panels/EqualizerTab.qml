import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Equalizer — Milestone 1.7.
//
// 10 bands, 31 Hz - 16 kHz, +/-20 dB, preamp, VLC's built-in presets plus user
// presets. Applies live via libvlc_audio_equalizer_*.
//
// Shared on purpose: because it hangs off libVLC rather than off Local, it works
// for M3U streams too (§P2.4) — the same component reached the same way, not a
// second equalizer.
Item {
    id: root

    property var eq: typeof Equalizer !== "undefined" ? Equalizer : null

    Column {
        anchors.fill: parent
        spacing: Theme.spaceMd

        // --------------------------------------------------- preset row --
        Row {
            width: parent.width
            spacing: Theme.spaceSm

            ComboBox {
                id: presetBox
                width: parent.width - resetButton.width - Theme.spaceSm
                model: root.eq ? root.eq.presetNames : []
                currentIndex: root.eq ? root.eq.currentPreset : 0
                onActivated: if (root.eq) root.eq.apply_preset(currentIndex)

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: Theme.glassFill
                    border.width: 1
                    border.color: Theme.glassBorder
                }
                contentItem: Text {
                    leftPadding: Theme.spaceMd
                    text: presetBox.displayText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
            }

            IconButton {
                id: resetButton
                glyph: Glyphs.refresh
                tooltip: "Reset to flat"
                onClicked: if (root.eq) root.eq.reset()
            }
        }

        // ------------------------------------------------------- preamp --
        Row {
            width: parent.width
            spacing: Theme.spaceSm

            Text {
                width: 52
                anchors.verticalCenter: parent.verticalCenter
                text: "Preamp"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.textFaint
            }
            HSlider {
                width: parent.width - 52 - 40 - Theme.spaceSm * 2
                anchors.verticalCenter: parent.verticalCenter
                from: -20; to: 20
                value: root.eq ? root.eq.preamp : 0
                onMoved: if (root.eq) root.eq.set_preamp(value)
            }
            Text {
                width: 40
                anchors.verticalCenter: parent.verticalCenter
                text: (root.eq ? root.eq.preamp.toFixed(1) : "0.0") + " dB"
                font.family: Theme.fontFamilyMono
                font.pixelSize: Theme.fontSizeTiny
                color: Theme.textMuted
                horizontalAlignment: Text.AlignRight
            }
        }

        Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

        // -------------------------------------------------- band sliders --
        Row {
            width: parent.width
            height: 180
            spacing: 0

            Repeater {
                model: root.eq ? root.eq.bandLabels : []

                delegate: Column {
                    required property int index
                    required property string modelData
                    width: parent.width / Math.max(1, (root.eq ? root.eq.bandLabels.length : 10))
                    spacing: Theme.spaceXs

                    Slider {
                        id: band
                        orientation: Qt.Vertical
                        width: parent.width
                        height: 140
                        from: -20; to: 20
                        value: root.eq ? root.eq.amp_at(index) : 0
                        onMoved: if (root.eq) root.eq.set_amp(index, value)

                        background: Rectangle {
                            x: band.width / 2 - width / 2
                            y: band.topPadding
                            width: 4
                            height: band.availableHeight
                            radius: 2
                            color: Theme.trackRest

                            Rectangle {
                                width: parent.width
                                height: Math.abs(band.visualPosition - 0.5) * parent.height
                                y: band.visualPosition < 0.5
                                   ? parent.height * band.visualPosition
                                   : parent.height * 0.5
                                radius: 2
                                color: Theme.accent
                            }
                        }

                        handle: Rectangle {
                            x: band.width / 2 - width / 2
                            y: band.topPadding + band.visualPosition * (band.availableHeight - height)
                            width: 12; height: 12; radius: 6
                            color: Theme.text
                            scale: band.pressed ? 1.15 : 1.0
                            Behavior on scale {
                                NumberAnimation { duration: Theme.durFast; easing.type: Theme.easing }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData
                        font.family: Theme.fontFamilyMono
                        font.pixelSize: 9
                        color: Theme.textFaint
                    }
                }
            }
        }
    }
}
