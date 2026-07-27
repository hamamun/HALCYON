pragma Singleton
import QtQuick

// One icon set, one stroke weight — §B.1.
//
// Segoe Fluent Icons ships with Windows 11 and falls back to Segoe MDL2 Assets
// on Windows 10; both are present on every target machine, so there is no font
// to bundle and no SVG pipeline to maintain. Codepoints are centralised here so
// no component ever hardcodes one.
QtObject {
    // transport
    readonly property string play:        "\uE768"
    readonly property string pause:       "\uE769"
    readonly property string stop:        "\uE71A"
    readonly property string previous:    "\uE892"
    readonly property string next:        "\uE893"
    readonly property string rewind:      "\uEB9E"
    readonly property string fastForward: "\uEB9D"

    // audio
    readonly property string volumeMute:  "\uE74F"
    readonly property string volumeLow:   "\uE993"
    readonly property string volumeMid:   "\uE994"
    readonly property string volumeHigh:  "\uE995"

    // view
    readonly property string fullscreen:      "\uE740"
    readonly property string fullscreenExit:  "\uE73F"
    readonly property string pictureInPicture: "\uE944"

    // modes / playlist
    readonly property string repeatAll:  "\uE8EE"
    readonly property string repeatOne:  "\uE8ED"
    readonly property string shuffle:    "\uE8B1"
    readonly property string addFile:    "\uE8E5"
    readonly property string addFolder:  "\uE8F4"
    readonly property string clearAll:   "\uE74D"
    readonly property string clearItem:  "\uE738"
    readonly property string playlist:   "\uE90B"
    readonly property string infoPanel:  "\uE8A0"   // right dock toggle

    // chrome
    readonly property string settings:   "\uE713"
    readonly property string minimize:   "\uE921"
    readonly property string maximize:   "\uE922"
    readonly property string restore:    "\uE923"
    readonly property string close:      "\uE8BB"
    readonly property string chevronLeft:  "\uE76B"
    readonly property string chevronRight: "\uE76C"
    readonly property string search:     "\uE721"

    // panels
    readonly property string info:       "\uE946"
    readonly property string lyrics:     "\uE8D2"
    readonly property string equalizer:  "\uE9E9"
    readonly property string subtitles:  "\uED1E"
    readonly property string audioTrack: "\uE8D6"
    readonly property string speed:      "\uEC4A"
    readonly property string music:      "\uE8D6"
    readonly property string video:      "\uE714"
    readonly property string bookmark:   "\uE734"
    readonly property string globe:      "\uE774"
    readonly property string refresh:    "\uE72C"
    readonly property string home:       "\uE80F"
}
