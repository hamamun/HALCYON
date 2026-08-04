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

    // The OS-level title: taskbar button, Alt-Tab, window list. The frameless
    // shell draws no caption of its own, so this is otherwise invisible to the
    // user — but it is what Windows shows, and "Halcyon" for every window is
    // useless the moment two copies are open.
    //
    // For M3U, the channel name is shown instead of file metadata.
    title: {
        // A mode may contribute an OS-level title through App's generic
        // protocol.  Web uses this for the active page title without making
        // this shared shell name/import the Web mode directly.
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

    Component.onCompleted: {
        // Seed the plain dock bools from the persisted settings. Done here
        // rather than as property bindings so that the imperative writes in
        // toggleRightPanel()/showLyrics()/showEqualizer() never clobber a
        // declared binding (and so Qt never logs "Overwriting binding").
        leftPanelOpen = Settings.get("window.leftPanelVisible", true);
        rightPanelOpen = Settings.get("window.rightPanelVisible", false);
        restoreGeometry();
        Actions.host = actionHost;
    }

    onClosing: {
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
        // readout (§6.2) that holds for 800 ms after the drag ends.
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
        }
        function toggleRightPanel() {
            if (!window.rightDockAvailable()) return;   // M3U/Web: inert (§P2.4)
            window.rightPanelOpen = !window.rightPanelOpen;
            Settings.set("window.rightPanelVisible", window.rightPanelOpen);
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
    }

    // ======================================================================
    // LAYOUT — Floating panels overlay the video, transport bar stays full-width
    // ======================================================================
    Rectangle {
        anchors.fill: parent
        color: Theme.base
        radius: window.maximizedOrFull ? 0 : Theme.radiusPanel

        TitleBar {
            id: titleBar
            width: parent.width
            anchors.top: parent.top
            activeMode: window.activeMode
            visible: !window.fullscreen
            height: window.fullscreen ? 0 : Theme.titleBarHeight
            onModeRequested: function(id) { Actions.switchMode(id) }
        }

        Item {
            id: body
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
                open: !window.fullscreen && window.leftPanelOpen && window.leftPanelAvailable()
                // Clearing the source matters as well as width: a native Web
                // stage must not leave Web's placeholder panel instantiated
                // behind an invisible zero-width dock.
                source: window.leftPanelAvailable() && window.modeSpec ? window.modeSpec.panelQml : ""
                blurSource: stage
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
                open: !window.fullscreen && window.rightPanelOpen
                      && window.rightDockAvailable()
                blurSource: stage
                z: 10

                Behavior on anchors.bottomMargin {
                    NumberAnimation { duration: Theme.durAutoHide; easing.type: Theme.easing }
                }
            }

            // ----------------------------------------------------------------
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
    // behaviour of its own.
    // ======================================================================
    Item {
        anchors.fill: parent
        focus: true

        readonly property bool mediaKeys: !!window.modeSpec && window.modeSpec.mediaKeysEnabled

        Keys.onPressed: function(event) {
            window.wakeChrome();
            var shift = event.modifiers & Qt.ShiftModifier;
            var ctrl = event.modifiers & Qt.ControlModifier;

            if (ctrl) {
                switch (event.key) {
                // These are player/dock commands, not browser shortcuts. In
                // Web they are inert: no media dialog and no empty dock.
                case Qt.Key_O:
                    if (window.usesPlayer()) Actions.addFiles();
                    event.accepted = true; return;
                case Qt.Key_E: Actions.showEqualizer();  event.accepted = true; return;
                case Qt.Key_L: Actions.toggleLeftPanel();  event.accepted = true; return;
                case Qt.Key_I: Actions.toggleRightPanel(); event.accepted = true; return;
                }
            }

            if (event.key === Qt.Key_Escape) {
                Actions.exitFullscreen();
                event.accepted = true;
                return;
            }

            if (!mediaKeys)
                return;                  // Web mode: media keys are inert (§P3.6)

            switch (event.key) {
            case Qt.Key_Space:  Actions.playPause(); break;
            case Qt.Key_Left:   Actions.seekRelative(shift ? -60000 : -10000); break;
            case Qt.Key_Right:  Actions.seekRelative(shift ?  60000 :  10000); break;
            case Qt.Key_Up:     Actions.adjustVolume(5); break;
            case Qt.Key_Down:   Actions.adjustVolume(-5); break;
            case Qt.Key_M:      Actions.toggleMute(); break;
            case Qt.Key_F:      Actions.toggleFullscreen(); break;
            case Qt.Key_S:      Actions.cycleSubtitleTrack(); break;
            case Qt.Key_A:      Actions.cycleAudioTrack(); break;
            case Qt.Key_L:      Actions.cycleRepeat(); break;
            case Qt.Key_BracketLeft:  Actions.stepRate(-1); break;
            case Qt.Key_BracketRight: Actions.stepRate(1); break;
            case Qt.Key_Delete: Actions.clearSelected(); break;
            default: return;
            }
            event.accepted = true;
        }
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
}
