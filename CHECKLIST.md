# Halcyon — Build Checklist

> Companion to `HALCYON_PLAN.md` v3.1. Every task, in build order, with a plan reference.
>
> **How to use this file**
> - **`[ ]` → `[x]`** is set by *me* when a task is implemented.
> - **`◻` → `◼`** is set by *you* when you've verified it works. Only your marks count for phase sign-off.
> - Update this file at the end of every milestone. If a task turns out to be wrong or unnecessary, **strike it and write why** — don't silently delete it.
> - **A phase cannot close with an unticked ◻.**

**Legend** — `[ ]` built · `◻` verified by you · **★** critical path, blocks everything downstream · `§` plan section

---

## Progress

| Phase | Milestones | Build tasks | Your verifications | Tag |
|---|---|---|---|---|
| 0 — Setup | 1 | 0 / 8 | 0 / 1 | — |
| 1 — Local | 10 | 0 / 174 | 0 / 104 | `v0.1.0-local` |
| 2 — M3U | 5 | 0 / 42 | 0 / 43 | `v0.2.0-m3u` |
| 3 — Web | 5 | 0 / 49 | 0 / 40 | `v1.0.0` |
| **Total** | **21** | **0 / 273** | **0 / 188** | |

---|---|---|---|---|
| 1 — Local | 0/10 | 0/187 | 0/58 | `v0.1.0-local` |
| 2 — M3U | 0/5 | 0/61 | 0/27 | `v0.2.0-m3u` |
| 3 — Web | 0/5 | 0/54 | 0/25 | `v1.0.0` |

---

# PHASE 0 — Repository Setup

*Before any code. ~half a day.*

- [ ] `git init`, create branch `phase-1-local` · §A.4
- [ ] `.gitignore` — `.venv/`, `__pycache__/`, `build/`, `dist/`, `*.spec`, `vendor/vlc/`
- [ ] `README.md` — what Halcyon is, how to fetch libVLC binaries into `vendor/vlc/`
- [ ] Commit `HALCYON_PLAN.md` and `CHECKLIST.md` as the first commit
- [ ] `py -3.12 -m venv .venv` · §12
- [ ] `pip install PySide6 python-vlc` *(nothing else yet — smaller surface, easier debugging)*
- [ ] Download libVLC 3.0.21 Win64 → `vendor/vlc/` (`libvlc.dll`, `libvlccore.dll`, `plugins/`)
- [ ] Confirm `python -c "import vlc; print(vlc.libvlc_get_version())"` works against the bundled DLLs

◻ Repo exists, venv activates, libVLC version prints

---

# PHASE 1 — Local Mode

**Ship:** `v0.1.0-local` · **Est:** 15–18 days · **Branch:** `phase-1-local`

---

## ★ Milestone 1.0 — Compositing Spike · §0.6 · 1–2 d

> **THE GATE.** Nothing else is written until every box here is ticked. If this fails, the architecture is wrong and we find out on day two, not month three.

### Build
- [ ] ★ `spike.py` — standalone, throwaway, ~150 lines
- [ ] ★ Allocate a **3-slot ring buffer**, `ctypes` arrays, allocated once and never freed · §0.3
- [ ] ★ `lock` callback returns `&ring[write_idx]` — **no allocation, no copy** inside the callback
- [ ] ★ `unlock` callback — no pixel work
- [ ] ★ `display` callback — atomically publish index, rotate slots
- [ ] ★ **Hold hard Python references to all three callbacks on a long-lived object** · §9 High risk — *a GC'd ctypes callback is an instant segfault*
- [ ] ★ `threading.Lock` guards **only the three integer indices**, never pixel work
- [ ] ★ Request **I420**, not RV32 · §0.4
- [ ] ★ `video_set_format("I420", w, h, pitch)` with correct Y/U/V plane pitches
- [ ] ★ `VideoSurface(QQuickItem)` with `updatePaintNode()`
- [ ] ★ `QImage` constructed as a **view over the raw pointer** — verify no copy occurs
- [ ] ★ `QQuickWindow.createTextureFromImage(..., NoOwnership)`
- [ ] ★ `QSGSimpleTextureNode` wired into the scene graph
- [ ] ★ `yuv420p.frag` — 3 single-channel textures, BT.709 matrix
- [ ] ★ Compile shader with `pyside6-qsb` → `.qsb`
- [ ] ★ QML: `Rectangle`, 60% opacity, `MultiEffect` blur, rounded corners, **on top of** the video item
- [ ] ★ QML: an animated element crossing the video continuously
- [ ] ★ FPS counter + CPU readout visible on screen
- [ ] `--avcodec-threads=0` passed to the VLC instance · §0.5

