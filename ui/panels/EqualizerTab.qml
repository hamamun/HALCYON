import QtQuick
import QtQuick.Controls.Basic
import Halcyon.Ui

// Equalizer — Milestone 1.7 + Video adjust (Milestone 1.7).
//
// 10 bands, 31 Hz - 16 kHz, +/-20 dB, preamp, VLC's built-in presets plus user
// presets. Applies live via libvlc_audio_equalizer_*.
//
// Video adjust below it: contrast, brightness, hue, saturation, gamma via
// libvlc_video_set_adjust_*. No presets (VLC has none) — manual sliders only,
// enabled only when hasVideo is true.
//
// Shared on purpose: because it hangs off libVLC rather than off Local, it works
// for M3U streams too (§P2.4) — the same component reached the same way, not a
// second equalizer.
Item {
    id: root

    property var eq: typeof Equalizer !== "undefined" ? Equalizer : null
    property var va: typeof VideoAdjust !== "undefined" ? VideoAdjust : null
    property var appRoot: typeof App !== "undefined" ? App : null
    property bool hasVideo: appRoot ? appRoot.hasVideo : false

    Flickable {
        anchors.fill: parent
        contentHeight: contentCol.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { }

        Column {
            id: contentCol
            width: parent.width
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

                    // Keep combo in sync when preset changes from code (band edit -> Custom, reset -> Custom flat)
                    Connections {
                        target: root.eq
                        function onPresetChanged() {
                            presetBox.currentIndex = root.eq ? root.eq.currentPreset : 0
                        }
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
                    id: preampSlider
                    width: parent.width - 52 - 40 - Theme.spaceSm * 2
                    anchors.verticalCenter: parent.verticalCenter
                    from: -20; to: 20
                    value: root.eq ? root.eq.preamp : 0
                    onMoved: if (root.eq) root.eq.set_preamp(value)

                    Connections {
                        target: root.eq
                        function onPreampChanged() {
                            preampSlider.value = root.eq ? root.eq.preamp : 0
                        }
                    }
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
                            id: bandSlider
                            orientation: Qt.Vertical
                            width: parent.width
                            height: 140
                            from: -20; to: 20
                            value: root.eq ? root.eq.amp_at(index) : 0
                            onMoved: if (root.eq) root.eq.set_amp(index, value)

                            // FIX: visually update when preset or reset changes amps via bandsChanged
                            Connections {
                                target: root.eq
                                function onBandsChanged() {
                                    bandSlider.value = root.eq ? root.eq.amp_at(index) : 0
                                }
                                function onPresetChanged() {
                                    bandSlider.value = root.eq ? root.eq.amp_at(index) : 0
                                }
                            }

                            background: Rectangle {
                                x: bandSlider.width / 2 - width / 2
                                y: bandSlider.topPadding
                                width: 4
                                height: bandSlider.availableHeight
                                radius: 2
                                color: Theme.trackRest

                                Rectangle {
                                    width: parent.width
                                    height: Math.abs(bandSlider.visualPosition - 0.5) * parent.height
                                    y: bandSlider.visualPosition < 0.5
                                       ? parent.height * bandSlider.visualPosition
                                       : parent.height * 0.5
                                    radius: 2
                                    color: Theme.accent
                                }
                            }

                            handle: Rectangle {
                                x: bandSlider.width / 2 - width / 2
                                y: bandSlider.topPadding + bandSlider.visualPosition * (bandSlider.availableHeight - height)
                                width: 12; height: 12; radius: 6
                                color: Theme.text
                                scale: bandSlider.pressed ? 1.15 : 1.0
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

            Rectangle { width: parent.width; height: 1; color: Theme.glassBorder }

            // ----------------------------------------- video adjust section --
            // No VLC presets for video — manual sliders only, enabled when video exists.
            Column {
                width: parent.width
                spacing: Theme.spaceSm

                Row {
                    width: parent.width
                    spacing: Theme.spaceSm

                    Text {
                        width: parent.width - videoResetBtn.width - Theme.spaceSm
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Video Adjust" + (root.hasVideo ? "" : " (no video)")
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        font.weight: Theme.weightMedium
                        color: root.hasVideo ? Theme.text : Theme.textFaint
                    }

                    IconButton {
                        id: videoResetBtn
                        glyph: Glyphs.refresh
                        tooltip: "Reset video to default"
                        enabled: root.va !== null
                        onClicked: if (root.va) root.va.reset()
                    }
                }

                Text {
                    width: parent.width
                    visible: !root.hasVideo
                    text: "Video adjust available only when video is playing."
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeTiny
                    color: Theme.textFaint
                    wrapMode: Text.WordWrap
                }

                // Contrast
                Column {
                    width: parent.width
                    spacing: 2
                    enabled: root.hasVideo && root.va !== null
                    opacity: enabled ? 1.0 : 0.45

                    Row {
                        width: parent.width
                        Text { width: 70; text: "Contrast"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeTiny; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        HSlider {
                            id: contrastSlider
                            width: parent.width - 70 - 44
                            from: 0.0; to: 2.0; stepSize: 0.01
                            value: root.va ? root.va.contrast : 1.0
                            onMoved: if (root.va) root.va.set_contrast(value)
                            anchors.verticalCenter: parent.verticalCenter
                            Connections { target: root.va; function onContrastChanged() { contrastSlider.value = root.va ? root.va.contrast : 1.0 } }
                        }
                        Text { width: 44; text: root.va ? root.va.contrast.toFixed(2) : "1.00"; font.family: Theme.fontFamilyMono; font.pixelSize: Theme.fontSizeTiny; color: Theme.textMuted; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                    }
                }

                // Brightness
                Column {
                    width: parent.width
                    spacing: 2
                    enabled: root.hasVideo && root.va !== null
                    opacity: enabled ? 1.0 : 0.45
                    Row {
                        width: parent.width
                        Text { width: 70; text: "Bright."; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeTiny; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        HSlider {
                            id: brightnessSlider
                            width: parent.width - 70 - 44
                            from: 0.0; to: 2.0; stepSize: 0.01
                            value: root.va ? root.va.brightness : 1.0
                            onMoved: if (root.va) root.va.set_brightness(value)
                            anchors.verticalCenter: parent.verticalCenter
                            Connections { target: root.va; function onBrightnessChanged() { brightnessSlider.value = root.va ? root.va.brightness : 1.0 } }
                        }
                        Text { width: 44; text: root.va ? root.va.brightness.toFixed(2) : "1.00"; font.family: Theme.fontFamilyMono; font.pixelSize: Theme.fontSizeTiny; color: Theme.textMuted; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                    }
                }

                // Hue
                Column {
                    width: parent.width
                    spacing: 2
                    enabled: root.hasVideo && root.va !== null
                    opacity: enabled ? 1.0 : 0.45
                    Row {
                        width: parent.width
                        Text { width: 70; text: "Hue"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeTiny; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        HSlider {
                            id: hueSlider
                            width: parent.width - 70 - 44
                            from: 0; to: 360; stepSize: 1
                            value: root.va ? root.va.hue : 0
                            onMoved: if (root.va) root.va.set_hue(value)
                            anchors.verticalCenter: parent.verticalCenter
                            Connections { target: root.va; function onHueChanged() { hueSlider.value = root.va ? root.va.hue : 0 } }
                        }
                        Text { width: 44; text: root.va ? Math.round(root.va.hue) + "°" : "0°"; font.family: Theme.fontFamilyMono; font.pixelSize: Theme.fontSizeTiny; color: Theme.textMuted; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                    }
                }

                // Saturation
                Column {
                    width: parent.width
                    spacing: 2
                    enabled: root.hasVideo && root.va !== null
                    opacity: enabled ? 1.0 : 0.45
                    Row {
                        width: parent.width
                        Text { width: 70; text: "Satur."; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeTiny; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        HSlider {
                            id: satSlider
                            width: parent.width - 70 - 44
                            from: 0.0; to: 3.0; stepSize: 0.01
                            value: root.va ? root.va.saturation : 1.0
                            onMoved: if (root.va) root.va.set_saturation(value)
                            anchors.verticalCenter: parent.verticalCenter
                            Connections { target: root.va; function onSaturationChanged() { satSlider.value = root.va ? root.va.saturation : 1.0 } }
                        }
                        Text { width: 44; text: root.va ? root.va.saturation.toFixed(2) : "1.00"; font.family: Theme.fontFamilyMono; font.pixelSize: Theme.fontSizeTiny; color: Theme.textMuted; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                    }
                }

                // Gamma
                Column {
                    width: parent.width
                    spacing: 2
                    enabled: root.hasVideo && root.va !== null
                    opacity: enabled ? 1.0 : 0.45
                    Row {
                        width: parent.width
                        Text { width: 70; text: "Gamma"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeTiny; color: Theme.textFaint; anchors.verticalCenter: parent.verticalCenter }
                        HSlider {
                            id: gammaSlider
                            width: parent.width - 70 - 44
                            from: 0.01; to: 10.0; stepSize: 0.01
                            value: root.va ? root.va.gamma : 1.0
                            onMoved: if (root.va) root.va.set_gamma(value)
                            anchors.verticalCenter: parent.verticalCenter
                            Connections { target: root.va; function onGammaChanged() { gammaSlider.value = root.va ? root.va.gamma : 1.0 } }
                        }
                        Text { width: 44; text: root.va ? root.va.gamma.toFixed(2) : "1.00"; font.family: Theme.fontFamilyMono; font.pixelSize: Theme.fontSizeTiny; color: Theme.textMuted; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                    }
                }
            }
        }
    }
}
