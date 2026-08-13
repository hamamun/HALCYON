import QtQuick
import QtQuick.Window
import QtQuick.Dialogs
import Halcyon.Ui
import Halcyon.Shell
import Halcyon.Panels
import Halcyon.Overlay

// The window — §P1.4.
//
//  ┌──────────────────────────────────────────────────────────┐
//  │ ◆ Halcyon   [ Local ]                    ⚙  ─  □  ✕      │ 44px
//  ├──────────────────────────────────────────────────────────┤
//  │  ┌────────┐  Stage (video + OSD)         ┌──────────┐   │
//  │  │PanelHost│  full-width                  │InfoPanel │   │
//  │  │ overlay │                              │ overlay  │   │
//  │  │  z:10   │                              │  z:10    │   │
//  │  └────────┘                              └──────────┘   │
//  │  ──────────  mode transport bar  ──────────────────────  │
//  │              full-width, never moves                     │
//  └──────────────────────────────────────────────────────────┘
//
// Panels float over the video area — they never push the transport bar or
// squeeze the video. Both docks stop at the top edge of the transport bar
// (see body.transportInset) so the controls are never covered.
//
// Panels are opened and closed *only* by their toggles — the toolbar buttons
// and Ctrl+L / Ctrl+I. Clicking the video does not dismiss them; a click on
// the stage means play/pause and nothing else.
// The lyrics tab can expand for better readability (§P1.5).
//
// The chassis is fixed. Which panel, which stage and which bar load into it
// comes from the active ModeSpec (§A.2) — that is the whole extension mechanism.
Shell {
    id: window

    property string activeMode: App.activeMode
    readonly property var modeSpec: Modes.spec(activeMode)
    property bool chromeVisible: true

    // ---------------------------------------------------- video mode §0.5.1/§V
    // The *effective* route the engine reports, never the selection: a Turbo
    // attempt that failed has already fallen back to Soft, and every consumer
    // here must follow what is really on screen.
    readonly property string effectiveVideoMode:
        (typeof App !== "undefined" && App && App.effectiveVideoMode)
        ? App.effectiveVideoMode : "soft"
    readonly property bool turboActive: effectiveVideoMode === "turbo"

    // Picture size for the Turbo HWND. Soft does not read these.
    // A non-number (test stubs, missing property) is treated as 0 so the
    // container fills the stage until the decoder reports a real size.
    readonly property int turboVideoWidth: {
        if (typeof Player === "undefined" || !Player)
            return 0;
        var w = Player.videoWidth;
        return (typeof w === "number" && w > 0) ? w : 0;
    }
    readonly property int turboVideoHeight: {
        if (typeof Player === "undefined" || !Player)
            return 0;
        var h = Player.videoHeight;
        return (typeof h === "number" && h > 0) ? h : 0;
    }

    // True while chromeLayer lives in the Turbo overlay window. Kept as an
    // explicit flag (not inferred from parent) so blur can stay off for the
    // whole move — MultiEffect must not sample `stage` from a different window.
    property bool chromeInOverlay: false

    // A transparent (layered) window plus a native HWND punches through to the
    // desktop. Soft keeps the rounded-corner transparency; Turbo paints an
    // opaque base so the letterbox is the window, not File Explorer.
    color: (turboActive && !miniModeActive) ? "#000000" : "transparent"

    // Backup for the letterbox hole: while Turbo is on, strip the
    // layered/glass style from this HWND so leftover transparent pixels
    // land on black, not Outlook. Soft puts the glass back.
    onTurboActiveChanged: {
        if (typeof App === "undefined" || !App)
            return;
        if (turboActive && !miniModeActive) {
            if (App.sealTurboHost)
                App.sealTurboHost(window);
        } else if (App.unsealTurboHost) {
            App.unsealTurboHost(window);
        }
    }

    // What the glass panels blur. Soft video is scene-graph pixels, so the
    // Stage is a real backdrop. Turbo's picture is a native child window that
    // MultiEffect cannot sample (§V.3) — and while the chrome lives in the
    // overlay window the Stage is in a different scene entirely — so the
    // panels fall back to their plain tint rather than blurring nothing.
    //
    // Blur stays off for the whole overlay residency, not just while
    // turboActive is true: turning Soft back on must move chrome home *before*
    // MultiEffect is recreated against `stage`, or Qt raises
    // "Cannot use same item on different windows".
    readonly property var chromeBlurSource: (turboActive || chromeInOverlay) ? null : stage

    function reportTurboFailure(reason) {
        console.warn("Turbo: " + reason + " — falling back to Soft");
        if (typeof App !== "undefined" && App && App.reportTurboFailure)
            App.reportTurboFailure(String(reason));
    }

    // The docks' open state lives here as plain bools, NOT as an imperative
    // toggle on the docks, and NOT as bindings. `panelHost.open = !x` and
    // `rightPanelOpen: Settings.get(...)` both compile, but the first removes
    // the dock's binding and the second removes this property's own binding —
    // Qt logs "Overwriting binding ... that was initially bound at ..."
    // (qt.qml.binding.removal). Toggles write these bools, the docks bind
    // `open` to them, and that binding survives every toggle because these are
    // plain values. The initial value is loaded from Settings in
    // Component.onCompleted (see below), so there is never a binding here for
    // a write to clobber.
    property bool leftPanelOpen: false
    property bool rightPanelOpen: false

    // --------------------------------------------------------- Mini Mode v1.1 §M
    property bool miniModeActive: false
    property int normalX: -1
    property int normalY: -1
    property int normalW: -1
    property int normalH: -1
    property bool normalWasMaximized: false
    property bool normalWasFullscreen: false
    // Width from settings, height = titleBarHeight per spec
    property int miniBarWidth: Math.max(460, Settings.get("window.miniBarWidth", 460))
    readonly property int miniBarHeight: Theme.titleBarHeight // 44px

    // Override Shell's min/max to allow fixed mini size
    minimumWidth: miniModeActive ? miniBarWidth : 860
    minimumHeight: miniModeActive ? miniBarHeight : 520
    maximumWidth: miniModeActive ? miniBarWidth : 16777215
    maximumHeight: miniModeActive ? miniBarHeight : 16777215
    // Always-on-top in mini
    flags: Qt.Window | Qt.FramelessWindowHint | (miniModeActive ? Qt.WindowStaysOnTopHint : 0)

    // The OS-level title: taskbar button, Alt-Tab, window list. The frameless
    // shell draws no caption of its own, so this is otherwise invisible to the
    // user — but it is what Windows shows, and "Halcyon" for every window is
    // useless the moment two copies are open.
    //
    // For M3U, the channel name is shown instead of file metadata.
    title: {
        var modeTitle = App.modeWindowTitle || "";
        if (modeTitle !== "")
            return modeTitle + "  \u00B7  Halcyon";
        var channelName = window.modeChannelName();
        if (channelName !== "")
            return channelName + "  \u00B7  Halcyon";
        var media = titleBar.mediaTitle;
        return media !== "" ? media + "  \u00B7  Halcyon" : "Halcyon";
    }
    visible: true

    // -------------------------------------------------- geometry overrides §M
    function saveGeometry() {
        if (miniModeActive) {
            Settings.set("window.miniBarX", x);
            Settings.set("window.miniBarY", y);
        } else {
            if (visibility === Window.Windowed) {
                Settings.set("window.x", x);
                Settings.set("window.y", y);
                Settings.set("window.width", width);
                Settings.set("window.height", height);
            }
            Settings.set("window.maximized", visibility === Window.Maximized);
        }
    }

    function restoreGeometry() {
        // Normal geometry only — mini geometry restored on demand in enterMiniMode
        var w = Settings.get("window.width", 1280);
        var h = Settings.get("window.height", 760);
        var sx = Settings.get("window.x", -1);
        var sy = Settings.get("window.y", -1);
        width = Math.max(w, 860);
        height = Math.max(h, 520);
        if (sx >= 0 && sy >= 0) {
            x = sx;
            y = sy;
        } else {
            x = Screen.width / 2 - width / 2;
            y = Screen.height / 2 - height / 2;
        }
        if (Settings.get("window.maximized", false))
            visibility = Window.Maximized;
    }

    // Mini Mode core — simplest path §M.6
    function hasMedia() {
        return Player && (Player.duration > 0 || (Player.currentMedia !== undefined && Player.currentMedia !== null && Player.currentMedia !== ""));
    }

    function enterMiniMode() {
        if (miniModeActive) return;
        if (activeMode !== "local") return;
        if (!hasMedia()) return;
        if (fullscreen) {
            // Fullscreen lockout §M.5
            return;
        }
        // Save normal geometry
        normalX = x;
        normalY = y;
        normalW = width;
        normalH = height;
        normalWasMaximized = (visibility === Window.Maximized);
        normalWasFullscreen = fullscreen;
        if (normalWasFullscreen) {
            setFullscreen(false);
        }
        if (normalWasMaximized) {
            visibility = Window.Windowed;
        }
        // Video mode — Mini runs on Soft (§M, §V.4).
        //
        // The 460×44 bar has no stage to embed a native child window in, so a
        // Turbo child here would be orphaned or invisible: exactly the state
        // the failure rule forbids. The *selection* is untouched — nothing is
        // written to settings and no old Turbo checkbox is resurrected — the
        // controller simply forces Soft while Mini is on and re-resolves the
        // chosen mode (including Auto -> Turbo) on the way back out.
        App.setMiniMode(true);

        // Determine mini position — each session's first entry is top-center
        // (startup resets the saved position to -1); within this session the
        // last dragged position is remembered.
        var mx = Settings.get("window.miniBarX", -1);
        var my = Settings.get("window.miniBarY", -1);
        var mw = miniBarWidth;
        var mh = miniBarHeight;
        if (mx < 0 || my < 0) {
            // Top-center of the screen where the window was
            var scr = Screen; // current screen
            mx = scr.width / 2 - mw / 2 + scr.virtualX;
            my = scr.virtualY + 12;
        }

        // Apply fixed size and move — triggers saveTimer but our saveGeometry will save mini pos
        width = mw;
        height = mh;
        x = mx;
        y = my;

        miniModeActive = true;
        // Ensure chromeVisible true for mini (no auto-hide)
        chromeVisible = true;
    }

    function leaveMiniMode() {
        if (!miniModeActive) return;
        // Save mini position
        Settings.set("window.miniBarX", x);
        Settings.set("window.miniBarY", y);

        miniModeActive = false;

        // Restore normal geometry
        if (normalW > 0 && normalH > 0) {
            width = normalW;
            height = normalH;
            x = normalX;
            y = normalY;
        } else {
            // Fallback to settings restore
            restoreGeometry();
        }
        if (normalWasMaximized) {
            visibility = Window.Maximized;
        }
        if (normalWasFullscreen) {
            setFullscreen(true);
        }
        // Back to the full window: re-resolve the selected Video mode, which
        // may be Auto and may land on Turbo. A Turbo attempt that fails here
        // falls back to Soft exactly as it does anywhere else (§V.4).
        App.setMiniMode(false);
    }

    function toggleMiniMode() {
        if (miniModeActive) leaveMiniMode();
        else enterMiniMode();
    }

    Component.onCompleted: {
        // Seed the plain dock bools from the persisted settings. Done here
        // rather than as property bindings so that the imperative writes in
        // toggleRightPanel()/showLyrics()/showEqualizer() never clobber a
        // declared binding (and so Qt never logs "Overwriting binding").
        leftPanelOpen = Settings.get("window.leftPanelVisible", true);
        rightPanelOpen = Settings.get("window.rightPanelVisible", false);
        restoreGeometry();
        // Mini Mode always re-enters top-center on a fresh session (§M).
        // Startup clears any position the previous session's drag persisted;
        // leaveMiniMode() still saves within this run, so drags stay
        // remembered between entries in the same session while every launch
        // begins top-center again.
        Settings.set("window.miniBarX", -1);
        Settings.set("window.miniBarY", -1);
        Actions.host = actionHost;
    }

    onClosing: function(close) {
        if (miniModeActive) {
            // No close from mini — return to normal §M.5
            close.accepted = false;
            leaveMiniMode();
            return;
        }
        saveGeometry();
        Settings.flush();
    }

    // ======================================================================
    // ACTION HOST — the single implementation of every action (§4.1).
    //
    // Buttons, hotkeys, drag-and-drop and the OSD all route here. If you find
    // yourself writing behaviour anywhere else in the UI, it belongs in this
    // object instead.
    // ======================================================================
    QtObject {
        id: actionHost

        // ---------------------------------------------------- playback --
        // `usesPlayer` is read through a helper because modeSpec is null for
        // one frame at startup — Modes.spec() runs before App.activeMode has
        // settled — and `null.usesPlayer` throws rather than returning false.
        function playPause() {
            if (!window.usesPlayer()) return;
            // Capture the requested direction before libVLC's asynchronous
            // state publish. A newly opened live channel may still report
            // "Opening" for a moment, but the user correctly asked to play.
            var wasPlaying = !!(Player && Player.isPlaying);
            if (!App.playPause())
                return;                  // empty playlist / no media: stay quiet
            osd(wasPlaying ? "Paused" : "Playing",
                wasPlaying ? Glyphs.pause : Glyphs.play);
            // Keep the quick centre acknowledgement alongside the readable
            // status toast — the icon is useful at a glance over video.
            osdGlyph(wasPlaying ? Glyphs.pause : Glyphs.play);
        }
        function play()  { if (window.usesPlayer()) App.play() }
        function pause() { if (window.usesPlayer()) App.pause() }
        function stop()  { if (window.usesPlayer()) App.stop() }

        // M3U contexts provide a friendly channel label through the generic
        // controller protocol. Local returns an empty string here because its
        // existing media-change toast already names the file.
        function _channelToast(action, glyph, accepted) {
            if (!accepted)
                return;
            var name = window.playlistPlaybackLabel();
            if (name.length === 0)
                return;
            osd(action + ": " + window.shortToastName(name), glyph);
        }
        function next() {
            _channelToast("Next", Glyphs.next, App.next());
        }
        function previous() {
            _channelToast("Previous", Glyphs.previous, App.previous());
        }

        function seekRelative(ms) {
            if (!window.usesPlayer()) return;
            Player.seek_relative(ms);
            osd((ms > 0 ? Glyphs.fastForward : Glyphs.rewind) + "  "
                + formatTime(Player.time) + " / " + formatTime(Player.duration));
        }
        // seekTo and seekFraction show the same position pill as keyboard
        // seek (seekRelative above). Mouse scrubbing fires them repeatedly,
        // and the OSD's restart-not-stack timer turns that into a live
        // readout (§6.2) that holds for 1500 ms after the drag ends.
        function seekTo(ms) {
            Player.seek(ms);
            _osdSeekTarget(ms);
        }
        function seekFraction(f) {
            Player.set_position(f);
            _osdSeekTarget(f * Player.duration);
        }
        function _osdSeekTarget(targetMs) {
            if (Player.duration <= 0)
                return;                  // live stream / duration unknown
            osd(formatTime(targetMs) + " / " + formatTime(Player.duration),
                targetMs >= Player.time ? Glyphs.fastForward : Glyphs.rewind);
        }
        function beginScrub()     { Player.set_scrubbing(true) }
        function endScrub()       { Player.set_scrubbing(false) }
        function setRate(rate) {
            Player.set_rate(rate);
            osd(rate + "\u00D7");
        }
        function stepRate(delta) {
            var steps = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
            var i = 0, best = 1e9;
            for (var k = 0; k < steps.length; k++) {
                var d = Math.abs(steps[k] - Player.rate);
                if (d < best) { best = d; i = k; }
            }
            setRate(steps[Math.max(0, Math.min(steps.length - 1, i + delta))]);
        }

        // ------------------------------------------------------- audio --
        function setVolume(v) {
            Player.set_volume(v);
            Settings.set("audio.volume", v);
            osdLevel({ text: "Volume " + v + "%", glyph: volumeGlyph(v, Player.muted),
                       level: v / 100 });
        }
        function adjustVolume(delta) { setVolume(Math.max(0, Math.min(100, Player.volume + delta))) }
        function toggleMute() {
            Player.toggle_mute();
            Settings.set("audio.muted", Player.muted);
            osd(Player.muted ? "Muted" : "Unmuted",
                volumeGlyph(Player.volume, Player.muted));
        }

        // ------------------------------------------------------ tracks --
        function setAudioTrack(id) {
            App.setAudioTrack(id);
            if (id === -1) {
                osd("Audio disabled", Glyphs.volumeMute);
            } else {
                var track = App.audioTracks.filter(function(t) { return t.id === id; })[0];
                osd("Audio: " + (track ? track.label : "Track " + id), Glyphs.volumeHigh);
            }
        }
        function cycleAudioTrack() {
            App.cycleAudioTrack();
            if (App.audioTracks.length > 0) {
                osd("Audio: " + App.audioTracks[0].label, Glyphs.volumeHigh);
            }
        }
        function setSubtitleTrack(id) {
            App.setSubtitleTrack(id);
            if (id === -1) {
                osd("Subtitles disabled", Glyphs.subtitles);
            } else {
                var track = App.subtitleTracks.filter(function(t) { return t.id === id; })[0];
                if (!track) {
                    track = App.localSubtitleTracks.filter(function(t) { return t.id === id; })[0];
                }
                osd("Subtitles: " + (track ? track.label : "Track " + id), Glyphs.subtitles);
            }
        }
        function cycleSubtitleTrack() {
            App.cycleSubtitleTrack();
            if (App.subtitleTracks.length > 0) {
                osd("Subtitles: " + App.subtitleTracks[0].label, Glyphs.subtitles);
            }
        }
        function loadSubtitleFile()   { subtitleDialog.open() }
        function adjustSubtitleDelay(ms) {
            App.adjustSubtitleDelay(ms);
            var sign = ms > 0 ? "+" : "";
            osd("Subtitle delay " + sign + ms + " ms", Glyphs.subtitles);
        }

        // ---------------------------------------------------- playlist --
        function addFiles()        { fileDialog.open() }
        function addFolder()       { folderDialog.open() }
        function addPaths(paths)   { App.addPaths(paths) }
        function clearSelected() {
            App.clearSelected(localPanelSelection());
            if (panelHost.item && "selection" in panelHost.item) {
                panelHost.item.selection = [];
            }
        }
        function clearPlaylist() {
            App.clearPlaylist();
            if (panelHost.item && "selection" in panelHost.item) {
                panelHost.item.selection = [];
            }
        }
        function playIndex(i)      { App.playIndex(i) }
        function moveItem(f, t)    { App.moveItem(f, t) }
        function cycleRepeat() {
            App.cycleRepeat();
            if (!window.modeContext)
                return;                  // mode still resolving — stay silent
            var m = window.modeContext.repeatMode;
            osd(m === 0 ? "Repeat off" : m === 1 ? "Repeat one" : "Repeat all",
                m === 1 ? Glyphs.repeatOne : Glyphs.repeatAll);
        }
        function toggleShuffle() {
            App.toggleShuffle();
            if (!window.modeContext)
                return;
            osd(window.modeContext.shuffle ? "Shuffle on" : "Shuffle off",
                Glyphs.shuffle);
        }

        // -------------------------------------------------------- view --
        function toggleFullscreen() {
            var entering = !window.fullscreen;
            window.setFullscreen(entering);
            osd(entering ? "Fullscreen" : "Exit fullscreen",
                entering ? Glyphs.fullscreen : Glyphs.fullscreenExit);
            osdGlyph(entering ? Glyphs.fullscreen : Glyphs.fullscreenExit);
        }
        function exitFullscreen()  { if (window.fullscreen) toggleFullscreen() }
        function toggleLeftPanel() {
            // Web is a full-width browser, not a player with an empty dock.
            // Keep Local/M3U's remembered state intact, but never let Ctrl+L
            // resurrect a placeholder panel while the active mode opted out.
            if (!window.leftPanelAvailable()) return;
            window.leftPanelOpen = !window.leftPanelOpen;
            Settings.set("window.leftPanelVisible", window.leftPanelOpen);
            if (window.fullscreen) window.wakeChrome();
        }
        function toggleRightPanel() {
            if (!window.rightDockAvailable()) return;   // M3U/Web: inert (§P2.4)
            window.rightPanelOpen = !window.rightPanelOpen;
            Settings.set("window.rightPanelVisible", window.rightPanelOpen);
            if (window.fullscreen) window.wakeChrome();
        }
        function showEqualizer() {
            if (!window.rightDockAvailable()) return;   // EQ is Local's (§P2.4)
            window.rightPanelOpen = true;
            infoPanel.currentTab = 2;
            Settings.set("window.rightPanelVisible", true);
        }
        // Lands the right dock on the Lyrics tab — used by the Equalizer/Info
        // button when its lyrics dot is showing, so a single click delivers
        // the lyrics the dot promised instead of the default Info tab.
        function showLyrics() {
            if (!window.rightDockAvailable()) return;
            window.rightPanelOpen = true;
            infoPanel.currentTab = 1;   // 0 Info, 1 Lyrics, 2 Equalizer
            Settings.set("window.rightPanelVisible", true);
        }
        function showSettings()    { settingsDialog.open() }

        // -------------------------------------------------------- mode --
        function switchMode(id)    { App.setActiveMode(id) }

        // ------------------------------------------------------ window --
        function minimizeWindow()  { window.showMinimized() }
        function toggleMaximized() { window.toggleMaximized() }
        function closeWindow()     { window.close() }
        function toggleMiniMode()  { window.toggleMiniMode() }

        // --------------------------------------------------------- osd --
        function osd(text, glyph)  { if (osdEnabled()) osdLayer.show(text, glyph) }
        function osdLevel(spec)    { if (osdEnabled()) osdLayer.showLevel(spec.text, spec.glyph, spec.level) }
    }

    // OSD fires only where the ModeSpec allows it (§6.2), and never before the
    // first spec resolves. M3U opts in for lightweight transport feedback;
    // the user can still disable every toast from Settings.
    function osdEnabled()  {
        return !!modeSpec && modeSpec.osdEnabled && Settings.get("ui.osdEnabled", true);
    }
    function osdGlyph(g)   { if (osdEnabled()) osdLayer.showGlyph(g) }

    // The right dock (Info / Lyrics / Equalizer) is deliberately independent
    // from transport feedback. M3U can show a toast without inheriting Local's
    // rich media panels; future modes make the same decision in their spec.
    function rightDockAvailable() {
        return !!modeSpec && modeSpec.rightDockEnabled;
    }

    // A mode can own no left dock at all.  This is distinct from an open/closed
    // preference: Web has no panel to open, while Local/M3U keep their normal
    // remembered dock state.
    function leftPanelAvailable() {
        // Do not render a dock until a real ModeSpec has explicitly opted in.
        // This prevents a transient Local placeholder from flashing in Web
        // while the active mode binding settles at startup.
        return !!modeSpec && !!modeSpec.panelEnabled;
    }

    function shortToastName(name) {
        name = String(name || "");
        return name.length > 60 ? name.substring(0, 59) + "…" : name;
    }

    // A context may provide a friendly playlist label (M3U channel name). A
    // local file has no such protocol and continues to use its filename below.
    function playlistPlaybackLabel() {
        if (typeof App.currentPlaybackLabel !== "function")
            return "";
        return App.currentPlaybackLabel() || "";
    }

    function playbackDisplayName() {
        var label = playlistPlaybackLabel();
        return label.length > 0 ? label : (App.currentFileStem || "");
    }

    // Get the current channel name for M3U mode (for the title bar).
    // Returns empty string for other modes.
    function modeChannelName() {
        if (activeMode === "m3u" && modeContext && modeContext.currentChannelName)
            return modeContext.currentChannelName;
        return "";
    }

    // Does the active mode drive the shared player? False while modeSpec is
    // still resolving, which is the safe answer.
    function usesPlayer() { return !!modeSpec && modeSpec.usesPlayer }

    function volumeGlyph(v, muted) {
        if (muted || v === 0) return Glyphs.volumeMute;
        return v < 34 ? Glyphs.volumeLow : v < 67 ? Glyphs.volumeMid : Glyphs.volumeHigh;
    }

    function formatTime(ms) {
        if (!isFinite(ms) || ms < 0) ms = 0;
        var total = Math.floor(ms / 1000);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = (h > 0 && m < 10 ? "0" : "") + m;
        var ss = (s < 10 ? "0" : "") + s;
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }

    function localPanelSelection() {
        return panelHost.item && panelHost.item.selection ? panelHost.item.selection : [];
    }

    // The active mode's context object (Local's queue today). Looked up by id,
    // never named directly, so adding a mode needs no edit here (§A.3).
    readonly property var modeContext: activeMode === "local"
                                       && typeof LocalPlaylist !== "undefined"
                                       ? LocalPlaylist : null

    // Push live state into whichever transport bar the active mode loaded.
    // Establishes real bindings via Qt.binding, so later changes keep flowing.
    function bindTransport(item) {
        if (!item)
            return;
        if ("player" in item)
            item.player = Player;
        if ("repeatMode" in item)
            item.repeatMode = Qt.binding(function() {
                return window.modeContext ? window.modeContext.repeatMode : 0;
            });
        if ("shuffle" in item)
            item.shuffle = Qt.binding(function() {
                return window.modeContext ? window.modeContext.shuffle : false;
            });
        if ("playlistVisible" in item)
            item.playlistVisible = Qt.binding(function() { return panelHost.open });
        if ("infoPanelVisible" in item)
            item.infoPanelVisible = Qt.binding(function() { return infoPanel.open });
        if ("audioTracks" in item)
            item.audioTracks = Qt.binding(function() { return App.audioTracks });
        if ("subtitleTracks" in item)
            item.subtitleTracks = Qt.binding(function() { return App.subtitleTracks });
        if ("embeddedSubtitleTracks" in item)
            item.embeddedSubtitleTracks = Qt.binding(function() { return App.embeddedSubtitleTracks });
        if ("localSubtitleTracks" in item)
            item.localSubtitleTracks = Qt.binding(function() { return App.localSubtitleTracks });
        if ("currentAudioId" in item)
            item.currentAudioId = Qt.binding(function() { return App.currentAudioId });
        if ("currentSubtitleId" in item)
            item.currentSubtitleId = Qt.binding(function() { return App.currentSubtitleId });
        if ("subtitleDelayMs" in item)
            item.subtitleDelayMs = Qt.binding(function() { return App.subtitleDelayMs });
        if ("hasVideo" in item)
            item.hasVideo = Qt.binding(function() { return App.hasVideo });
        // Availability flags for the two transport-bar dots (§P1.6). Subtitles
        // is computed in the controller (it knows tracks + active state);
        // lyrics is read straight off the Lyrics object's parsed lines.
        if ("subtitlesAvailable" in item)
            item.subtitlesAvailable = Qt.binding(function() { return App.subtitlesAvailable });
        if ("lyricsAvailable" in item)
            item.lyricsAvailable = Qt.binding(function() {
                return typeof Lyrics !== "undefined" && !!Lyrics && Lyrics.lines.length > 0;
            });
        if ("solidChrome" in item)
            item.solidChrome = Qt.binding(function() { return window.turboActive });
    }

    // ======================================================================
    // LAYOUT — Floating panels overlay the video, transport bar stays full-width
    // ======================================================================
    Rectangle {
        anchors.fill: parent
        color: window.turboActive ? "#000000" : Theme.base
        radius: window.maximizedOrFull || window.miniModeActive ? 0 : Theme.radiusPanel
        visible: !window.miniModeActive

        TitleBar {
            id: titleBar
            width: parent.width
            anchors.top: parent.top
            activeMode: window.activeMode
            visible: !window.fullscreen && !window.miniModeActive
            height: (window.fullscreen || window.miniModeActive) ? 0 : Theme.titleBarHeight
            onModeRequested: function(id) { Actions.switchMode(id) }
        }

        Item {
            id: body
            visible: !window.miniModeActive
            anchors.top: titleBar.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom

            // How much of the body's bottom edge the mode's transport bar owns.
            //
            // The bar lives inside the Stage and is anchored to its bottom, so
            // a panel anchored to `body.bottom` would sit *on top of* it and
            // swallow the controls. Both docks therefore stop short by exactly
            // the bar's own height — they end where the controls begin.
            //
            // Read from the Loader rather than hardcoded: each mode declares
            // its own bar height (§B.2 — Local's two rows are 72px, M3U's
            // single row is shorter), and `transportLoader.height` follows the
            // loaded item's implicitHeight. A mode with no bar reports 0.
            //
            // Gated on `chromeVisible` so that when the bar fades out under
            // auto-hide (§P1.4) the panels reclaim the full height instead of
            // leaving a dead strip where the bar used to be.
            readonly property bool hasTransport:
                !!window.modeSpec && !!window.modeSpec.transportQml
            readonly property real transportInset:
                (hasTransport && transportLoader.active && window.chromeVisible)
                ? transportLoader.height : 0

            // Stage takes full width — panels float on top
            Stage {
                id: stage
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                // Stage caches only modes that explicitly request it. Web uses
                // this to keep live WebView2 tabs/pages alive across a mode
                // switch; Local and M3U continue to unload normally.
                modeSpecs: Modes.list
                activeMode: window.activeMode
            }

            // Letterbox fill behind the native Turbo surface. If the HWND does
            // not cover every pixel of the body (aspect-fit), this — not the
            // desktop — is what shows in the gap.
            Rectangle {
                objectName: "turboLetterbox"
                anchors.fill: parent
                color: "#000000"
                visible: window.turboActive && !window.miniModeActive
                z: 0
            }

            // ----------------------------------------------------------------
            // TURBO — the native video surface, inside this window (§V.3).
            //
            // Occupies the picture rectangle (letterbox is the black fill
            // behind it). Instantiated only while the
            // engine reports it is genuinely on the native route, so a Soft
            // session (which is every session on a platform without the route)
            // never creates a WindowContainer at all. Any problem adopting the
            // child is reported straight back to the engine, which continues
            // the same media on Soft (§V.4).
            Loader {
                id: turboSurfaceLoader
                anchors.fill: parent
                z: 1
                // A Loader, not a hidden item: an invisible WindowContainer is
                // still a constructed one, and there is no reason for a Soft
                // session to own a native-window embedder it will never use.
                active: window.turboActive && !window.miniModeActive
                sourceComponent: turboSurfaceComponent
            }

            Component {
                id: turboSurfaceComponent

                TurboSurfaceHost {
                    turboActive: window.turboActive
                    videoWidth: window.turboVideoWidth
                    videoHeight: window.turboVideoHeight
                    windowProvider: function() {
                        return (typeof App !== "undefined" && App && App.turboWindow)
                               ? App.turboWindow() : null;
                    }
                    onFailed: function(reason) { window.reportTurboFailure(reason) }
                }
            }

            // ----------------------------------------------------------------
            // CHROME LAYER — the transport bar, both docks and the OSD.
            //
            // Grouped into one item for exactly one reason: a native child
            // window (Turbo) is composited above the Qt Quick scene graph, so
            // ordinary QML siblings cannot paint over it. While Turbo runs,
            // this whole layer is moved into the transparent overlay window
            // (§V.3) and moved straight back afterwards — one implementation of
            // every control, in one of two homes, never two copies.
            //
            // In Soft (and therefore in every non-Windows session) it never
            // leaves this window and the layout is exactly what it always was.
            Item {
                id: chromeLayer
                objectName: "chromeLayer"
                anchors.fill: parent
                z: 5

                // VideoStage's click target lives in the main window. Once this
                // layer moves into the overlay, those clicks never arrive, so
                // the same play/pause + fullscreen actions are offered here,
                // underneath the docks and the bar.
                MouseArea {
                    id: overlayStageClick
                    anchors.fill: parent
                    z: -1
                    acceptedButtons: Qt.LeftButton
                    hoverEnabled: true
                    onClicked: Actions.playPause()
                    onDoubleClicked: Actions.toggleFullscreen()
                    onPositionChanged: function(mouse) {
                        window.notePointer(mouse.x, mouse.y)
                    }
                }

                // The mode's own bar, floating over the video (§B.4).
                Loader {
                    id: transportLoader
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    source: body.hasTransport ? window.modeSpec.transportQml : ""
                    active: body.hasTransport
                    opacity: window.chromeVisible ? 1 : 0
                    visible: body.hasTransport && opacity > 0

                    Behavior on opacity {
                        NumberAnimation { duration: Theme.durAutoHide; easing.type: Theme.easing }
                    }

                    // A one-shot assignment in onLoaded is a *copy*, not a
                    // binding: the bar would keep whatever repeat mode and
                    // track list existed the instant it loaded. Binding
                    // properties on the Loader propagates them to `item` and
                    // keeps updating, which is what makes the subtitle popover
                    // and the repeat/shuffle buttons reflect reality.
                    //
                    // Guarded with hasOwnProperty-free `??`-style defaults so a
                    // mode whose bar declares fewer properties (M3U's six
                    // controls, §B.2) still loads cleanly.
                    onLoaded: window.bindTransport(item)
                }

                // Slim progress hairline in fullscreen once the chrome is gone (§7).
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width * (Player ? Player.position : 0)
                    height: 2
                    // A browser never inherits the player's progress hairline,
                    // even if the OS/window enters fullscreen by another path.
                    visible: window.usesPlayer() && window.fullscreen && !window.chromeVisible
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.accent }
                        GradientStop { position: 1.0; color: Theme.accentAlt }
                    }
                }

                // Left panel — floats over the stage (overlay).
                // Stops at the top of the transport bar so the controls stay
                // visible and clickable while the dock is open.
                PanelHost {
                    id: panelHost
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: body.transportInset
                    open: window.leftPanelOpen && window.leftPanelAvailable()
                          && (!window.fullscreen || window.chromeVisible)
                    // Clearing the source matters as well as width: a native Web
                    // stage must not leave Web's placeholder panel instantiated
                    // behind an invisible zero-width dock.
                    source: window.leftPanelAvailable() && window.modeSpec ? window.modeSpec.panelQml : ""
                    // Backdrop blur samples scene-graph pixels. Turbo's picture
                    // is a native child window, which MultiEffect cannot read —
                    // and once this layer lives in the overlay window the Stage
                    // is not even in the same scene. Dropping the source there
                    // is honest (a tinted panel, §V.3) instead of asking Qt to
                    // sample across windows. Soft keeps the full blur.
                    blurSource: window.chromeBlurSource
                    z: 10

                    // Match the bar's own fade so the panel edge and the bar move
                    // together rather than the panel snapping to a new height.
                    Behavior on anchors.bottomMargin {
                        NumberAnimation { duration: Theme.durAutoHide; easing.type: Theme.easing }
                    }
                }

                // Right panel — floats over the stage (overlay).
                // Same bottom stop as the left dock — see body.transportInset.
                InfoPanel {
                    id: infoPanel
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: body.transportInset
                    // Gated on the mode's rich-chrome flag: in M3U/Web the dock is
                    // simply absent — even if it was open when the chip flipped.
                    // In fullscreen panels auto-hide together with the transport
                    // bar (chromeVisible) — move mouse to bring all back.
                    open: window.rightPanelOpen && window.rightDockAvailable()
                          && (!window.fullscreen || window.chromeVisible)
                    blurSource: window.chromeBlurSource
                    z: 10

                    Behavior on anchors.bottomMargin {
                        NumberAnimation { duration: Theme.durAutoHide; easing.type: Theme.easing }
                    }
                }

                // ------------------------------------------------------------
                // OSD — a sibling of the docks at a higher z, NOT a child of Stage.
                //
                // It used to live inside Stage, which is a z:0 sibling of two z:10
                // docks. z only orders siblings, so every pill — status, volume and
                // the resume toast — was painted *underneath* the 300px playlist
                // dock that shares its top-left origin, and was simply invisible in
                // windowed mode with the queue open. It only ever looked correct in
                // fullscreen, where both docks are forced shut.
                //
                // Anchored inside the docks rather than merely drawn over them: a
                // pill floating on top of the glass would be legible but would sit
                // on the wrong background. Both margins animate with the docks so
                // the pill slides with them instead of jumping.
                Osd {
                    id: osdLayer
                    anchors.fill: parent
                    // Both docks already animate their own width, and the transport
                    // inset animates with the chrome, so these margins inherit that
                    // motion. A Behavior here would animate an already-animating
                    // value and make the pill lag behind the dock edge.
                    anchors.leftMargin: panelHost.width
                    anchors.rightMargin: infoPanel.width
                    anchors.bottomMargin: body.transportInset
                    z: 20
                    osdEnabled: window.osdEnabled()
                    suppressed: settingsDialog.visible
                    // The clock, the seek bar and the toast all read time the same
                    // way — one formatter, not three (§4.1).
                    formatTime: window.formatTime
                }
            }
        }
    }

    // ======================================================================
    // TURBO CHROME OVERLAY — §V.3.
    //
    // Created only while Turbo is actually running. On load the chrome layer
    // moves into it; on unload — including a Turbo failure falling back to
    // Soft — it moves straight back into `body`, so the controls can never be
    // stranded in a window that is going away.
    // ======================================================================
    Loader {
        id: turboChromeLoader
        active: window.turboActive && !window.miniModeActive
        sourceComponent: turboChromeComponent
        // Do not reparent on the same frame the overlay is created: the docks'
        // MultiEffect must be destroyed first (chromeBlurSource is already
        // null), otherwise Qt logs "Cannot use same item on different windows"
        // and the playlist/info panels vanish under the HWND.
        onLoaded: chromeMoveTimer.restart()
        // Runs before the Window is destroyed, which is the only safe moment
        // to take the chrome back out of it.
        onActiveChanged: if (!active) {
            chromeMoveTimer.stop()
            window.moveChromeHome()
        }
    }

    Timer {
        id: chromeMoveTimer
        interval: 16
        repeat: false
        onTriggered: window.moveChromeToOverlay()
    }

    Component {
        id: turboChromeComponent

        TurboChromeWindow {
            hostWindow: window
            // The body rectangle in window coordinates. The container
            // Rectangle fills the window with no offset of its own, so the
            // only inset is the title bar's height (zero in fullscreen).
            bodyRect: Qt.rect(0, titleBar.height, body.width, body.height)
            visible: true
        }
    }

    function moveChromeToOverlay() {
        if (!window.turboActive)
            return;
        var overlay = turboChromeLoader.item;
        if (!overlay || !overlay.hostItem)
            return;
        chromeLayer.parent = overlay.hostItem;
        window.chromeInOverlay = true;
    }

    function moveChromeHome() {
        if (chromeLayer.parent !== body)
            chromeLayer.parent = body;
        window.chromeInOverlay = false;
    }

    // ======================================================================
    // MINI BAR — §M.3 / §M.4 — v1.1 fixed 460×44, always-on-top
    // ======================================================================
    MiniBar {
        id: miniBar
        anchors.centerIn: parent
        width: window.miniBarWidth
        height: window.miniBarHeight
        visible: window.miniModeActive
        z: 50

        onSeekRequested: function(frac) {
            Actions.seekFraction(frac);
        }
    }

    // ======================================================================
    // AUTO-HIDE — §P1.4
    // **Fullscreen only.** Playing + pointer still 2.5 s -> the transport bar
    // and the mouse cursor fade; any pointer motion brings both straight back.
    //
    // In windowed mode the bar is permanent. Hiding it there is the wrong
    // trade: the window already has its own chrome and borders, the video does
    // not fill the screen, and there is nothing immersive to protect — it just
    // makes the controls disappear from under the pointer while the user is
    // still working in the window. `autoHideActive` is the single gate, so the
    // rule lives in exactly one place rather than being re-tested at each of
    // the sites that reads `chromeVisible`.
    // ======================================================================
    readonly property bool autoHideActive: fullscreen

    // Entering or leaving fullscreen resets the cycle. Leaving is the important
    // direction: without this, exiting while the bar is hidden would drop the
    // user into a window with no controls and no cursor, and nothing windowed
    // ever hides or shows them again.
    onAutoHideActiveChanged: {
        lastPointerX = -1;      // the pointer's frame of reference just changed
        lastPointerY = -1;
        wakeChrome();
    }

    MouseArea {
        id: idleWatcher
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true
        z: -1

        // Same real-movement test as cursorBlanker, for the same reason: a
        // stationary pointer must not be able to keep the chrome awake. Layout
        // changes when the bar fades (the stage resizes under the pointer) also
        // produce positionChanged with the mouse untouched, which would
        // re-show the bar the instant it hid.
        onPositionChanged: function(mouse) { window.notePointer(mouse.x, mouse.y) }
    }

    // Cursor blanking, fullscreen only.
    //
    // A separate area on top rather than a `cursorShape` on idleWatcher,
    // because the cursor is decided by the *topmost* item under the pointer:
    // idleWatcher sits at z:-1, so VideoStage's click area (and every button)
    // would win and keep drawing an arrow over the picture. This one sits above
    // everything and takes `Qt.NoButton`, so it paints the cursor without
    // swallowing a single click — presses still reach the stage and the bar
    // underneath. It exists only while the chrome is hidden, so in windowed
    // mode, while paused, and for as long as the pointer keeps moving it is
    // simply not instantiated.
    MouseArea {
        id: cursorBlanker
        anchors.fill: parent
        z: 10000
        visible: window.autoHideActive && !window.chromeVisible
        enabled: visible
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true
        cursorShape: Qt.BlankCursor

        onPositionChanged: function(mouse) { window.notePointer(mouse.x, mouse.y) }
    }

    // ------------------------------------------------- pointer bookkeeping --
    // **Only a real move may wake the chrome.**
    //
    // `positionChanged` does not mean "the user moved the mouse". It also fires
    // when an area appears under a stationary pointer (the pointer has
    // "entered" something new) and when the scene moves *beneath* a stationary
    // pointer — which is exactly what happens the moment the transport bar
    // fades and the stage relayouts under the cursor.
    //
    // Waking on those is a self-sustaining loop: hide -> blanker appears and
    // the layout shifts -> synthetic positionChanged -> wake -> 2.5 s -> hide,
    // forever. In fullscreen the bar and cursor would flicker on a 2.5 s cycle
    // and never settle. Comparing against the last seen coordinates is what
    // separates a genuine move from those artefacts.
    property real lastPointerX: -1
    property real lastPointerY: -1

    function notePointer(x, y) {
        // First sighting: record, do not wake. Otherwise the very first event
        // after the chrome hides — which is usually synthetic — un-hides it.
        if (lastPointerX < 0 && lastPointerY < 0) {
            lastPointerX = x;
            lastPointerY = y;
            return;
        }
        var moved = Math.abs(x - lastPointerX) > 2 || Math.abs(y - lastPointerY) > 2;
        lastPointerX = x;
        lastPointerY = y;
        if (moved)
            wakeChrome();
    }

    function wakeChrome() {
        chromeVisible = true;
        if (autoHideActive)
            idleTimer.restart();
        else
            idleTimer.stop();
    }

    Timer {
        id: idleTimer
        interval: Settings.get("ui.autoHideDelayMs", 2500)
        // Never started in windowed mode — wakeChrome() is the only thing that
        // starts it, and it refuses to unless autoHideActive.
        running: false
        onTriggered: {
            if (!window.autoHideActive)
                return;
            var bar = transportLoader.item;
            var busy = bar && ((bar.popoverOpen === true) || (bar.scrubbing === true));
            if (Player && Player.isPlaying && !busy)
                window.chromeVisible = false;
            else if (busy)
                idleTimer.restart();   // re-arm; the popover will not stay open forever
        }
    }

    // `target` is guarded rather than a bare `Player`. On shutdown Qt clears
    // the context property before this element is destroyed, so the binding
    // re-evaluates to null/undefined and Qt tries to disconnect from nothing —
    // which is the `QObject::disconnect: Unexpected nullptr parameter` line in
    // the exit log. Resolving to `null` explicitly makes the detach a no-op.
    Connections {
        target: (typeof Player !== "undefined" && Player) ? Player : null
        enabled: target !== null

        function onStateChanged() {
            if (target && !target.isPlaying)
                window.wakeChrome();     // never hide while paused
        }
    }

    // ======================================================================
    // RESUME TOAST — §P1.5.
    //
    // Purely a listener on the existing resumePrompted signal: openPath() has
    // already applied the saved position by the time this fires, so the toast
    // reports what happened rather than deciding it. Local-only, because the
    // signal is only reachable through a mode that drives the shared player.
    // ======================================================================
    Connections {
        target: App
        function onResumePrompted(path, positionMs) {
            if (window.osdEnabled())
                osdLayer.showResume(path, positionMs);
        }
    }

    // ======================================================================
    // NOW-PLAYING TOAST — one hook for every media change. The core emits
    // mediaNameChanged from the single media-open path (app.py), so
    // Next/Previous, clicking a queue/channel row, auto-advance at end of
    // media and the first open all report here. M3U supplies its parsed channel
    // name through the generic context protocol; Local falls back to its file
    // name without teaching this shared shell about either mode.
    Connections {
        target: App
        function onMediaNameChanged() {
            var name = window.playbackDisplayName();
            if (name.length === 0)
                return;                  // stop / nothing playing
            if (!window.osdEnabled())
                return;
            if (osdLayer.resumeShowing)
                return;                  // the resume toast owns this open
            osdLayer.show("Now Playing: " + window.shortToastName(name),
                          App.hasVideo ? Glyphs.video : Glyphs.music);
        }
    }

    // ======================================================================
    // MODE-SWITCH CLEANUP — the shared OSD must not outlive its mode.
    //
    // A mode switch stops the current player but usually does not open new
    // media, so no mediaChanged arrives to retire a visible toast. Without
    // this, a Resume / Start Over, Now Playing, volume or glyph toast shown in
    // Local mode keeps floating over M3U (and vice versa) until its own timer
    // runs out — and Start Over would act on media that belongs to another
    // mode. osdLayer.clear() retires every pill, timer and the stored resume
    // path in one call. This is the only mode-change cleanup; the modes
    // themselves must not add Local-only or M3U-only variants.
    Connections {
        target: App
        function onActiveModeChanged() { osdLayer.clear() }
    }

    Connections {
        target: osdLayer

        function onStartOverClicked(path) {
            if (!window.usesPlayer())
                return;
            // One call, not three steps here: App.startOver() cancels the
            // engine's pending resume seek, clears the saved position and
            // rewinds, in that order. Doing it in QML got the order wrong —
            // the queued resume seek landed after the seek to 0 and dragged
            // playback straight back to where the user asked to leave.
            App.startOver(path);
        }
    }

    // A toast that outlives the media it describes is a trap: Start Over would
    // rewind whatever is playing now. Retire it whenever the media changes.
    //
    // Safe against retiring the toast it belongs to: openPath() opens the media
    // first and emits resumePrompted second, so the mediaChanged that carries
    // this file has already been delivered by the time the toast appears. Any
    // mediaChanged after that is genuinely a different file.
    Connections {
        target: (typeof Player !== "undefined" && Player) ? Player : null
        enabled: target !== null
        function onMediaChanged() { osdLayer.hideResume() }
    }

    // ======================================================================
    // HOTKEYS — §P1.5. Every binding invokes an Actions entry, never a
    // behaviour of its own. The primary implementation is in globalShortcuts
    // (WindowShortcut) so shortcuts work even when a child TextField has focus.
    //
    // NOTE: Ctrl+1/2/3 for mode switching are ONLY defined in globalShortcuts.
    // WebStage also defines Ctrl+1/2/3 for tab switching with its own enabled
    // condition (webStage.stageActive && browser exists). These are mutually
    // exclusive: when in Web mode, Main.qml's shortcuts are disabled and
    // WebStage's shortcuts are enabled (and vice versa).
    //
    // This Keys handler is a FALLBACK ONLY for special cases where Shortcut
    // context is blocked (e.g. WebView2 child HWND has native focus that
    // prevents Qt from receiving the event at all). It requires focus.
    // ======================================================================
    Item {
        anchors.fill: parent
        focus: true

        Keys.onPressed: function(event) {
            window.wakeChrome();
            var ctrl = event.modifiers & Qt.ControlModifier;
            var alt = event.modifiers & Qt.AltModifier;

            // Alt+1/2/3 — mode switching always, even in Web (no conflict with browser shortcuts)
            // This is a fallback; the primary implementation is in globalShortcuts
            if (alt && !ctrl) {
                switch (event.key) {
                case Qt.Key_1: Actions.switchMode("local"); event.accepted = true; return;
                case Qt.Key_2: Actions.switchMode("m3u");   event.accepted = true; return;
                case Qt.Key_3: Actions.switchMode("web");   event.accepted = true; return;
                }
            }

            // Ctrl+1/2/3 for mode switching — fallback only (primary is in globalShortcuts)
            // Only fire when NOT in Web mode (Web mode uses Ctrl+1/2/3 for tab switching)
            if (ctrl && window.activeMode !== "web") {
                switch (event.key) {
                case Qt.Key_1: Actions.switchMode("local"); event.accepted = true; return;
                case Qt.Key_2: Actions.switchMode("m3u");   event.accepted = true; return;
                case Qt.Key_3: Actions.switchMode("web");   event.accepted = true; return;
                }
            }

            // Fallback for F when native WebView2 child has focus and WindowShortcut misses
            if (event.key === Qt.Key_F && !ctrl && !event.modifiers) {
                Actions.toggleFullscreen(); event.accepted = true; return;
            }
            // Other shortcuts (Space, arrows, etc.) are handled by globalShortcuts WindowShortcut
        }
    }

    // ----------------------------------------------------------------
    // GLOBAL SHORTCUTS — WindowShortcut so they fire even when a child
    // TextField/ListView has focus (Keys.onPressed above only fires when
    // the Item itself has focus). Media keys are gated by
    // isTextInputFocused to avoid typing 'f', 'm', etc in a search box
    // triggering fullscreen/mute.
    // This guarantees Ctrl+1/2/3 always work — the bug the owner reported.
    // ----------------------------------------------------------------
    Item {
        id: globalShortcuts

        property bool isTextInputFocused: {
            var item = window.activeFocusItem;
            if (!item) return false;
            // GlassField / TextField / TextInput all have text + cursorPosition
            if (typeof item.text !== "undefined" && typeof item.cursorPosition !== "undefined")
                return true;
            return false;
        }
        readonly property bool mediaKeys: !!window.modeSpec && window.modeSpec.mediaKeysEnabled
        readonly property bool canMedia: mediaKeys && !isTextInputFocused

        // --- Mode switching — always global, no conflict ---
        // Ctrl+1/2/3 switches modes when NOT in Web (in Web, Ctrl+1..9 switches tabs — standard browser UX)
        Shortcut { sequence: "Ctrl+1"; context: Qt.WindowShortcut; enabled: window.activeMode !== "web"; onActivated: Actions.switchMode("local") }
        Shortcut { sequence: "Ctrl+2"; context: Qt.WindowShortcut; enabled: window.activeMode !== "web"; onActivated: Actions.switchMode("m3u") }
        Shortcut { sequence: "Ctrl+3"; context: Qt.WindowShortcut; enabled: window.activeMode !== "web"; onActivated: Actions.switchMode("web") }
        // Alt+1/2/3 switches modes even in Web — no conflict with Web tab switching
        Shortcut { sequence: "Alt+1"; context: Qt.WindowShortcut; onActivated: Actions.switchMode("local") }
        Shortcut { sequence: "Alt+2"; context: Qt.WindowShortcut; onActivated: Actions.switchMode("m3u") }
        Shortcut { sequence: "Alt+3"; context: Qt.WindowShortcut; onActivated: Actions.switchMode("web") }

        // --- Fullscreen — global even in Web ---
        Shortcut { sequence: "F"; context: Qt.WindowShortcut; enabled: !globalShortcuts.isTextInputFocused; onActivated: Actions.toggleFullscreen() }

        // --- Panels / file dialogs — gated ---
        Shortcut { sequence: "Ctrl+O"; context: Qt.WindowShortcut; enabled: window.usesPlayer(); onActivated: Actions.addFiles() }
        Shortcut { sequence: "Ctrl+E"; context: Qt.WindowShortcut; enabled: window.rightDockAvailable(); onActivated: Actions.showEqualizer() }
        Shortcut { sequence: "Ctrl+L"; context: Qt.WindowShortcut; enabled: window.leftPanelAvailable(); onActivated: Actions.toggleLeftPanel() }
        Shortcut { sequence: "Ctrl+I"; context: Qt.WindowShortcut; enabled: window.rightDockAvailable(); onActivated: Actions.toggleRightPanel() }

        // --- Media — gated by mediaKeys and not typing ---
        Shortcut { sequence: "Space"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.playPause() }
        Shortcut { sequence: "Left"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.seekRelative(-10000) }
        Shortcut { sequence: "Shift+Left"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.seekRelative(-60000) }
        Shortcut { sequence: "Right"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.seekRelative(10000) }
        Shortcut { sequence: "Shift+Right"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.seekRelative(60000) }
        Shortcut { sequence: "Up"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.adjustVolume(5) }
        Shortcut { sequence: "Down"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.adjustVolume(-5) }
        Shortcut { sequence: "M"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.toggleMute() }
        Shortcut { sequence: "S"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.cycleSubtitleTrack() }
        Shortcut { sequence: "A"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.cycleAudioTrack() }
        Shortcut { sequence: "L"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.cycleRepeat() }
        Shortcut { sequence: "N"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.next() }
        Shortcut { sequence: "Shift+N"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.previous() }
        Shortcut { sequence: "P"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia && window.activeMode !== "m3u"; onActivated: Actions.previous() }
        Shortcut { sequence: "["; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.stepRate(-1) }
        Shortcut { sequence: "]"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.stepRate(1) }
        Shortcut { sequence: "Delete"; context: Qt.WindowShortcut; enabled: globalShortcuts.canMedia; onActivated: Actions.clearSelected() }
        // Escape is also a global shortcut for reliability (Keys above may miss when WebView2 child has focus)
        Shortcut { sequence: "Escape"; context: Qt.WindowShortcut; onActivated: {
            if (window.miniModeActive) { window.leaveMiniMode(); return; }
            if (window.fullscreen && (window.leftPanelOpen || window.rightPanelOpen)) {
                if (window.leftPanelOpen && window.leftPanelAvailable()) { window.leftPanelOpen = false; Settings.set("window.leftPanelVisible", false); }
                if (window.rightPanelOpen && window.rightDockAvailable()) { window.rightPanelOpen = false; Settings.set("window.rightPanelVisible", false); }
                window.wakeChrome(); return;
            }
            Actions.exitFullscreen();
        } }
    }

    // ======================================================================
    // DRAG AND DROP — anywhere in the window, same handler as Add Files (§4.1)
    // ======================================================================
    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            // A file dropped on Web belongs to the browser/page, not Halcyon's
            // media queue.  Local/M3U retain their existing one append path.
            if (!window.usesPlayer())
                return;
            if (drop.hasUrls) {
                var paths = [];
                for (var i = 0; i < drop.urls.length; i++)
                    paths.push(drop.urls[i].toString());
                Actions.addPaths(paths);       // the one append path
                drop.accept();
            }
        }
    }

    // ======================================================================
    // DIALOGS
    // ======================================================================
    FileDialog {
        id: fileDialog
        title: "Add files"
        fileMode: FileDialog.OpenFiles
        nameFilters: [
            "Media files (*.mkv *.mp4 *.avi *.mov *.wmv *.ts *.flv *.webm *.m4v *.mpg *.mpeg *.mp3 *.flac *.aac *.opus *.ogg *.wav *.m4a *.wma)",
            "Video (*.mkv *.mp4 *.avi *.mov *.wmv *.ts *.flv *.webm)",
            "Audio (*.mp3 *.flac *.aac *.opus *.ogg *.wav *.m4a)",
            "All files (*)"
        ]
        onAccepted: {
            var paths = [];
            for (var i = 0; i < selectedFiles.length; i++)
                paths.push(selectedFiles[i].toString());
            Actions.addPaths(paths);
        }
    }

    FolderDialog {
        id: folderDialog
        title: "Add folder"
        onAccepted: Actions.addPaths([selectedFolder.toString()])
    }

    FileDialog {
        id: subtitleDialog
        title: "Load subtitle file"
        nameFilters: ["Subtitles (*.srt *.ass *.ssa *.sub *.vtt)", "All files (*)"]
        onAccepted: { App.loadSubtitle(selectedFile.toString()); Actions.osd("Subtitle loaded", Glyphs.subtitles) }
    }

    SettingsDialog {
        id: settingsDialog
    }

    // ---- Phase R mobile remote (v1.2) ------------------------------------
    // The remote is a second doorway onto the same action host (§4.1): these
    // Connections translate bridge requests into the identical existing
    // actions. `remoteBridge` is null when the bridge is absent (tests,
    // older launchers) — a Connections on null is a silent no-op.
    property var remoteBridge: typeof RemoteBridge !== "undefined" ? RemoteBridge : null

    Connections {
        target: window.remoteBridge
        function onToggleFullscreenRequested() {
            if (window.remoteBridge) actionHost.toggleFullscreen()
        }
    }
}