### ◻ Verify — pass criteria · §0.6
- ◻ Glass panel is **visibly over** the video, blur clearly blending with moving frames
- ◻ Scene graph holds **sustained 60 fps**
- ◻ CPU **under 25%** on 1080p H.264
- ◻ **No tearing**
- ◻ **No flicker or black flash** on window resize
- ◻ Animated element moves smoothly, never stutters
- ◻ Runs 10 minutes with **no crash and no memory growth**

> **If any box fails: STOP.** Do not proceed to 1.1. Try RV32 fallback (§0.4), then re-evaluate.

---

## Milestone 1.1 — Engine Core · 2 d

### Build
- [ ] `engine/video_out.py` — promote the spike's ring buffer to a real module · §0.3
- [ ] Handle **resolution change mid-stream** (reallocate ring safely)
- [ ] Reader refcount so multiple surfaces can bind later (PiP in Phase 2) · §0.3
- [ ] `engine/surface.py` — `VideoSurface` as a registered QML type
- [ ] Aspect-ratio fit: letterbox / pillarbox, correct on resize
- [ ] DPR-aware texture sizing · §9 HiDPI risk
- [x] RV32 + `Format_RGBX8888` fallback path behind a flag · §9
      *(VLC RV32 is host-order RGB, not BGRA — Format_RGB32 swaps red/blue. Fixed in engine/surface.py)*
- [ ] `engine/vlc_engine.py` — instance creation, bundled-DLL path resolution
- [ ] Set `VLC_PLUGIN_PATH` at startup · §9 Nuitka risk
- [ ] `play()` · `pause()` · `stop()` · `toggle()`
- [ ] `seek(ms)` · `seek_relative(±ms)` · `set_position(0..1)`
- [ ] `set_volume()` · `get_volume()` · `set_mute()` · `toggle_mute()`
- [ ] `set_rate()` — 0.5× to 2×
- [ ] Properties: `position`, `duration`, `state`, `is_playing`, `buffered`
- [ ] Qt signals for every state change (playing, paused, stopped, ended, error, buffering, time, length)
- [ ] Event manager attached; **all event callbacks hard-referenced** · §9
- [ ] ★ **Safe shutdown:** `stop()` → await `Stopped` event → `release()`. **Never release from a Qt slot directly** · §9
- [ ] Error surface: unreadable file, missing codec, network failure

### ◻ Verify
- ◻ Play / pause / stop / seek / volume all work from a test script
- ◻ Signals fire correctly and in order
- ◻ Closing during playback exits cleanly, no hang, no segfault
- ◻ 50 rapid open/close cycles — no crash, no leak

---

## ★ Milestone 1.2 — Shell & Foundation · 3 d

> **Gates §4.1 compliance for the entire project.** The `Actions` singleton and `ModeSpec` must exist *before* any UI is written, or duplication creeps in immediately.

### Build — the contract
- [ ] ★ `core/mode_api.py` — `ModeSpec` frozen dataclass · §A.2
- [ ] ★ Fields: `id`, `title`, `panel_qml`, **`stage_qml`**, **`transport_qml`**, `osd_enabled`
- [ ] ★ `stage_qml` defaults to the video surface — *declared now so Phase 3 stays additive* · §P3.3
- [ ] ★ `core/modes.py` — `REGISTRY` list; later phases append exactly one entry
- [ ] ★ `tools/check_isolation.py` · §A.5
  - [ ] Fails if `modes/<a>/` imports `modes/<b>/`
  - [ ] Fails if `engine|core|ui/shell` imports `modes/*`
  - [ ] Fails if a phase-2+ commit touches a frozen phase-1 path
- [ ] ★ `ui/Actions.qml` — singleton, **every** action declared as a named entry · §4.1
- [ ] ★ `ui/Theme.qml` — all tokens from §7, nothing hardcoded anywhere else

### Build — the shell
- [ ] `main.py` — app bootstrap, QML engine, type registration
- [ ] `ui/Main.qml`
- [ ] `ui/shell/Shell.qml` — frameless window
- [ ] 8 resize handles (4 edges + 4 corners), correct cursors
- [ ] Drag-to-move from the title bar
- [ ] Double-click title bar → maximise / restore
- [ ] Windows snap (Aero) works
- [ ] Window geometry saved and restored · §P1.5
- [ ] `ui/shell/TitleBar.qml` — 44px, logo, mode chips **rendered from the registry**, gear, min/max/close
- [ ] ★ Only one chip renders in Phase 1; adding a mode later must require **no edit here**
- [ ] `ui/shell/PanelHost.qml` — single 300px left slot, loads `ModeSpec.panel_qml`
- [ ] `ui/shell/Stage.qml` — loads `ModeSpec.stage_qml`, hosts OSD layer
- [ ] Aurora animated background · §7
- [ ] Idle state: album art + Ken Burns drift
- [ ] `core/settings.py` — JSON in `%APPDATA%\Halcyon`, defaults copied from repo `config/` on first run
- [ ] `ui/components/` — `GlassPanel`, `IconButton`, `Slider`, `Menu`, `Popover`, `ListRow`, `Toolbar` · §B.1
- [ ] ★ Every component reads **only** from `Theme.qml` — no local colours, radii, or durations

