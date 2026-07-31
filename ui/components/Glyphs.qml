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
    // OpenFile — a document with an arrow, reads "open/browse a file".
    // Deliberately NOT a folder: folders mean "media folder" here (addFolder).
    readonly property string openFile:   "\uE8E5"
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
    readonly property string chevronDown:  "\uE70D"
    readonly property string chevronUp:    "\uE70E"
    readonly property string search:     "\uE721"

    // panels
    readonly property string info:       "\uE946"
    readonly property string lyrics:     "\uE8D2"
    readonly property string equalizer:  "\uE9E9"
    readonly property string subtitles:  "\uED1E"   // Fluent "Subtitles" (CC)
    readonly property string audioTrack: "\uE8D6"
    readonly property string speed:      "\uEC4A"
    readonly property string download:   "\uE896"
    // Eye pair — Fluent/MDL2 "View" and "Hide", for API-key reveal toggles.
    readonly property string eyeShow:    "\uE890"
    readonly property string eyeHide:    "\uED1A"
    readonly property string music:      "\uE8D6"
    readonly property string video:      "\uE714"
    readonly property string bookmark:   "\uE734"
    readonly property string globe:      "\uE774"
    readonly property string refresh:    "\uE72C"
    readonly property string home:       "\uE80F"

    // Right-dock widen/narrow, used by the Lyrics tab.
    //
    // Aliases onto the chevron pair above rather than introducing new
    // codepoints: for a dock pinned to the right edge, "grow" moves its inner
    // edge left and "shrink" moves it back right, so the chevrons point the way
    // the panel is about to travel.
    //
    // Do not substitute E902/E903 here. E902 is "Group" (an unrelated glyph)
    // and E903 is unassigned in Segoe Fluent Icons — it renders as tofu.
    readonly property string expandPanel:   chevronLeft    // widen  ← 
    readonly property string collapsePanel: chevronRight   // narrow →
}
