pragma Singleton
import QtQuick

// The Actions singleton — §4.1, the Single-Placement Rule.
//
//     Every action exists in exactly one place. If a second context needs it,
//     that context invokes the *same* action — it does not draw its own copy.
//
// Two components *binding* one action is correct. Two components *implementing*
// the same behaviour is a bug. So: `F`, the fullscreen button, and double-click
// on the stage all call Actions.toggleFullscreen() — one implementation, three
// triggers.
//
// The review question for any new control is:
//     "is this the only place it can be triggered from, or the only place it's
//      implemented?"  The second is required.
//
// Handlers are installed once by the shell (see Main.qml). Anything that fires
// before wiring is a silent no-op rather than a crash.
QtObject {
    id: actions

    // Wired by Main.qml at startup. QML has no interfaces, so this is the
    // pragmatic version: one object holding the implementations.
    property var host: null

    function _call(name, a, b) {
        if (!host || typeof host[name] !== "function") {
            console.warn("Actions." + name + " invoked before wiring");
            return undefined;
        }
        return host[name](a, b);
    }

    // ------------------------------------------------------------ playback --
    // The one home: the mode's transport bar (§P1.4).
    function playPause()            { return _call("playPause") }
    function play()                 { return _call("play") }
    function pause()                { return _call("pause") }
    function stop()                 { return _call("stop") }
    function next()                 { return _call("next") }
    function previous()             { return _call("previous") }
    function seekRelative(ms)       { return _call("seekRelative", ms) }
    function seekTo(ms)             { return _call("seekTo", ms) }
    function seekFraction(f)        { return _call("seekFraction", f) }
    // Bracket a scrub drag so the engine stops publishing positions that
    // would fight the pointer.
    function beginScrub()           { return _call("beginScrub") }
    function endScrub()             { return _call("endScrub") }
    function setRate(rate)          { return _call("setRate", rate) }
    function stepRate(delta)        { return _call("stepRate", delta) }

    // --------------------------------------------------------------- audio --
    function setVolume(v)           { return _call("setVolume", v) }
    function adjustVolume(delta)    { return _call("adjustVolume", delta) }
    function toggleMute()           { return _call("toggleMute") }

    // -------------------------------------------------------------- tracks --
    // The one home: transport bar → subtitle popover.
    function setAudioTrack(id)      { return _call("setAudioTrack", id) }
    function cycleAudioTrack()      { return _call("cycleAudioTrack") }
    function setSubtitleTrack(id)   { return _call("setSubtitleTrack", id) }
    function cycleSubtitleTrack()   { return _call("cycleSubtitleTrack") }
    function loadSubtitleFile()     { return _call("loadSubtitleFile") }
    function adjustSubtitleDelay(ms) { return _call("adjustSubtitleDelay", ms) }

    // ------------------------------------------------------------ playlist --
    // The one home: the Local panel toolbar. The empty-stage prompt, Ctrl+O and
    // Explorer drag-and-drop all call these — they do not draw their own buttons.
    function addFiles()             { return _call("addFiles") }
    function addFolder()            { return _call("addFolder") }
    function addPaths(paths)        { return _call("addPaths", paths) }
    function clearSelected()        { return _call("clearSelected") }
    function clearPlaylist()        { return _call("clearPlaylist") }
    function playIndex(i)           { return _call("playIndex", i) }
    function moveItem(from, to)     { return _call("moveItem", from, to) }
    function cycleRepeat()          { return _call("cycleRepeat") }
    function toggleShuffle()        { return _call("toggleShuffle") }

    // ---------------------------------------------------------------- view --
    function toggleFullscreen()     { return _call("toggleFullscreen") }
    function exitFullscreen()       { return _call("exitFullscreen") }
    function toggleLeftPanel()      { return _call("toggleLeftPanel") }
    function toggleRightPanel()     { return _call("toggleRightPanel") }
    function showEqualizer()        { return _call("showEqualizer") }
    // Open the right dock straight onto the Lyrics tab — the destination the
    // lyrics availability dot on the Equalizer/Info button advertises. Mirrors
    // showEqualizer() (which lands on tab 2); this lands on tab 1.
    function showLyrics()           { return _call("showLyrics") }
    function showSettings()         { return _call("showSettings") }

    // ---------------------------------------------------------------- mode --
    // The one home: the title bar.
    function switchMode(id)         { return _call("switchMode", id) }

    // -------------------------------------------------------------- window --
    function minimizeWindow()       { return _call("minimizeWindow") }
    function toggleMaximized()      { return _call("toggleMaximized") }
    function closeWindow()          { return _call("closeWindow") }

    // ----------------------------------------------------------------- osd --
    // Fires only when the active ModeSpec has osd_enabled (§6.2).
    function osd(text, glyph)       { return _call("osd", text, glyph) }
    function osdLevel(text, glyph, level) { return _call("osdLevel", { text: text, glyph: glyph, level: level }) }
}