### ◻ Verify
- ◻ Window is frameless with working glass; all 8 handles resize correctly
- ◻ Drag-move, double-click maximise, snap all work
- ◻ Geometry survives restart
- ◻ `tools/check_isolation.py` passes
- ◻ Grep confirms **no hardcoded colour or radius** outside `Theme.qml`

---

## Milestone 1.3 — Transport · 3 d

> Per §B.4: `ui/transport/` holds **shared parts**. `modes/local/LocalTransport.qml` arranges them. There is no universal `TransportBar.qml`.

### Build — shared parts (`ui/transport/`)
- [ ] `SeekBar.qml` — 4px at rest, **6px + knob on hover** · §P1.5
- [ ] Buffered region rendered behind the played region
- [ ] Played region uses the accent gradient
- [ ] Click-to-seek anywhere on the track
- [ ] Scrub-drag follows pointer live, commits on release
- [ ] Hover timestamp tooltip *(frame thumbnail deferred to v1.1 · §8)*
- [x] `VolumeControl.qml` — icon plus an **always-visible** slider
      *(revised: the hover-to-expand version never expanded — the IconButton
      swallowed the hover events — and a volume control you cannot see is one
      most people never find.)*
- [x] Mute toggle on icon click; icon reflects level and mute state
- [x] `TimeDisplay.qml` — **three readouts, always visible, fixed order**:
      `remaining · playback · media`
      *(revised: replaces the click-to-toggle elapsed↔remaining control. The
      toggle hid one value behind the other and was undiscoverable.)*
- [ ] `TrackPopover.qml` — CC icon, grouping speed, audio track, embedded +
  local subtitles, subtitle delay; 5-row cap + `ThinScrollBar`; right edge
  anchored under the button, window-edge clamped
- [ ] `SubtitleDownloadDialog.qml` — OpenSubtitles flyout: collapsible
  API-key/languages (persisted), search, best-match top 3 + scrollable rest,
  one-tap download → saved beside media → loaded into Local subtitles
  (`core/subtitles.py`, context property `Subs`)
- [ ] `TransportScrim.qml` — vertical gradient for legibility over bright video

### Build — Local's arrangement
- [ ] `modes/local/LocalTransport.qml` — **two rows, ~72px** · §B.2
- [ ] Row 1: seek bar, full width
- [x] Row 2: ▶ ⏹ ⏮ ⏪ ⏩ ⏭ · volume · time · ☰ ⚙ 🔁 🔀 ⛶
      (☰ = playlist toggle — the left dock previously had no on-screen
      trigger at all, only Ctrl+L)
- [ ] All 14 controls present and wired to `Actions` entries
- [ ] Repeat cycles off → one → all, with distinct icons
- [ ] Shuffle toggles, icon reflects state
- [ ] 40×40 hit targets, glass hover ring, tooltips · §B.1
- [ ] 220 ms `OutCubic` on every transition · §7
- [ ] Auto-hide after 2.5 s of pointer stillness; fade 180 ms · §P1.4
- [ ] Cursor hides with the bar
- [ ] Instant restore on any pointer move, key press, or focus change
- [ ] ★ **Never** auto-hides while a popover is open, while scrubbing, or while paused
- [ ] Fullscreen: button, `F`, and stage double-click all invoke the **same** `Actions` entry · §4.1
- [ ] Fullscreen leaves only a slim progress hairline · §7

### ◻ Verify
- ◻ Every control works
- ◻ Seek bar thickens on hover; scrub-drag is smooth; click-to-seek accurate
- ◻ Volume expands on hover; mute works
- ◻ Time display toggles on click
- ◻ Fullscreen identical via all three triggers
- ◻ Auto-hide timing correct; never hides at the wrong moment
- ◻ Controls remain legible over bright video (scrim working)

---

## Milestone 1.4 — OSD · §6.2 · 1 d

### Build
- [ ] `ui/overlay/Osd.qml` — glass pill, 8px blur, in the scene graph over video
- [ ] Top-left anchor for status lines; centre for large glyphs
- [ ] 800 ms hold + 250 ms fade
- [ ] ★ Repeated triggers **reset the timer** rather than stacking
- [ ] ★ **Never** covers the subtitle safe area (bottom 20%)
- [ ] Suppressed while a menu or panel has focus
- [ ] ★ Driven by `ModeSpec.osd_enabled` — **Local only**

### Build — all 10 triggers · §P1.5
- [ ] Volume change — speaker glyph + level bar + %
- [ ] Mute toggle — muted / unmuted glyph
- [ ] Seek — ⏪/⏩ 10s + new position / duration
- [ ] Play / pause — large centre glyph, quick fade
- [ ] Speed change — `1.25×`
- [ ] Audio switch — `Audio: English (AC3 5.1)`
- [ ] Subtitle switch — `Subtitle: English` / `Subtitles Off`
- [ ] Fullscreen — enter / exit glyph
- [ ] File open — filename + resolution + duration, 3 s
- [ ] Resume — `Resuming from 24:31`

### ◻ Verify
- ◻ All 10 triggers fire with correct content and position
- ◻ Timing correct; rapid repeats reset rather than stack
- ◻ Never overlaps subtitles
- ◻ Readable over both bright and dark video

---

## Milestone 1.5 — Local Panel · 2–3 d

### Build
- [ ] `modes/local/__init__.py` — `ModeSpec` for `"local"`
- [ ] `modes/local/playlist.py` — queue model (`QAbstractListModel`)
- [ ] Duration probed asynchronously — **must not block the UI**
- [ ] `modes/local/LocalPanel.qml`
- [ ] ★ Toolbar — **the only place these four exist** · §4.1
  - [ ] **Add Files** — multi-select dialog, appends
  - [ ] **Add Folder** — recursive scan, media extensions only, appends
  - [ ] **Clear Selected** — enabled only when rows are selected
  - [ ] **Clear Playlist** — confirm dialog if >1 item
- [ ] Rows: index · title · duration · now-playing indicator
- [ ] Drag-to-reorder
- [ ] Double-click to play
- [ ] `Delete` key = Clear Selected (same `Actions` entry, not a second path)
- [ ] Multi-select: Ctrl+click, Shift+click
- [ ] ★ Explorer drag-and-drop **anywhere in the window** → the *same* append handler Add Files calls · §4.1
- [ ] Empty state: prompt that invokes `Actions.addFiles` — **not a second button** · §4.1
- [ ] Repeat / shuffle honoured by next/prev logic
- [ ] `ui/panels/InfoPanel.qml` — right dock, 320px, collapsible, tabs: Info · Lyrics · Equalizer

### ◻ Verify
- ◻ All four toolbar buttons work
- ◻ Add Folder recurses and filters to media only
- ◻ Clear Selected disabled with no selection; confirm appears for Clear Playlist
- ◻ Reorder, double-click play, `Delete` key all work
- ◻ Explorer drop works from any part of the window
- ◻ 500-item playlist scrolls smoothly, UI never blocks on duration probing

---

## Milestone 1.6 — Tracks & Subtitles · 2 d

### Build
- [ ] Enumerate audio tracks; live switching · §P1.5
- [ ] Remember audio track per file
- [ ] Enumerate subtitle tracks; live switching, including "off"
- [ ] External subtitle load via `add_slave()` — `.srt` / `.ass` / `.sub`
- [ ] Auto-load sidecar subtitle matching the filename
- [ ] Subtitle delay ±, in 50 ms steps
- [ ] Subtitle scale and encoding override
- [ ] Verify **embedded ASS/SSA styling is preserved** (blended by VLC pre-callback) · §0.4
- [ ] Verify PGS / VobSub bitmap subtitles render
- [ ] Wire all of it into `TrackPopover.qml`
- [ ] `S` cycles subtitles · `A` cycles audio — both via `Actions`
- [ ] Every change announced by OSD

### ◻ Verify
- ◻ Multi-audio MKV switches correctly, audio actually changes
- ◻ Embedded subs display with correct ASS styling
- ◻ External `.srt` and `.ass` load
- ◻ Sidecar auto-loads
- ◻ Delay adjustment visibly shifts timing
- ◻ PGS/VobSub render
- ◻ OSD announces every change

---

## Milestone 1.7 — Equalizer & Video Adjust · 2 d

### Build
- [ ] `engine/equalizer.py` — `libvlc_audio_equalizer_*` wrapper
- [ ] 10 bands, 31 Hz – 16 kHz, ±20 dB
- [ ] Preamp
- [ ] ~18 built-in VLC presets enumerated
- [ ] User presets saved to `eq.json`
- [ ] Applies live, no playback restart
- [ ] Persists across app restart
- [ ] EQ tab UI in `InfoPanel` — vertical sliders, dB labels, preset dropdown, reset
- [ ] `libvlc_video_set_adjust_*` — contrast, brightness, hue, saturation, gamma
- [ ] 8 video presets: Vivid · Cinema · Warm · Cool · Night · Flat · Punch · Custom
- [ ] Video adjust UI below EQ in the right panel
- [ ] `Ctrl+E` opens the EQ tab

### ◻ Verify
- ◻ Each of the 10 bands audibly changes the sound
- ◻ Presets load and apply
- ◻ Preamp works without clipping
- ◻ Settings survive restart
- ◻ All 5 video adjustments visibly change the picture
- ◻ All 8 video presets work

---

## Milestone 1.8 — Library & Polish · 2 d

### Build
- [ ] `core/library.py` — `recent.json`, capped at 200 entries
- [ ] Position saved every 5 s and on close
- [ ] Resume prompt when >30 s in **and** >5% remaining · §P1.5
- [ ] Resume announced by OSD
- [ ] `core/metadata.py` — title, artist, album, album art via libVLC (no ffprobe)
- [ ] Info tab: filename, resolution, codecs, bitrate, duration, container
- [ ] `core/lyrics.py` — sidecar `.lrc` parsing, timed
- [ ] Embedded lyrics tags
- [ ] Lyrics tab: auto-scroll, current line highlighted, click a line to seek
- [x] Audio-only idle visual: album art + Ken Burns on the stage · §7
      (`ui/shell/NowPlayingCard.qml` — cover, title, artist, album; shown
      whenever the stage has no picture. Audio-reactive bars still to do.)
- [ ] Settings dialog behind the gear · §4.1
- [ ] **Turbo Mode** toggle in Settings — `set_hwnd()` + `--avcodec-hw=d3d11va`; transport drops to a solid strip below the video · §0.5
- [ ] All hotkeys wired, every one invoking an `Actions` entry · §P1.5
  - [ ] `Space` · `←/→` ±10s · `Shift+←/→` ±60s · `↑/↓` volume · `M` · `F` · `S` · `A` · `[`/`]` · `L` · `Ctrl+E` · `Ctrl+O` · `Ctrl+L` · `Ctrl+I` · `Esc`
- [ ] Animation polish pass — every transition on the §7 curve
- [ ] Empty / error / loading states designed, not default

### ◻ Verify
- ◻ Resume prompt appears at the right threshold and works
- ◻ Recent list populates and caps at 200
- ◻ Metadata and album art display; audio-only files look good
- ◻ Lyrics scroll in time; click-to-seek works
- ◻ Every hotkey works
- ◻ Turbo Mode plays 4K smoothly *(with the documented docked-bar trade-off)*

---

## Milestone 1.9 — Package · 2 d

### Build
- [ ] Nuitka build script
- [ ] ★ `--include-data-dir` for `vendor/vlc/plugins` · §9
- [ ] ★ `VLC_PLUGIN_PATH` set correctly at runtime in the frozen build
- [ ] QML resources bundled
- [ ] Compiled `.qsb` shaders included
- [ ] App icon (`.ico`, all sizes)
- [ ] Version metadata in the executable
- [ ] Installer (Inno Setup or similar)
- [ ] First-run: copy `config/` defaults into `%APPDATA%\Halcyon`
- [ ] ★ **Test on a clean Windows machine with no VLC and no Python installed**

### ◻ Verify
- ◻ Installer runs, app launches on a clean machine
- ◻ All formats play in the packaged build
- ◻ Shaders load (no blank/black video)
- ◻ Settings persist to `%APPDATA%`
- ◻ Uninstaller removes cleanly

---

## ◻ PHASE 1 SIGN-OFF · §P1.7

**Compositing**
- ◻ Glass transport renders over playing video, blur visible
- ◻ No flicker / tearing / black flash on resize, maximise, fullscreen
- ◻ 1080p H.264 sustains 60 fps under 25% CPU
- ◻ Panels slide over video without artefacts

**Formats** — all play with no external codecs installed
- ◻ MKV ◻ MP4 ◻ AVI ◻ MOV ◻ WMV ◻ TS ◻ FLV ◻ WebM ◻ HEVC 10-bit
- ◻ MP3 ◻ FLAC ◻ AAC ◻ Opus

**Transport**
- ◻ Play · pause · stop · prev · next
- ◻ Seek ±10 s · scrubber drag · click-to-seek
- ◻ Volume · mute · both OSD-reported
- ◻ Time display toggles elapsed ↔ remaining
- ◻ Fullscreen identical via button, `F`, double-click
- ◻ Repeat off/one/all · shuffle
- ◻ Speed 0.5×–2×

**OSD**
- ◻ All 10 triggers fire, correct position and timing, repeats reset, never covers subtitles

**Playlist**
- ◻ Add Files · Add Folder · Clear Selected · Clear Playlist
- ◻ Drag-reorder · double-click play · `Delete` key · Explorer drop

**Tracks & subs**
- ◻ Multi-audio switch · embedded subs · external `.srt`/`.ass` · sidecar auto-load · delay

**Equalizer**
- ◻ 10 bands live · presets · preamp · persists across restart

**Library**
- ◻ Resume prompt · recent list · lyrics scroll · metadata + art

**Window**
- ◻ All 8 resize handles · drag-move · double-click maximise · geometry remembered

**Isolation**
- ◻ `tools/check_isolation.py` passes
- ◻ No `modes/m3u` or `modes/web` reference exists anywhere

**Stability**
- ◻ 2-hour playback, no memory growth
- ◻ 50 rapid track changes, no crash
- ◻ Close during playback is clean

**→ Merge to `main`, tag `v0.1.0-local`. Foundation is now FROZEN.** · §A.3

---

# PHASE 2 — M3U Mode

**Ship:** `v0.2.0-m3u` · **Est:** 5–6 days · **Branch:** `phase-2-m3u`

> ★ **Additive only.** The single permitted Phase 1 edit is one entry appended to `core/modes.py`. · §A.3

---

## Milestone 2.1 — Parser · 1 d

- [ ] `modes/m3u/parser.py` — `.m3u` and `.m3u8`
- [ ] `#EXTINF` duration + title
- [ ] `tvg-name`, `tvg-logo`, `tvg-id`, `group-title` attributes
- [ ] `#EXTGRP`
- [ ] Relative and absolute paths; local and remote entries
- [ ] Encoding detection (UTF-8, BOM, Latin-1 fallback)
- [ ] Malformed lines skipped, not fatal
- [ ] Nested / chained playlist references handled or explicitly ignored
- [ ] `modes/m3u/playlist.py` — channel model

◻ Parses real-world IPTV playlists · ◻ Malformed files don't crash · ◻ Groups and logos extracted

---

## Milestone 2.2 — Mode Registration · 0.5 d

- [ ] `modes/m3u/__init__.py` — `ModeSpec` for `"m3u"`
- [ ] `controls=["playPause","prev","next","volume","pip","fullscreen"]` — **six** · §P2.3
- [ ] `transport_qml="qrc:/modes/m3u/M3UTransport.qml"`
- [ ] `osd_enabled=False`
- [ ] ★ Append one entry to `core/modes.py` — **the only Phase 1 edit permitted**
- [ ] Second chip appears in the title bar **with no `TitleBar.qml` edit** · §P1.4

◻ Both chips render · ◻ Switching works · ◻ `git diff` shows exactly one Phase 1 line changed

---

## Milestone 2.3 — Panel · 1 d

- [ ] `modes/m3u/M3UPanel.qml`
- [ ] ★ Toolbar: **Clear Playlist only** · §P2.4
- [ ] *Loading `.m3u` is the title-bar Open action — a playlist is a document you open, not an item you append*
- [ ] Rows: channel name · group tag · `tvg-logo` thumbnail when present
- [ ] Logo loading is async and cached; missing logos fall back gracefully
- [ ] Filter/search box narrows the list
- [ ] Optional group-by-category collapse
- [ ] Single-click to play
- [ ] No reorder — the file defines order
- [ ] Right panel hidden by default; EQ still reachable via `Ctrl+I` (**same component**) · §P2.4

◻ Channels list with logos and groups · ◻ Filter works · ◻ Clear Playlist is the only button · ◻ EQ reachable and applies

---

## Milestone 2.4 — Transport · 1 d

- [ ] `modes/m3u/M3UTransport.qml` — ★ **single row, ~52px, designed for six controls** · §B.2
- [ ] ★ **No reserved gaps, no ghost slots** — this is *not* Local's bar with the seek row deleted
- [ ] Built from the **same shared `ui/transport/` parts** — same `IconButton`, same icons, same hover ring · §B.1
- [ ] Play/pause · prev · next · volume+mute · PiP · fullscreen
- [ ] Volume persists across mode switches
- [ ] Buffering indicator for slow streams
- [ ] Stream error state: clear message, no crash, no hang
- [ ] Connection timeout handled with a retry affordance

◻ Exactly six controls · ◻ Layout looks designed for six, balanced, no gaps · ◻ Buttons visually identical to Local's · ◻ Unreachable stream fails gracefully

---

## Milestone 2.5 — Picture-in-Picture · 1–2 d

- [ ] `ui/overlay/PipWindow.qml` — borderless, always-on-top, default 480×270
- [ ] ★ Binds **the same ring buffer** — no second decode, no second player · §0.3
- [ ] ★ Reader refcount respected; main Stage never unbinds · §9
- [ ] Resizable, aspect-locked
- [ ] Snaps to screen corners
- [ ] Main window can minimise while PiP keeps playing
- [ ] Double-click PiP restores the main window
- [ ] Minimal hover controls (play/pause, close) — from shared components
- [ ] Position and size remembered

◻ Opens, stays on top, resizes, snaps · ◻ Main window minimises, PiP keeps playing · ◻ **CPU rise vs non-PiP is negligible** (proves shared buffer) · ◻ Double-click restores

---

## ◻ PHASE 2 SIGN-OFF · §P2.6

**Regression first**
- ◻ **Entire Phase 1 sign-off list re-run and passing**
- ◻ Deleting `modes/m3u/` still leaves a working Local build
- ◻ `git diff phase-1..phase-2` touches no Phase 1 file except the one `core/modes.py` line
- ◻ `tools/check_isolation.py` passes

**M3U**
- ◻ Loads `.m3u` and `.m3u8`, local and remote entries
- ◻ `#EXTINF` name, `group-title`, `tvg-logo` parsed and shown
- ◻ HLS streams play
- ◻ Filter box narrows the list
- ◻ Clear Playlist works and is the only toolbar button
- ◻ Malformed / unreachable entries fail gracefully with a message, no crash

**Controls**
- ◻ Exactly six render: play/pause, prev, next, volume+mute, PiP, fullscreen
- ◻ No seek bar, time display, stop, repeat/shuffle, or track menu — **absent, not greyed**
- ◻ Volume and mute work; volume persists across a mode switch
- ◻ No OSD fires in M3U mode
- ◻ M3U bar is its own layout — single row, balanced, **no empty gaps** · §B.2
- ◻ Equalizer reachable via the right panel and applies to the stream

**PiP**
- ◻ Opens, on top, resizes, snaps
- ◻ Main minimises, PiP plays on
- ◻ Negligible CPU increase
- ◻ Double-click restores

**Mode switching**
- ◻ Both chips render
- ◻ Local ↔ M3U swaps panel and control set correctly
- ◻ Local playlist survives a round-trip to M3U and back
- ◻ The two playlists never contaminate each other

**→ Merge to `main`, tag `v0.2.0-m3u`.**

---

# PHASE 3 — Web Mode

**Ship:** `v1.0.0` · **Est:** 5–6 days · **Branch:** `phase-3-web`

> ★ **Additive only.** Web renders **inside the main window** — `WebEngineView` is a `QQuickItem`. · §P3.2

---

## Milestone 3.1 — WebEngine Integration · 1–2 d

- [ ] `pip install PySide6-Addons` (supplies QtWebEngine)
- [ ] ★ `QtWebEngineQuick.initialize()` **before** the QML engine is created · §P3.2
- [ ] ★ If the view renders blank: `QQuickWindow.setGraphicsApi(GraphicsApi.OpenGL)` **before** `QGuiApplication` · §P3.2
- [ ] `modes/web/WebStage.qml` — `WebEngineView` filling the Stage
- [ ] ★ **Verify it renders inside the main window** — no second window anywhere
- [ ] ★ Verify QML panels and the address bar composite **over** web content
- [ ] Profile: persistent cookies, cache, and storage paths under `%APPDATA%\Halcyon`
- [ ] User agent set to a current desktop Chrome string
- [ ] Sensible settings: JS on, local storage on, autoplay policy, PDF viewer
- [ ] Fullscreen request handling (a video going fullscreen inside the page)
- [ ] Download handling — save prompt
- [ ] New-window / popup requests handled in-place or blocked, not spawning OS windows
- [ ] Certificate error handling

◻ ★ **Web renders inside the main window** · ◻ Glass shell and panel visible around it · ◻ Pages scroll, links work, text input works · ◻ HTML5 video plays

---

## Milestone 3.2 — Mode Registration · 0.5 d

- [ ] `modes/web/__init__.py` — `ModeSpec` for `"web"`
- [ ] `stage_qml` → `WebStage.qml` (overrides the video stage)
- [ ] `transport_qml` → `AddressBar.qml`
- [ ] `osd_enabled=False`
- [ ] ★ Append one entry to `core/modes.py` — **the only edit to earlier phases**
- [ ] ★ Video engine **stops/releases cleanly** when switching to Web
- [ ] Third chip appears with no `TitleBar.qml` edit

◻ Three chips render · ◻ Switching in any order is stable · ◻ Video engine releases properly

---

## Milestone 3.3 — Address Bar · 1 d

- [ ] `modes/web/AddressBar.qml` — occupies the transport region, **is not a transport bar** · §P3.4
- [ ] Built from the **same `IconButton` vocabulary** as the other modes · §B.1
- [ ] Back · Forward · Reload/Stop · Home
- [ ] URL field: editable, shows current URL, selects all on focus
- [ ] Enter navigates; non-URL input goes to a search engine
- [ ] Loading progress indicator
- [ ] Page title shown in the title bar
- [ ] ★ **No media controls render in Web mode**
- [ ] ★ **No OSD fires in Web mode**
- [ ] ★ Media hotkeys inert in Web mode (`Space` must scroll the page, not toggle playback)

◻ All navigation works · ◻ Search fallback works · ◻ No transport bar, no OSD · ◻ Media hotkeys inert

---

## Milestone 3.4 — Bookmarks · 1 d

- [ ] `modes/web/bookmarks.py` — JSON store in `%APPDATA%\Halcyon`
- [ ] `modes/web/WebPanel.qml` — third and final panel in the one dock slot
- [ ] Toolbar: **Add Bookmark** (captures current URL + title) · **Edit** · **Delete** · §P3.5
- [ ] Rows: favicon · title · URL
- [ ] Click to navigate
- [ ] Drag to reorder
- [ ] Edit dialog: title and URL
- [ ] Delete confirmation
- [ ] Persists across restart
- [ ] Seed with a few sensible defaults
- [ ] *Folders deferred to v1.1* · §8

◻ Add / edit / delete / reorder / navigate all work · ◻ Favicons load · ◻ Persists across restart

---

## Milestone 3.5 — Final Integration & Release · 1–2 d

- [ ] ★ Nuitka packaging **including QtWebEngine** — helper process, resources, locales · §9
- [ ] Verify QtWebEngine works in the frozen build *(a common packaging failure — budget time)*
- [ ] Full `Theme.qml` consistency pass across all three modes · §B.3
- [ ] Settings dialog covers all modes
- [ ] About dialog with version and licence notices
- [ ] Final animation pass
- [ ] Update `README.md`
- [ ] Build installer, tag `v1.0.0`

### ◻ §B.3 — "One machine" review
- ◻ Screenshots of all three modes side by side look like **one product**
- ◻ No control is drawn by a component existing only for one mode *(address bar and PiP excepted)*
- ◻ No mode defines a colour, blur, radius, or duration outside `Theme.qml`
- ◻ Each bar looks **designed for its own contents** — balanced, no gaps, no cramping
- ◻ Switching modes feels like **one app changing channel**, not a different app loading

---

## ◻ PHASE 3 SIGN-OFF · §P3.6

**Regression first**
- ◻ **Phase 1 and Phase 2 sign-off lists both re-run and passing**
- ◻ Deleting `modes/web/` leaves Local + M3U fully working
- ◻ No Phase 1 or Phase 2 file edited except the one `core/modes.py` line
- ◻ `tools/check_isolation.py` passes

**Web**
- ◻ ★ **Renders INSIDE the main window — no second window appears anywhere**
- ◻ Chromium content correct; scroll, links, text input all work
- ◻ Frameless glass shell, title bar, and left panel remain correct around it
- ◻ Address bar: navigate, back, forward, reload, home
- ◻ HTML5 video plays with the page's own controls
- ◻ Bookmarks add / edit / delete / reorder / navigate, persist across restart

**Controls**
- ◻ No transport bar renders in Web mode
- ◻ No OSD fires
- ◻ Media hotkeys inert
- ◻ Switching away from Web returns cleanly

**Final integration**
- ◻ All three chips render; switching in any order is stable
- ◻ Three separate lists — local queue, M3U channels, bookmarks — never cross-contaminate
- ◻ Settings, theme, and window geometry consistent across all modes
- ◻ Clean shutdown from any mode
- ◻ Installer works on a clean Windows machine with no VLC installed

**→ Merge to `main`, tag `v1.0.0`. 🎉**

---

# Deferred — post-v1.0 · §8

Not in any phase above. Recorded so they aren't mistaken for oversights.

- [ ] **Mobile remote + QR** — own phase; must mirror each mode's control set, which only stabilises at v1.0
- [ ] Seek-bar frame thumbnails — needs a second decoder instance
- [ ] Bookmark folders
- [ ] "Play in Halcyon" — pipe a resolved web stream URL into libVLC
- [ ] libVLC 4 GPU path — blocked on upstream release · §0.5
- [ ] Chromecast / DLNA — out of scope

---

# Standing Rules — check at every commit

- [ ] ★ **§4.1** — is this action implemented in exactly one place, and does everything else *bind* to it?
- [ ] ★ **§B.1** — is this built from the shared component vocabulary, not a lookalike?
- [ ] ★ **§B.2** — is this layout designed for its own contents, with no ghost slots?
- [ ] ★ **§A.3** — has any frozen file from an earlier phase been touched?
- [ ] ★ **§9** — are all ctypes callbacks hard-referenced on a long-lived object?
- [ ] ★ Does anything hardcode a value that belongs in `Theme.qml`?
- [ ] `tools/check_isolation.py` passes

---

*Generated from `HALCYON_PLAN.md` v3.1 — 26 July 2026*
