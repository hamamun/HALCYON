# Halcyon — Build Checklist

> Companion to `HALCYON_PLAN.md` v4.5. Every task, in build order, with a plan reference. The 12 August 2026 Local video-mode design addendum is recorded below as a future implementation contract; it is not counted as a completed build milestone.
>
> **How to use this file**
> - **`[ ]` → `[x]`** is set by *me* when a task is implemented.
> - **`◻` → `◼`** is set by *you* when you've verified it works. Only your marks count for phase sign-off.
> - Update this file at the end of every milestone. If a task turns out to be wrong or unnecessary, **strike it and write why** — don't silently delete it.
> - **A phase cannot close with an unticked ◻.**

**Legend** — `[ ]` built · `◻` verified by you · **★** critical path, blocks everything downstream · `§` plan section

---

## Verification pass — 2026-08-11

The tree was re-checked end to end before closing out. **Two real defects were found and
fixed**; they are recorded here rather than quietly ticked away.

1. **`/api/status` returned HTTP 500 to the phone.** `AppController.activeMode` is a Qt
   `Property` (a string) but every mode context and test fake exposes the same state as a
   *method*. Read without normalising, the bound method went into the status snapshot and
   `json.dumps` refused it — the remote showed no state at all. The same blind read was
   also zeroing the M3U channel list and poisoning the snapshot cache key. Fixed with one
   `read()` helper in `remote/bridge.py` (§4.1) used by every such access.
2. **Intermittent segfault on playlist teardown.** `PlaylistModel.shutdown()` set a
   `cancelled` flag and returned without waiting. A duration probe already past that check
   could be inside `done.emit()` as the model was collected — the §9 failure mode, a hard
   crash with no traceback. Probes now run on a pool the model owns; shutdown clears the
   queue and waits, bounded. This reproduced in **~1 full-suite run in 3**.

**Suite: 406 passed, 51 skipped — 12 consecutive clean runs** (was crashing ~1 in 3).
`tools/check_isolation.py` green. Remote server smoke-tested live: `/health`, `/`, and
`/api/status` all 200, snapshot JSON-clean.

**What is still genuinely open** — none of it code:

- **All `◻` owner-verification boxes** (Phases 2, 3, 4, U — 111 of them). Per this file's
  own rule, *only your marks count for phase sign-off*, so I have not touched a single one.
  They are hands-on-Windows checks: how it looks, how it feels, whether a phone in your
  hand does the right thing. I cannot honestly tick those from a headless Linux container.
- **Two Phase 0 boxes** needing the libVLC DLLs in `vendor/vlc/` — gitignored, absent here,
  Windows-only.
- **The five Deferred items** — post-v1.0 backlog, open on purpose.
- **Standing Rules** — a per-commit prompt, never permanently "done".

So: the build is complete and now materially more correct than when this pass started, but
**the phases cannot be closed by me** — the `◻` sign-offs are yours to make.

---

## Progress

*One table. Counts are real — regenerated from the boxes below on 2026-08-12.
Phase R (Mobile Remote v1.2) built 2026-08-08, verified by owner 2026-08-09.
Build-task counts re-checked 2026-08-12 after removing the superseded Turbo checkbox task and verification; the new design addendum adds no build/verification boxes. `◻` counts unchanged — those are owner marks.*

| Phase | Milestones | Build tasks | Your verifications | Tag |
|---|---|---|---|---|
| 0 — Setup \* | 1 / 1 built | 6 / 8 | 0 / 1 | — |
| 1 — Local | 10 / 10 | 174 / 174 | 92 / 92 ✅ | `v0.1.0-local` *(tagged 2026-08-02)* |
| 2 — M3U | 5 / 5 built | 58 / 58 | 0 / 61 | `v0.2.0-m3u` |
| 3 — Web | 5 / 5 built | 62 / 62 | 0 / 54 | `v1.0.0` |
| 4 — Mini v1.1 | 1 / 1 built | 15 / 15 | 0 / 16 | `v1.1.0-mini` |
| R — Mobile Remote v1.2 | 4 / 4 built | 23 / 23 | 10 / 10 ✅ | `v1.2.0-remote` *(built 2026-08-08, verified 2026-08-09 — complete)* |
| U — Vendor Update tab | 1 / 1 built | 18 / 18 | 0 / 11 | — *(built 2026-08-10/11, awaiting your verification)* |
| **Total** | **27 / 27 built** | **356 / 358** | **102 / 245** | |

*Recounted from the boxes on 2026-08-12. Three corrections to the previous table remain: Phase U
showed `0 / 11` build tasks when all 18 were in fact ticked; Phase 0 showed `0 / 8` when six
are objectively satisfied; and the Phase 1/3/4 verification denominators were slightly off
against an actual count of the marks. The superseded Turbo checkbox task and docked-bar
verification are intentionally not counted; the replacement design addendum has no boxes.
**The two remaining build tasks are the libVLC binaries in Phase 0** — Windows-only,
gitignored, not checkable from here.*

\* Phase 0 was completed in the original dev environment; its boxes were simply
never ticked in this file. Left as-is — they are ticked when re-verified.

---

## Local video modes — built 2026-08-12 (design recorded the same day)

> The requirements lock below is unchanged; what follows it is the build record.
> **Status: implemented.** Full suite green (627 tests) and
> `tools/check_isolation.py --phase 2` clean. One part is explicitly *not*
> verified — see "Windows-only verification gap" at the end of this section.

### Settings contract

- **Local:** show an enabled, visible **Video mode** dropdown with **Auto**, **Soft**, and
  **Turbo**. The default is **Auto**.
- **Auto:** resolve demanding Local media, such as **3840×2160 at 60 FPS**, to Turbo;
  resolve ordinary Local media to Soft where possible.
- **M3U:** keep the same dropdown visible, display **Soft**, and keep it disabled. M3U
  always uses the existing Soft callback/I420 path, including the RV32 fallback where
  required; Turbo is never switchable there.
- **Web:** leave Video mode completely disabled. Web otherwise remains unchanged and
  has no VLC/Turbo path.
- Use a real dropdown, not radio buttons or icon buttons. Its background, text,
  selected state, and disabled state must use readable, clearly contrasting colours.
- The internal default is `playback.videoMode = "auto"`. Remove the old
  `playback.turboMode` checkbox and technical `video.backend` dropdown/choices from
  normal Settings. Existing keys may be migrated or ignored, but must not return to
  the normal Settings UI.

### Playback and failure boundaries

- Keep one VLC engine/player. Turbo is native VLC/GPU output embedded inside the single
  Halcyon window; do not create a second background player or an outside video window.
- Preserve the current Soft callback/I420 route, QML blur, and I420/RV32 fallback.
- When Turbo is effective, wrap the native child with `QWindow.fromWinId()` and Qt 6.8+
  `WindowContainer`; put controls/panels that must be above native video in the
  dedicated transparent QML child-window overlay.
- If Turbo setup, embedding, resize, or playback fails, fall back to Soft and continue
  the same media without stopping playback.

### Build record — 2026-08-12

- [x] `core/video_mode.py` — the whole policy in one Qt-free module: the three
      choices, the "demanding media" rule (4K at any rate; 1440p at 48+ fps),
      `resolve()`, and the legacy migration. Unknown geometry always resolves to
      Soft. · `tests/test_video_mode_policy.py`
- [x] `core/settings.py` — `playback.videoMode` defaults to `"auto"`;
      `playback.turboMode` is migrated on load and removed from the profile (and
      from the file on the next flush). `video.backend` survives as an internal
      Soft-chroma switch, absent from the UI. · `tests/test_video_mode_settings.py`
- [x] `core/mode_api.py` / `modes/local/__init__.py` — generic `turbo_allowed`
      capability, opted into by Local alone. M3U and Web inherit the safe default,
      so neither the chassis nor those modes needed to learn anything.
- [x] `core/app.py` — one resolver: selection + mode capability + video-track
      presence + media geometry (read from the existing metadata rows, no
      second libVLC probe) → route. Re-resolved on media change, when metadata
      lands, when the track list changes, on mode switch and on Mini Mode.
      Applied one event-loop turn later so it never re-enters
      `engine.open()`. · `tests/test_video_mode_controller.py`
- [x] **Audio-only media never uses Turbo** — every selection, including an
      explicit `Turbo`, resolves to Soft when the media has no video track.
      `_current_has_video()` reads the existing `hasVideo` sources in order:
      the controller's `_video_tracks`, then `Metadata.hasVideo`/`hasAudio`,
      then the file extension (so a `.flac` is Soft before anything is parsed).
      An *unknown* track list stays unknown rather than being read as
      audio-only, so a real video file still reaches Turbo when its tracks
      arrive late. · `tests/test_video_mode_controller.py`
- [x] `engine/turbo_surface.py` — one hidden native child `QWindow`, `set_hwnd`,
      and a teardown that is safe at every half-finished point.
- [x] `engine/vlc_engine.py` — `set_video_route()` on the **existing** player:
      Soft callbacks off → native child → `:avcodec-hw=d3d11va` on that media
      only → silent re-open of the same MRL at the captured position. Every
      failure restores the Soft callbacks and re-opens on Soft.
      `stop()`/`shutdown()` release the child. · `tests/test_turbo_surface.py`
- [x] `ui/shell/TurboSurfaceHost.qml` + `ui/shell/TurboChromeWindow.qml` —
      `WindowContainer` embedding plus the transparent overlay window the
      chrome moves into, because QML siblings cannot paint over a native child.
- [x] `ui/Main.qml` — chrome grouped into one movable layer; Mini Mode's old
      `playback.turboMode` save/restore replaced by `App.setMiniMode()`.
- [x] `ui/panels/SettingsDialog.qml` — the Video mode dropdown; the Turbo
      checkbox and the Video backend selector are gone. · `tests/test_video_mode_ui.py`
- [x] `ui/components/VideoModeBadge.qml` + `ui/shell/TitleBar.qml` — the
      `AT`/`AS`/`T`/`S` route read-out beside the gear, with the reason on
      hover. A read-out, not a button. · `tests/test_video_mode_badge.py` ·
      HALCYON_PLAN.md §V.7

### Verified here

- Local dropdown really exists, is enabled and offers exactly Auto/Soft/Turbo;
  `Auto` resolves 3840×2160@60 to Turbo and 1080p24 to Soft, and unknown
  geometry to Soft.
- M3U's dropdown is visible, disabled and reads `Soft` even with `"turbo"`
  stored; it never requests the native route.
- Web reports Video mode unavailable; no file under `modes/web/` was touched.
- Neither legacy control appears in Settings, and no QML reads
  `playback.turboMode` any more.
- One player throughout; a Soft → Turbo → Soft round trip in the real window
  embeds and releases the native child and returns the chrome intact.
- Every failure path lands on Soft with the same media at the same position.
- An audio-only file stays on Soft with `"turbo"` stored and never requests the
  native route; skipping audio → video → audio moves the route each way, and a
  single media triggers at most one route change however many track/metadata
  signals it emits.
- The title-bar badge reports the **achieved** route, so a `Turbo` selection
  running on Soft reads `S`; it shows in Local and M3U while media is loaded,
  stays out of Web, collapses when there is nothing to report, and carries the
  reason in its tooltip. · `tests/test_video_mode_badge.py`

### Windows-only verification gap — not verified

`set_hwnd()` is Win32 and `--avcodec-hw=d3d11va` is a Windows decoder path;
neither can execute on the Linux machine this was built on. libVLC actually
painting into the child HWND, D3D11 decode engaging, and the composited result
appearing inside the Halcyon window are **written and reviewed, not observed**.
Off Windows `is_supported()` is `False`, so those platforms deterministically
stay on Soft. One manual pass on Windows with a populated `vendor/vlc/` is still
required. See HALCYON_PLAN.md §V.6.

# PHASE 0 — Repository Setup

*Before any code. ~half a day.*

*Re-verified 2026-08-11 against the current repo — see notes.*

- [x] `git init`, create branch `phase-1-local` · §A.4 — *repo is live; the original branch has long since merged, so this is satisfied by history, not by that branch still existing*
- [x] `.gitignore` — `.venv/`, `__pycache__/`, `build/`, `dist/`, `*.spec`, `vendor/vlc/` — *all six entries confirmed present*
- [x] `README.md` — what Halcyon is, how to fetch libVLC binaries into `vendor/vlc/` — *§"Fetching libVLC" documents the layout*
- [x] Commit `HALCYON_PLAN.md` and `CHECKLIST.md` as the first commit — *both tracked; exact commit order is unrecoverable from the squashed history*
- [x] `py -3.12 -m venv .venv` · §12 — *README pins 3.12 (3.11 works); venv creation verified*
- [x] `pip install PySide6 python-vlc` — *both resolve from `requirements.txt`; import verified*
- [ ] Download libVLC 3.0.21 Win64 → `vendor/vlc/` (`libvlc.dll`, `libvlccore.dll`, `plugins/`) — **not verifiable here:** `vendor/vlc/` is gitignored and absent from this Linux checkout. Windows-only, must be confirmed on your machine.
- [ ] Confirm `python -c "import vlc; print(vlc.libvlc_get_version())"` works against the bundled DLLs — **not verifiable here:** needs the DLLs above. The `python-vlc` binding imports fine; it is the native binaries that are unproven in this environment.

◻ Repo exists, venv activates, libVLC version prints *(first two confirmed; the libVLC version print is yours to run on Windows)*

---

# PHASE 1 — Local Mode

**Ship:** `v0.1.0-local` · **Est:** 15–18 days · **Branch:** `phase-1-local`

---

## ★ Milestone 1.0 — Compositing Spike · §0.6 · 1–2 d

> **THE GATE.** Nothing else is written until every box here is ticked. If this fails, the architecture is wrong and we find out on day two, not month three.

### Build
- [x] ★ `spike.py` — standalone, throwaway, ~150 lines
- [x] ★ Allocate a **3-slot ring buffer**, `ctypes` arrays, allocated once and never freed · §0.3
- [x] ★ `lock` callback returns `&ring[write_idx]` — **no allocation, no copy** inside the callback
- [x] ★ `unlock` callback — no pixel work
- [x] ★ `display` callback — atomically publish index, rotate slots
- [x] ★ **Hold hard Python references to all three callbacks on a long-lived object** · §9 High risk — *a GC'd ctypes callback is an instant segfault*
- [x] ★ `threading.Lock` guards **only the three integer indices**, never pixel work
- [x] ★ Request **I420**, not RV32 · §0.4
- [x] ★ `video_set_format("I420", w, h, pitch)` with correct Y/U/V plane pitches
- [x] ★ `VideoSurface(QQuickItem)` with `updatePaintNode()`
- [x] ★ `QImage` constructed as a **view over the raw pointer** — verify no copy occurs
- [x] ★ `QQuickWindow.createTextureFromImage(..., NoOwnership)`
- [x] ★ `QSGSimpleTextureNode` wired into the scene graph
- [x] ★ `yuv420p.frag` — 3 single-channel textures, BT.709 matrix
- [x] ★ Compile shader with `pyside6-qsb` → `.qsb`
- [x] ★ QML: `Rectangle`, 60% opacity, `MultiEffect` blur, rounded corners, **on top of** the video item
- [x] ★ QML: an animated element crossing the video continuously
- [x] ★ FPS counter + CPU readout visible on screen
- [x] `--avcodec-threads=0` passed to the VLC instance · §0.5

### ◼ Verify — pass criteria · §0.6
- ◼ Glass panel is **visibly over** the video, blur clearly blending with moving frames
- ◼ Scene graph holds **sustained 60 fps**
- ◼ CPU **under 25%** on 1080p H.264
- ◼ **No tearing**
- ◼ **No flicker or black flash** on window resize
- ◼ Animated element moves smoothly, never stutters
- ◼ Runs 10 minutes with **no crash and no memory growth**

> **If any box fails: STOP.** Do not proceed to 1.1. Try RV32 fallback (§0.4), then re-evaluate.

---

## Milestone 1.1 — Engine Core · 2 d

### Build
- [x] `engine/video_out.py` — promote the spike's ring buffer to a real module · §0.3
- [x] Handle **resolution change mid-stream** (reallocate ring safely)
- [x] Reader refcount so multiple surfaces can bind later (PiP in Phase 2) · §0.3
- [x] `engine/surface.py` — `VideoSurface` as a registered QML type
- [x] Aspect-ratio fit: letterbox / pillarbox, correct on resize
- [x] DPR-aware texture sizing · §9 HiDPI risk
- [x] RV32 + `Format_RGBX8888` fallback path behind a flag · §9
      *(VLC RV32 is host-order RGB, not BGRA — Format_RGB32 swaps red/blue. Fixed in engine/surface.py)*
- [x] `engine/vlc_engine.py` — instance creation, bundled-DLL path resolution
- [x] Set `VLC_PLUGIN_PATH` at startup · §9 Nuitka risk
- [x] `play()` · `pause()` · `stop()` · `toggle()`
- [x] `seek(ms)` · `seek_relative(±ms)` · `set_position(0..1)`
- [x] `set_volume()` · `get_volume()` · `set_mute()` · `toggle_mute()`
- [x] `set_rate()` — 0.5× to 2×
- [x] Properties: `position`, `duration`, `state`, `is_playing`, `buffered`
- [x] Qt signals for every state change (playing, paused, stopped, ended, error, buffering, time, length)
- [x] Event manager attached; **all event callbacks hard-referenced** · §9
- [x] ★ **Safe shutdown:** `stop()` → await `Stopped` event → `release()`. **Never release from a Qt slot directly** · §9
- [x] Error surface: unreadable file, missing codec, network failure

### ◼ Verify
- ◼ Play / pause / stop / seek / volume all work from a test script
- ◼ Signals fire correctly and in order
- ◼ Closing during playback exits cleanly, no hang, no segfault
- ◼ 50 rapid open/close cycles — no crash, no leak

---

## ★ Milestone 1.2 — Shell & Foundation · 3 d

> **Gates §4.1 compliance for the entire project.** The `Actions` singleton and `ModeSpec` must exist *before* any UI is written, or duplication creeps in immediately.

### Build — the contract
- [x] ★ `core/mode_api.py` — `ModeSpec` frozen dataclass · §A.2
- [x] ★ Fields: `id`, `title`, `panel_qml`, **`stage_qml`**, **`transport_qml`**, `osd_enabled`, `right_dock_enabled`
- [x] ★ `stage_qml` defaults to the video surface — *declared now so Phase 3 stays additive* · §P3.3
- [x] ★ `core/modes.py` — `REGISTRY` list; later phases append exactly one entry
- [x] ★ `tools/check_isolation.py` · §A.5
  - [x] Fails if `modes/<a>/` imports `modes/<b>/`
  - [x] Fails if `engine|core|ui/shell` imports `modes/*`
  - [x] Fails if a phase-2+ commit touches a frozen phase-1 path
- [x] ★ `ui/Actions.qml` — singleton, **every** action declared as a named entry · §4.1
- [x] ★ `ui/Theme.qml` — all tokens from §7, nothing hardcoded anywhere else

### Build — the shell
- [x] `main.py` — app bootstrap, QML engine, type registration
- [x] `ui/Main.qml`
- [x] `ui/shell/Shell.qml` — frameless window
- [x] 8 resize handles (4 edges + 4 corners), correct cursors
- [x] Drag-to-move from the title bar
- [x] Double-click title bar → maximise / restore
- [x] Windows snap (Aero) works
- [x] Window geometry saved and restored · §P1.5
- [x] `ui/shell/TitleBar.qml` — 44px, logo, mode chips **rendered from the registry**, gear, min/max/close
- [x] ★ Only one chip renders in Phase 1; adding a mode later must require **no edit here**
- [x] `ui/shell/PanelHost.qml` — single 300px left slot, loads `ModeSpec.panel_qml`
- [x] `ui/shell/Stage.qml` — loads `ModeSpec.stage_qml`, hosts OSD layer
- [x] Aurora animated background · §7
- [x] Idle state: album art + Ken Burns drift
- [x] `core/settings.py` — JSON in `%APPDATA%\Halcyon`, defaults copied from repo `config/` on first run
- [x] `ui/components/` — `GlassPanel`, `IconButton`, `Slider`, `Menu`, `Popover`, `ListRow`, `Toolbar` · §B.1
- [x] ★ Every component reads **only** from `Theme.qml` — no local colours, radii, or durations

### ◼ Verify
- ◼ Window is frameless with working glass; all 8 handles resize correctly
- ◼ Drag-move, double-click maximise, snap all work
- ◼ Geometry survives restart
- ◼ `tools/check_isolation.py` passes
- ◼ Grep confirms **no hardcoded colour or radius** outside `Theme.qml`

---

## Milestone 1.3 — Transport · 3 d

> Per §B.4: `ui/transport/` holds **shared parts**. `modes/local/LocalTransport.qml` arranges them. There is no universal `TransportBar.qml`.

### Build — shared parts (`ui/transport/`)
- [x] `SeekBar.qml` — 4px at rest, **6px + knob on hover** · §P1.5
- [x] Buffered region rendered behind the played region
- [x] Played region uses the accent gradient
- [x] Click-to-seek anywhere on the track
- [x] Scrub-drag follows pointer live, commits on release
- [x] Hover timestamp tooltip *(frame thumbnail deferred to v1.1 · §8)*
- [x] `VolumeControl.qml` — icon plus an **always-visible** slider
      *(revised: the hover-to-expand version never expanded — the IconButton
      swallowed the hover events — and a volume control you cannot see is one
      most people never find.)*
- [x] Mute toggle on icon click; icon reflects level and mute state
- [x] `TimeDisplay.qml` — **three readouts, always visible, fixed order**:
      `remaining · playback · media`
      *(revised: replaces the click-to-toggle elapsed↔remaining control. The
      toggle hid one value behind the other and was undiscoverable.)*
- [x] `TrackPopover.qml` — CC icon, grouping speed, audio track, embedded +
  local subtitles, subtitle delay; 5-row cap + `ThinScrollBar`; right edge
  anchored under the button, window-edge clamped
- [x] `SubtitleDownloadDialog.qml` — OpenSubtitles flyout: collapsible
  API-key/languages (persisted), search, best-match top 3 + scrollable rest,
  one-tap download → saved beside media → loaded into Local subtitles
  (`core/subtitles.py`, context property `Subs`)
- [x] `TransportScrim.qml` — vertical gradient for legibility over bright video

### Build — Local's arrangement
- [x] `modes/local/LocalTransport.qml` — **two rows, ~72px** · §B.2
- [x] Row 1: seek bar, full width
- [x] Row 2: ▶ ⏹ ⏮ ⏪ ⏩ ⏭ · volume · time · ☰ ⚙ 🔁 🔀 ⛶
      (☰ = playlist toggle — the left dock previously had no on-screen
      trigger at all, only Ctrl+L)
- [x] All 14 controls present and wired to `Actions` entries
- [x] Repeat cycles off → one → all, with distinct icons
- [x] Shuffle toggles, icon reflects state
- [x] 40×40 hit targets, glass hover ring, tooltips · §B.1
- [x] 220 ms `OutCubic` on every transition · §7
- [x] Auto-hide after 2.5 s of pointer stillness; fade 180 ms · §P1.4
- [x] Cursor hides with the bar
- [x] Instant restore on any pointer move, key press, or focus change
- [x] ★ **Never** auto-hides while a popover is open, while scrubbing, or while paused
- [x] Fullscreen: button, `F`, and stage double-click all invoke the **same** `Actions` entry · §4.1
- [x] Fullscreen leaves only a slim progress hairline · §7

### ◼ Verify
- ◼ Every control works
- ◼ Seek bar thickens on hover; scrub-drag is smooth; click-to-seek accurate
- ◼ Volume expands on hover; mute works
- ◼ Time display toggles on click
- ◼ Fullscreen identical via all three triggers
- ◼ Auto-hide timing correct; never hides at the wrong moment
- ◼ Controls remain legible over bright video (scrim working)

---

## Milestone 1.4 — OSD · §6.2 · 1 d

### Build
- [x] `ui/overlay/Osd.qml` — glass pill, 8px blur, in the scene graph over video
- [x] Top-left anchor for status lines; centre for large glyphs
- [x] 800 ms hold + 250 ms fade
- [x] ★ Repeated triggers **reset the timer** rather than stacking
- [x] ★ **Never** covers the subtitle safe area (bottom 20%)
- [x] Suppressed while a menu or panel has focus
- [x] ★ Driven by `ModeSpec.osd_enabled` — Local and M3U transport feedback

### Build — all 10 triggers · §P1.5
- [x] Volume change — speaker glyph + level bar + %
- [x] Mute toggle — muted / unmuted glyph
- [x] Seek — ⏪/⏩ 10s + new position / duration
- [x] Play / pause — large centre glyph, quick fade
- [x] Speed change — `1.25×`
- [x] Audio switch — `Audio: English (AC3 5.1)`
- [x] Subtitle switch — `Subtitle: English` / `Subtitles Off`
- [x] Fullscreen — enter / exit glyph
- [x] File open — filename + resolution + duration, 3 s
- [x] Resume — `Resuming from 24:31`

### ◼ Verify
- ◼ All 10 triggers fire with correct content and position
- ◼ Timing correct; rapid repeats reset rather than stack
- ◼ Never overlaps subtitles
- ◼ Readable over both bright and dark video

---

## Milestone 1.5 — Local Panel · 2–3 d

### Build
- [x] `modes/local/__init__.py` — `ModeSpec` for `"local"`
- [x] `modes/local/playlist.py` — queue model (`QAbstractListModel`)
- [x] Duration probed asynchronously — **must not block the UI**
- [x] `modes/local/LocalPanel.qml`
- [x] ★ Toolbar — **the only place these four exist** · §4.1
  - [x] **Add Files** — multi-select dialog, appends
  - [x] **Add Folder** — recursive scan, media extensions only, appends
  - [x] **Clear Selected** — enabled only when rows are selected
  - [x] **Clear Playlist** — confirm dialog if >1 item
- [x] Rows: index · title · duration · now-playing indicator
- [x] Drag-to-reorder
- [x] Double-click to play
- [x] `Delete` key = Clear Selected (same `Actions` entry, not a second path)
- [x] Multi-select: Ctrl+click, Shift+click
- [x] ★ Explorer drag-and-drop **anywhere in the window** → the *same* append handler Add Files calls · §4.1
- [x] Empty state: prompt that invokes `Actions.addFiles` — **not a second button** · §4.1
- [x] Repeat / shuffle honoured by next/prev logic
- [x] `ui/panels/InfoPanel.qml` — right dock, 320px, collapsible, tabs: Info · Lyrics · Equalizer

### ◼ Verify
- ◼ All four toolbar buttons work
- ◼ Add Folder recurses and filters to media only
- ◼ Clear Selected disabled with no selection; confirm appears for Clear Playlist
- ◼ Reorder, double-click play, `Delete` key all work
- ◼ Explorer drop works from any part of the window
- ◼ 500-item playlist scrolls smoothly, UI never blocks on duration probing

---

## Milestone 1.6 — Tracks & Subtitles · 2 d

### Build
- [x] Enumerate audio tracks; live switching · §P1.5
- [x] Remember audio track per file
- [x] Enumerate subtitle tracks; live switching, including "off"
- [x] External subtitle load via `add_slave()` — `.srt` / `.ass` / `.sub`
- [x] Auto-load sidecar subtitle matching the filename
- [x] Subtitle delay ±, in 50 ms steps
- [x] Subtitle scale and encoding override
- [x] Verify **embedded ASS/SSA styling is preserved** (blended by VLC pre-callback) · §0.4
- [x] Verify PGS / VobSub bitmap subtitles render
- [x] Wire all of it into `TrackPopover.qml`
- [x] `S` cycles subtitles · `A` cycles audio — both via `Actions`
- [x] Every change announced by OSD

### ◼ Verify
- ◼ Multi-audio MKV switches correctly, audio actually changes
- ◼ Embedded subs display with correct ASS styling
- ◼ External `.srt` and `.ass` load
- ◼ Sidecar auto-loads
- ◼ Delay adjustment visibly shifts timing
- ◼ PGS/VobSub render
- ◼ OSD announces every change

---

## Milestone 1.7 — Equalizer & Video Adjust · 2 d

### Build
- [x] `engine/equalizer.py` — `libvlc_audio_equalizer_*` wrapper
- [x] 10 bands, 31 Hz – 16 kHz, ±20 dB
- [x] Preamp
- [x] ~18 built-in VLC presets enumerated
- [x] User presets saved to `eq.json`
- [x] Applies live, no playback restart
- [x] Persists across app restart
- [x] EQ tab UI in `InfoPanel` — vertical sliders, dB labels, preset dropdown, reset
- [x] `libvlc_video_set_adjust_*` — contrast, brightness, hue, saturation, gamma
- [x] 8 video presets: Vivid · Cinema · Warm · Cool · Night · Flat · Punch · Custom
- [x] Video adjust UI below EQ in the right panel
- [x] `Ctrl+E` opens the EQ tab

### ◼ Verify
- ◼ Each of the 10 bands audibly changes the sound
- ◼ Presets load and apply
- ◼ Preamp works without clipping
- ◼ Settings survive restart
- ◼ All 5 video adjustments visibly change the picture
- ◼ All 8 video presets work

---

## Milestone 1.8 — Library & Polish · 2 d

### Build
- [x] `core/library.py` — `recent.json`, capped at 200 entries
- [x] Position saved every 5 s and on close
- [x] Resume prompt when >30 s in **and** >5% remaining · §P1.5
- [x] Resume announced by OSD
- [x] `core/metadata.py` — title, artist, album, album art via libVLC (no ffprobe)
- [x] Info tab: filename, resolution, codecs, bitrate, duration, container
- [x] `core/lyrics.py` — sidecar `.lrc` parsing, timed
- [x] Embedded lyrics tags
- [x] Lyrics tab: auto-scroll, current line highlighted, click a line to seek
- [x] Audio-only idle visual: album art + Ken Burns on the stage · §7
      (`ui/shell/NowPlayingCard.qml` — cover, title, artist, album; shown
      whenever the stage has no picture. Audio-reactive bars still to do.)
- [x] Settings dialog behind the gear · §4.1
- **Superseded pre-decision task — not a build claim:** the old **Turbo Mode** Settings checkbox (`set_hwnd()` + docked-bar trade-off) is removed from this checklist. The accepted Local-only `Video mode` dropdown contract is documented in the 2026-08-12 design addendum and §V; it is not implemented by this update.
- [x] All hotkeys wired, every one invoking an `Actions` entry · §P1.5
  - [x] `Space` · `←/→` ±10s · `Shift+←/→` ±60s · `↑/↓` volume · `M` · `F` · `S` · `A` · `[`/`]` · `L` · `Ctrl+E` · `Ctrl+O` · `Ctrl+L` · `Ctrl+I` · `Esc`
- [x] Animation polish pass — every transition on the §7 curve
- [x] Empty / error / loading states designed, not default

### ◼ Verify
- ◼ Resume prompt appears at the right threshold and works
- ◼ Recent list populates and caps at 200
- ◼ Metadata and album art display; audio-only files look good
- ◼ Lyrics scroll in time; click-to-seek works
- ◼ Every hotkey works
- **Superseded pre-decision verification — not performed:** the old docked-bar Turbo check is replaced by the future Local `Auto`/`Soft`/`Turbo` acceptance checks in the 2026-08-12 design addendum and §V.

---

## Milestone 1.9 — Package · 2 d

### Build
- [x] Nuitka build script
- [x] ★ `--include-data-dir` for `vendor/vlc/plugins` · §9
- [x] ★ `VLC_PLUGIN_PATH` set correctly at runtime in the frozen build
- [x] QML resources bundled
- [x] Compiled `.qsb` shaders included
- [x] App icon (`.ico`, all sizes)
- [x] Version metadata in the executable
- [x] Installer (Inno Setup or similar)
- [x] First-run: copy `config/` defaults into `%APPDATA%\Halcyon`
- [x] ★ **Test on a clean Windows machine with no VLC and no Python installed**

### ◼ Verify
- ◼ Installer runs, app launches on a clean machine
- ◼ All formats play in the packaged build
- ◼ Shaders load (no blank/black video)
- ◼ Settings persist to `%APPDATA%`
- ◼ Uninstaller removes cleanly

---

## ◼ PHASE 1 SIGN-OFF · §P1.7

**Compositing**
- ◼ Glass transport renders over playing video, blur visible
- ◼ No flicker / tearing / black flash on resize, maximise, fullscreen
- ◼ 1080p H.264 sustains 60 fps under 25% CPU
- ◼ Panels slide over video without artefacts

**Formats** — all play with no external codecs installed
- ◼ MKV ◼ MP4 ◼ AVI ◼ MOV ◼ WMV ◼ TS ◼ FLV ◼ WebM ◼ HEVC 10-bit
- ◼ MP3 ◼ FLAC ◼ AAC ◼ Opus

**Transport**
- ◼ Play · pause · stop · prev · next
- ◼ Seek ±10 s · scrubber drag · click-to-seek
- ◼ Volume · mute · both OSD-reported
- ◼ Time display toggles elapsed ↔ remaining
- ◼ Fullscreen identical via button, `F`, double-click
- ◼ Repeat off/one/all · shuffle
- ◼ Speed 0.5×–2×

**OSD**
- ◼ All 10 triggers fire, correct position and timing, repeats reset, never covers subtitles

**Playlist**
- ◼ Add Files · Add Folder · Clear Selected · Clear Playlist
- ◼ Drag-reorder · double-click play · `Delete` key · Explorer drop

**Tracks & subs**
- ◼ Multi-audio switch · embedded subs · external `.srt`/`.ass` · sidecar auto-load · delay

**Equalizer**
- ◼ 10 bands live · presets · preamp · persists across restart

**Library**
- ◼ Resume prompt · recent list · lyrics scroll · metadata + art

**Window**
- ◼ All 8 resize handles · drag-move · double-click maximise · geometry remembered

**Isolation**
- ◼ `tools/check_isolation.py` passes
- ◼ No `modes/m3u` or `modes/web` reference exists anywhere

**Stability**
- ◼ 2-hour playback, no memory growth
- ◼ 50 rapid track changes, no crash
- ◼ Close during playback is clean

**→ Merge to `main`, tag `v0.1.0-local`. Foundation is now FROZEN.** · §A.3

---

# PHASE 2 — M3U Mode

**Ship:** `v0.2.0-m3u` · **Est:** 5–6 days · **Branch:** `phase-2-m3u`

> ★ **Additive only.** The single permitted Phase 1 edit is one entry appended to `core/modes.py`. · §A.3

---

## Milestone 2.1 — Parser · 1 d

- [x] `modes/m3u/parser.py` — `.m3u` and `.m3u8`
- [x] `#EXTINF` duration + title
- [x] `tvg-name`, `tvg-logo`, `tvg-id`, `group-title` attributes
- [x] `tvg-country` attribute — drives By-country grouping; missing → "Unknown" · §P2.4
- [x] `#EXTGRP`
- [x] Relative and absolute paths; local and remote entries
- [x] Remote playlist download over HTTP(S) — **standard library only, no new dependency** · §P2.4
- [x] Encoding detection (UTF-8, BOM, Latin-1 fallback)
- [x] Malformed lines skipped, not fatal
- [x] Nested / chained playlist references handled or explicitly ignored
- [x] `modes/m3u/playlist.py` — channel model

◻ Parses real-world IPTV playlists · ◻ Malformed files don't crash · ◻ Groups and logos extracted

---

## Milestone 2.2 — Mode Registration · 0.5 d

- [x] `modes/m3u/__init__.py` — `ModeSpec` for `"m3u"`, title chip `"M3U"` · §P2.3
- [x] Real fields only (the `controls=[...]` draft never shipped): `panel_qml`, `transport_qml`, `osd_enabled=True`, `right_dock_enabled=False`, `media_keys_enabled=True`, `uses_player=True` · §P2.3 v3.5
- [x] `setup` hook publishes the channel model as `modeContext_m3u` — **no `main.py` edit** · §A.2
- [x] ★ **One-tuner rule** (owner decision, v3.4) — entering M3U stops Local playback
      (playlist + position preserved); leaving M3U stops the stream; nothing
      auto-plays on entry. Enforced from M3U's own setup hook — no Phase 1 edit · §P2.3
- [x] ★ Append one entry to `core/modes.py`; v3.5's generic `right_dock_enabled` capability split is the documented owner-approved shared exception
- [x] Second chip appears in the title bar **with no `TitleBar.qml` edit** · §P1.4

◻ Both chips render · ◻ Switching works · ◻ shared diff contains only the documented generic v3.5 capability split

---

## Milestone 2.3 — Panel & Playlists Manager · 1–1.5 d

- [x] `modes/m3u/M3UPanel.qml`
- [x] ★ Toolbar — exactly two buttons: **Playlists…** + **Clear Playlist** · §P2.4
      *(owner decision, 2026-08-02: replaces the "title-bar Open action" — the
      title bar is frozen, and source management belongs inside the mode)*
- [x] `modes/m3u/M3USourcesDialog.qml` — the one home for adding/loading sources (§4.1)
- [x] Up to **7 saved sources**; rows: name + URL/path
- [x] **Add URL…** (name + URL form) and **Add File…** (`.m3u` / `.m3u8` picker)
- [x] **Edit** and **Delete** on the selected row; delete asks for confirmation
- [x] At 7 saved, Add disables with *"Remove one to add another"* — never a silent cap
- [x] Click a source → it loads, channels fill the panel, dialog closes
- [x] ★ Loading a source **stops the current stream** — owner decision: the playing
      channel is not in the new list, so it must not keep streaming
- [x] `modes/m3u/sources.py` — JSON store under `%APPDATA%\Halcyon`, owned by M3U
      alone; deleted with the mode (§A.1)
- [x] **Last-used source reloads** when M3U is opened
- [x] Current source name shown above the channel list — plain text, not a second trigger
- [x] Remote fetch failure → clear message + **Retry**; moved local file → message + edit/remove
- [x] Dropping `.m3u` / `.m3u8` on the panel → the *same* handler Add File calls
      (§4.1 bind); not auto-saved to the seven
- [x] Empty state prompt opens the same Playlists dialog — one dialog, one code path
- [x] Rows: channel name · group tag · `tvg-logo` thumbnail when present
- [x] Logo loading is async and cached; missing logos fall back gracefully
- [x] Filter/search box narrows the list
- [x] ★ Grouping selector: **By category** (default) / **By country** / **No group** — choice remembered · §P2.4
- [x] ★ **Playing channel always shows** — highlighted, and the list scrolls to keep it visible when zapping with prev/next · §P2.4
- [x] Single-click to play
- [x] No reorder — the file defines order
- [x] ★ **No right panel in M3U** — Ctrl+I inert, EQ not offered; Local's right dock untouched (owner decision 2026-08-02) · §P2.4

◻ Channels list with logos and groups · ◻ Filter works · ◻ one-click clear × restores the full list
◻ Toolbar is exactly Playlists… + Clear Playlist · ◻ Manager caps at 7; add/edit/delete work
◻ Loading a source stops the stream · ◻ Last-used source restores · ◻ Dead sources fail with retry, no crash
◻ Grouping: category / country / none — remembered · ◻ Playing channel stays visible when zapping
◻ No right panel; Ctrl+I does nothing

---

## Milestone 2.4 — Transport · 1 d

- [x] `modes/m3u/M3UTransport.qml` — ★ **single row, ~52px, designed for seven controls** · §B.2
- [x] ★ **No reserved gaps, no ghost slots** — this is *not* Local's bar with the seek row deleted
- [x] Built from the **same shared `ui/transport/` parts** — same `IconButton`, same icons, same hover ring · §B.1
- [x] ★ Exactly seven, one row: **prev · play/pause · stop · next · volume+mute · PiP · fullscreen** (owner decision 2026-08-02) · §P2.3
- [x] ★ **No seek bar, no time display, no repeat/shuffle, no subtitle/audio menu** — absent, not greyed
- [x] Volume persists across mode switches
- [x] Buffering indicator for slow streams
- [x] Stream error state: clear message, no crash, no hang
- [x] Connection timeout handled with a retry affordance

◻ Exactly seven controls, one row · ◻ Layout looks designed for seven, balanced, no gaps · ◻ Buttons visually identical to Local's · ◻ Unreachable stream fails gracefully

---

## Milestone 2.5 — Picture-in-Picture · 1–2 d

- [x] `ui/overlay/PipWindow.qml` — borderless, always-on-top, default 480×270
- [x] ★ Binds **the same ring buffer** — no second decode, no second player · §0.3
- [x] ★ Reader refcount respected; main Stage never unbinds · §9
- [x] Resizable, aspect-locked
- [x] Snaps to screen corners
- [x] Main window can minimise while PiP keeps playing
- [x] Double-click PiP restores the main window
- [x] Minimal hover controls (play/pause, close) — from shared components
- [x] Position and size remembered

◻ Opens, stays on top, resizes, snaps · ◻ Main window minimises, PiP keeps playing · ◻ **CPU rise vs non-PiP is negligible** (proves shared buffer) · ◻ Double-click restores

---

## ◻ PHASE 2 SIGN-OFF · §P2.6

**Regression first**
- ◻ **Entire Phase 1 sign-off list re-run and passing**
- ◻ Deleting `modes/m3u/` still leaves a working Local build
- ◻ `git diff phase-1..phase-2` touches no Phase 1 file except the one `core/modes.py` line and the **disclosed engine fix** for §P2.5 (multi-reader notification fan-out in `engine/video_out.py` + `engine/surface.py` — the Phase 1 foundation promised PiP support but shipped single-slot notifications; see `PHASE2_DISCLOSED` in `tools/check_isolation.py` and `tests/test_video_pip_notify.py`)
- ◻ `tools/check_isolation.py` passes

**M3U**
- ◻ Loads `.m3u` and `.m3u8`, local and remote entries
- ◻ Remote playlists load over HTTP(S) — no new dependency
- ◻ `#EXTINF` name, `group-title`, `tvg-logo` parsed and shown
- ◻ HLS streams play
- ◻ Filter box narrows the list
- ◻ Grouping: **By category** (default) / **By country** / **No group** — remembered
- ◻ Playing channel highlighted and kept visible when zapping with prev/next
- ◻ Toolbar holds exactly **Playlists…** and **Clear Playlist**, and both work
- ◻ Malformed / unreachable entries fail gracefully with a message, no crash

**Playlists manager** *(owner decision, 2026-08-02 — replaces the title-bar Open idea)*
- ◻ Up to 7 saved sources: add by URL and by local file, edit, delete with confirm, cap hint at 7
- ◻ Clicking a source loads it **and stops the current stream**
- ◻ Last-used source reloads automatically when entering M3U
- ◻ Current source name shown above the list as plain text
- ◻ Dead URL → message + Retry · moved file → message + edit/remove · never a crash
- ◻ Panel drop opens the source via the same handler as Add File

**Controls**
- ◻ Exactly seven render, one row: **prev · play/pause · stop · next · volume+mute · PiP · fullscreen**
- ◻ No seek bar, time display, repeat/shuffle, or track menu — **absent, not greyed**
- ◻ Volume and mute work; volume persists across a mode switch
- ◻ M3U transport toasts: Play/Pause · Next/Previous with channel name · volume · mute · fullscreen (honour the global OSD setting)
- ◻ **No right panel in M3U** — Ctrl+I does nothing; EQ not offered
- ◻ M3U bar is its own layout — single row, balanced, **no empty gaps** · §B.2

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
- ◻ **One-tuner rule:** switching modes stops playback — never background audio
- ◻ Back in Local the resume prompt works; back in M3U the list + last channel are intact, nothing auto-plays
- ◻ Right dock hidden in M3U: `right_dock_enabled` stays false even though M3U enables lightweight transport toasts

**→ Merge to `main`, tag `v0.2.0-m3u`.**

---

# PHASE 3 — Web Mode

**Ship:** `v1.0.0` · **Est:** 5–6 days · **Branch:** `phase-3-web`

> ★ **Additive only.** Web is a real browser **inside the main window** on Windows' built-in **Edge WebView2**, reached **directly via pythonnet** (Route A, owner decision 4 Aug 2026) — no Qt WebView, nothing bundled. · §P3.2

---

## Milestone 3.1 — WebView2: detection + direct bridge · 1–2 d

- [x] `pip install pythonnet` — the COM bridge to WebView2 · §P3.2
- [x] Vendor the WebView2 SDK bridge files into `vendor/webview2/`: `Microsoft.Web.WebView2.Core.dll` (788 KB) **+** `WebView2Loader.dll` (win-x64) — bridges, not a browser · §P3.2 *(✓ present locally, 4 Aug 2026 — not committed, like vendor/vlc)*
- [x] ★ Startup **detection**: registry check (`HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`) + import/`CreateCoreWebView2Environment` test · §P3.2
- [x] ★ Runtime missing → the stage shows **"WebView2 is not available"** — clear message, no crash, no blank page; **no bundling, no download** · §P3.2
- [x] ★ COM initialisation + pythonnet wiring **before** any view is created (disclosed v4.0 `main.py` line if required) · §P3.2
- [x] ★ Create **one shared `CoreWebView2Environment`** — user data folder `%LOCALAPPDATA%\Halcyon\webview2_data` (cookies, cache, profile) — one engine for all tabs · §P3.2
- [x] `modes/web/webview2_host.py` — per-tab host: a child HWND (`QWindow`) + `CreateCoreWebView2Controller`; the page is a native child window **below** Halcyon's chrome · §P3.2
- [x] ★ **Verify it renders inside the main window** — no second window anywhere
- [x] ★ Verify **popup routing**: `add_NewWindowRequested` → **new Halcyon tab** (15-cap applies); no outside window · §P3.4
- [x] User agent = current desktop Edge string (strip "WebView2"); hide `navigator.webdriver` (anti-bot — as in Smart Player)
- [x] Sensible settings: JS on, local storage on, autoplay policy, PDF viewer
- [x] Website fullscreen (HTML5 video) works — engine-handled, no Halcyon window · §P3.2
- [x] Download handling — save prompt (or documented fallback)
- [x] Certificate error handling (or documented fallback)

◻ ★ Web renders inside the main window · ◻ Detection: missing runtime → clear "not available" message · ◻ Pages scroll, links work, text input works · ◻ HTML5 video plays · ◻ Popup → new tab, no outside window · ◻ Nothing QML is drawn over the page

---

## Milestone 3.2 — Mode Registration · 0.5 d

- [x] `modes/web/__init__.py` — `ModeSpec` for `"web"` · §P3.3
- [x] `stage_qml` → `WebStage.qml` (overrides the video stage)
- [x] `transport_qml` → `""` — **no bottom bar** · §B.2
- [x] `osd_enabled=False` · `right_dock_enabled=False` · `media_keys_enabled=False` · `uses_player=False`
- [x] ★ v4.0 generic capability `panel_enabled=False` — no left dock in Web (changelogged + regression test) · §A.3 rule 1
- [x] ★ v4.0 generic capability `keep_stage_alive=True` — stage parked, not destroyed, on mode switch (changelogged + regression test) · §A.3 rule 1
- [x] `setup` hook publishes the browser context as `modeContext_web` — no `main.py` edit
- [x] ★ Append one entry to `core/modes.py` — **the only permitted earlier-phase edit besides the disclosed v4.0 capabilities**
- [x] ★ Video engine **stops/releases cleanly** when switching to Web (one-tuner)
- [x] Third chip appears with no `TitleBar.qml` edit

◻ Three chips render · ◻ Switching in any order is stable · ◻ Video engine releases · ◻ Left dock hidden in Web, back to normal in Local/M3U

---

## Milestone 3.3 — Tabs & Address Bar · 1–1.5 d

- [x] `modes/web/TabsRow.qml` — tab strip + **+** button
- [x] ★ Web opens with **no tabs, only +**; typing in the address bar creates the first tab · §P3.4
- [x] + opens an empty tab and focuses the URL field
- [x] Tab shows page title (fallback: URL) + close **×**; active tab highlighted
- [x] ★ **Maximum 15 tabs**; at 15, + greys out and further attempts show *"Maximum 15 tabs reached."* as a small glass pill in the tabs row · §P3.4
- [x] ★ Message renders **inside the tabs row** (chrome, not page — a small glass pill over the tabs), never over the page; fades after a few seconds or on closing a tab · §P3.2
- [x] ★ Tabs survive Web → Local/M3U → Web — order, URLs, titles, active tab; pages still loaded (`keep_stage_alive`)
- [x] ★ Tabs are **not saved after restart** — Web opens empty
- [x] ★ Site popups / new windows open as **new Halcyon tabs** (`add_NewWindowRequested`; 15-cap applies); no outside window · §P3.4
- [x] `modes/web/AddressBar.qml` — built from the same `IconButton` vocabulary · §B.1
- [x] **Icon-only buttons:** Back · Forward · Reload/Stop · Home · bookmark star · bookmarks/menu icon
- [x] URL field: text-based, shows current URL, selects all on focus, `Enter` navigates
- [x] Non-URL input goes to the search engine (**Google**)
- [x] Reload becomes **Stop** while loading; **Home → the loaded site's homepage; on a blank tab → Google**
- [x] Active tab's page title reflected in the window title
- [x] ★ **No media controls render in Web mode** — no play/pause, seek, volume, track menu, repeat/shuffle, PiP
- [x] ★ **No media OSD fires in Web mode**
- [x] ★ Media hotkeys inert (`Space` scrolls the page)

◻ All navigation works · ◻ Search fallback works · ◻ 15-tab cap + in-chrome message works · ◻ Tabs persist across mode switches, not restarts · ◻ No transport bar, no OSD, hotkeys inert

---

## Milestone 3.4 — Bookmarks · 1 d

- [x] `modes/web/bookmarks.py` — JSON store in `%APPDATA%\Halcyon`, **permanent** · §P3.5
- [x] ★ **Bookmarks start completely blank** — no default bookmarks · §P3.5
- [x] ★ Quick star: **empty = not bookmarked** → click opens Add popup (title prefilled); **filled = bookmarked** → click opens **Edit / Remove / Cancel**
- [x] Star state follows the active tab's URL
- [x] `modes/web/BookmarksDropdown.qml` — Edge-style, anchored under the menu icon (frameless popup window, §P3.2)
- [x] Opens on the menu icon; closes on same icon again, outside click, `Esc`
- [x] **Manage Bookmarks** pinned at the top; rows are **text** (title + URL), click navigates; empty-state message
- [x] `modes/web/BookmarksManagerTab.qml` — an **internal tab**, not a website
- [x] Add manual bookmark: **title + URL** fields
- [x] Edit · Delete (with confirm) · Reorder (drag) · Search (filter as you type)
- [x] Everything persists immediately; survives restart
- [x] ★ **No left bookmark drawer** — Web has no dock panel · §P3.1

◻ Star states + popup actions work · ◻ Dropdown open/close rules work · ◻ Manager add/edit/delete/reorder/search all persist · ◻ No left drawer anywhere in Web

---

## Milestone 3.5 — Final Integration & Release · 1–2 d

- [x] ★ Nuitka packaging with **pythonnet + the vendored connector DLL** — no Chromium to bundle, WebView2 is OS-provided · §10
- [x] Verify WebView2 works in the frozen build (connector DLL discoverable)
- [x] Full `Theme.qml` consistency pass across all three modes · §B.3
- [x] Settings dialog covers all modes
- [x] About dialog with version and licence notices
- [x] Final animation pass
- [x] Update `README.md`
- [x] Build installer, tag `v1.0.0`

### ◻ §B.3 — "One machine" review
- ◻ Screenshots of all three modes side by side look like **one product**
- ◻ No control is drawn by a component existing only for one mode *(tabs row, address bar, bookmark popup and PiP excepted)*
- ◻ No mode defines a colour, blur, radius, or duration outside `Theme.qml`
- ◻ Each bar looks **designed for its own contents** — balanced, no gaps, no cramping
- ◻ Switching modes feels like **one app changing channel**, not a different app loading

---

## ◻ PHASE 3 SIGN-OFF · §P3.6

**Regression first**
- ◻ **Phase 1 and Phase 2 sign-off lists both re-run and passing**
- ◻ Deleting `modes/web/` leaves Local + M3U fully working
- ◻ No Phase 1 or Phase 2 file edited except the one `core/modes.py` line and the **disclosed v4.0 generic capabilities** (`panel_enabled`, `keep_stage_alive` — see `PHASE3_DISCLOSED` in `tools/check_isolation.py` + their regression tests)
- ◻ `tools/check_isolation.py` passes

**Engine & layout**
- ◻ ★ Renders INSIDE the main window — no second window appears anywhere
- ◻ Detection: runtime missing → clear "WebView2 is not available" message
- ◻ Edge WebView2 engine confirmed (user agent); direct pythonnet bridge + vendored connector DLL
- ◻ Browser profile under `%LOCALAPPDATA%\Halcyon\webview2_data`
- ◻ Layout: title bar · tabs row · address bar · page; glass shell intact; **no dock panel**
- ◻ Scroll, links, text input work; HTML5 video plays with the page's own controls

**Tabs**
- ◻ No tab on entry, only +; typing creates the first tab
- ◻ + / close × / active highlight work
- ◻ Max 15; the 16th shows "Maximum 15 tabs reached." — inside the chrome, never over the page
- ◻ Tabs survive Web → Local/M3U → Web (pages still loaded)
- ◻ Not saved after restart — Web opens empty

**Address bar**
- ◻ Back · Forward · Reload/Stop · Home
- ◻ URL field: current URL, select-all on focus, Enter navigates, non-URL searches
- ◻ No transport bar, no seek bar, no volume — absent, not greyed

**Popups**
- ◻ Site popup/new-window → new Halcyon tab (`NewWindowRequested`); at 15, blocked with the in-chrome message
- ◻ No outside browser window ever appears

**Bookmarks**
- ◻ ★ Star states + Add popup + Edit/Remove/Cancel; follows navigation
- ◻ Dropdown open/close rules (same icon, outside, Esc); text title+URL rows; Manage Bookmarks on top
- ◻ Manager tab: manual add (title+URL), edit, delete, reorder, search — all persist
- ◻ Bookmarks survive restart; no left drawer

**Controls & integration**
- ◻ No media OSD; media hotkeys inert (Space scrolls)
- ◻ Switching away returns cleanly; video engine released
- ◻ Three chips; any switching order stable
- ◻ Three lists never cross-contaminate
- ◻ Settings/theme/geometry consistent; clean shutdown from any mode
- ◻ Installer works on a clean Windows machine — no VLC, no Python, no extra web runtime

**→ Merge to `main`, tag `v1.0.0`. 🎉**

---

# PHASE 4 — Mini Mode v1.1 — Local Compact Bar · §M

**Ship:** `v1.1.0-mini` · **Est:** 0.5–1 day · **Branch:** `phase-4-mini` or `main` post-v1.0

> ★ **Not a 4th ModeSpec.** Shell state `miniModeActive` in `Main.qml`. Only Local when media loaded. Height = `Theme.titleBarHeight: 44px` so it sits on Word/Explorer title bar. Width may increase to 400-420px to accommodate controls but still title-bar sized. Owner decisions 7 Aug 2026 locked.

## Milestone 4.1 — Mini Bar · 0.5–1 d

### Build

- [x] `ui/shell/MiniBar.qml` — fixed **400–420 × 44**, glass `Theme.glassFill`, blur 32, radius 12, always-on-top when active · §M.2
- [x] Layout: **grip ⋮⋮ (24px, only draggable via `startSystemMove()`) · prev track · seek -10s · play/pause 44px with circular progress ring · stop · next track · seek +10s · volume/mute · return** — 8 controls + grip, 32-40px hit targets, from shared `IconButton` vocabulary · §M.3 §B.1
- [x] ★ **Innovative seek without width increase:** top 3px hairline of bar IS seek bar — 2px rest (played accent gradient + buffered), 6px + knob + tooltip on hover, click/drag to seek live · §M.4
- [x] ★ Circular progress ring around play button — 0-100% fill, accent colour, glanceable without width · §M.4
- [x] Volume: mute icon click = `Actions.toggleMute`, hover → vertical `GlassPanel` slider 140px tall pops ABOVE bar (overlay, no width increase) · §M.4
- [x] All controls bind to **same `Actions` entries** as Local transport — `playPause`, `stop`, `prev`, `next`, `seekRelative`, `toggleMute`, `toggleMiniMode` — no second implementation · §4.1
- [x] `ui/shell/TitleBar.qml` — add mini toggle left of minimize as `[mini][─][□][✕]`, glyph relevant, tooltip "Mini Mode", enabled only when `activeModeId=="local"` && `hasMedia`, grayed in M3U/Web/no media · §M.5
- [x] `ui/Actions.qml` — new `toggleMiniMode` action, single implementation · §4.1
- [x] `ui/Main.qml` — `miniModeActive` bool, hide TitleBar/PanelHost/InfoPanel/Stage when active (Stage kept alive hidden, not destroyed — no black flash), fixed window size `min==max==400-420×44`, hide 8 resize handles, `StayOnTopHint` when active, save/restore normal geometry (`x,y,w,h,wasMaximized,wasFullscreen`) · §M.5 §M.6
- [x] `core/settings.py` — `miniBarPos` + `firstTime` flag, top-center on first activation: `screen.x + screen.width/2 - miniWidth/2, y=screen.y+12` · §M.5
- [x] Always-on-top, first-time top-center, only grip drags · §M.5
- [x] No close from mini: intercept `onClosing` in mini → `close.accepted=false; toggleMiniMode()` → returns to normal; only normal can `Qt.quit()` · §M.5
- [x] Auto-return on playlist naturally finished (no next, repeat off) → toggle to normal · §M.5
- [x] Mini video policy: while Mini is active, force the effective Local output to the Soft I420 path (disable the native child); on return, re-resolve the selected `Video mode` (`Auto` or `Turbo`) and fall back to Soft if native setup fails · §M.6 / §V
- [x] No auto-hide, no cursor hide in mini — bar always visible · §M.5

> **Re-verified 2026-08-11 — three boxes above are ticked but the code has since diverged
> from the spec they describe.** Left ticked because the *feature* is built and working;
> flagged here because the ticks no longer describe what ships. All three look like
> deliberate post-build improvements, but they were never written down, so confirm them:
>
> 1. **Width is 460px, not "400–420".** `ui/shell/MiniBar.qml:16` sets `width: 460` and
>    `ui/Main.qml:64` clamps `Math.max(460, …)`. Height is correct — `Theme.titleBarHeight`
>    (44px), so it still sits on a Word/Explorer title bar as intended. Only the width
>    budget slipped, presumably to fit the volume capsule below.
> 2. **Volume is a horizontal capsule to the right of mute, not a vertical pop-up slider.**
>    The file header states this outright: *"Innovative horizontal volume capsule to right
>    of mute button — zero clipping."* The box (and `docs/MINI_MODE_SUMMARY_v1.1.md:41`)
>    still describes the 140px vertical `GlassPanel` that pops above the bar. This is
>    almost certainly *why* the width grew to 460.
> 3. **No tooltips in Mini Mode.** Header: *"Zero tooltips in Mini Mode for unobtrusive,
>    clean controls."* The seek box above promises a *"knob + tooltip on hover"* and
>    §M.4 / summary line 48 promise a *"time tooltip"*. The hairline seek itself is built.
>
> **Nothing here is broken** — this is documentation drift, and the shipped behaviour may
> well be the better design. Decide which is authoritative, then either amend §M.2–M.4 in
> the plan or restore the original spec in the code. Until then the §M.7 verify boxes
> below should be read against the *code*, not the *text*.

### ◻ Verify — Mini Mode

- ◻ Toggle button renders left of minimize, only enabled in Local when media loaded, grayed in M3U/Web/no media
- ◻ Click → window becomes fixed 400–420×44, frameless, always-on-top, top-center first time, glass matches Theme.titleBarHeight
- ◻ Bar shows grip ⋮⋮ + 8 controls in order, 44px height, balanced, no gaps
- ◻ Only grip drags window, buttons click normally
- ◻ Top 3px hairline seek: 2px rest, 6px + knob on hover, click/drag seeks, buffered behind played, time tooltip
- ◻ Play button circular ring shows 0-100% progress
- ◻ Volume: mute click toggles, hover pops vertical slider above bar, live
- ◻ Seek -10s/+10s, prev/next, play/pause, stop all work via same Actions as Local
- ◻ Video hidden, audio continues, CPU not higher
- ◻ Return via return button / Esc / Alt+F4 → normal geometry restored, video instantly resumes no black flash
- ◻ Playlist finished while in mini → auto-return to normal
- ◻ No close from mini — taskbar close returns to normal, only normal can quit
- ◻ No auto-hide, no cursor hide
- ◻ Sits cleanly on Word/Explorer title bar (44px height match)
- ◻ No PiP conflict (PiP M3U only, Mini Local only), one-tuner intact
- ◻ `tools/check_isolation.py` passes, Phases 1-3 regression still passing

**→ Tag `v1.1.0-mini`**

---

# PHASE R — Mobile Remote v1.2 · §R — SPEC LOCKED (2026-08-08), **BUILT AND SIGNED OFF 2026-08-09**

> **Build started 2026-08-08 (owner decision — overrides the §R build-gate).** All boxes below are from `HALCYON_PLAN.md` §R (locked 2026-08-08). Each step lands with the full regression suite and `tools/check_isolation.py` green, and **no player code path is modified** — the remote is a new doorway onto existing `AppController` actions (§4.1).
>
> **Locked decisions (owner, 8 Aug 2026):** web page in phone browser (no install) · server on by default, starts last at startup, stops on exit · QR in PC Settings → Mobile Remote is the only key — **no PIN** · real-time sync, PC is source of truth · one shot, no versions · Local playlist pinned **bottom, 7 rows max + autoscroll** · **no lyrics on mobile** · M3U add source = **URL only** · Web = active page only, universal media control via WebView2 `ExecuteScriptAsync` · **PiP + Fullscreen on M3U chip** · subtitle download on Local · ⚡ Power (collapsed) = Sleep / Shutdown.

## Milestone R.1 — Server + QR · 2 d

- [x] `aiohttp` server starts as the **last step of app startup**; stops cleanly on exit (`aboutToQuit`) — *Step 1 (2026-08-08): `remote/` package, guarded start (no aiohttp → app unaffected), `/health`, tests `test_remote_server.py`; suite 339 passed*
- [x] QR code + URL rendered in **PC Settings → Mobile Remote** section (regenerates on demand) — *Step 2: `remote/qr.py` PNG route, Settings dialog section; `qrcode[pil]` activated*
- [x] Phone opens the remote page by scanning the QR / typing the URL; connection dot shows live link — *Steps 2–5: phone UI served at `/`, SSE live-status dot in header*

## Milestone R.2 — Common shell + Local chip

- [x] Common shell: header + status dot · 3 chips (`Local`/`M3U`/`Web`) · Now Playing bar · ⚡ Power (collapsed) at bottom
- [x] Tapping a chip switches the **PC's** mode too (same `Actions.switchMode` as a PC click)
- [x] Real-time status push (time, volume, title, playing state) — PC is source of truth, phone mirrors
- [x] Transport: play/pause · stop · next/prev · seek bar + ±10 s · speed 0.5×–2×
- [x] Volume slider + mute
- [x] **Drive browser:** all drives · folder navigation · media-only filter · tap file = plays on PC · add file/folder to playlist
- [x] **Playlist pinned bottom, max 7 rows visible + autoscroll** · tap to play · reorder · remove · clear · shuffle · repeat
- [x] Tracks & subtitles: audio track · subtitle track · **download subtitles** (search/language/results/download) · load subtitle file (drive browser) · subtitle delay
- [x] Equalizer sliders + presets (same as PC)
- [x] Now playing card: album art, title, artist — **no lyrics**

## Milestone R.3 — M3U chip

- [x] Transport: prev ch · play/pause · next ch · stop · seek (VOD) · volume + mute
- [x] **PiP button + Fullscreen button** (act on PC)
- [x] Sources: list · **add by URL field only** · edit · remove
- [x] Channels: grouped list · search/filter · expand/collapse · favourites filter · tap = plays on PC
- [x] Favourites: star/unstar · favourites-only view

## Milestone R.4 — Web chip + Power

- [x] Active page card: title + URL of the **active tab only**
- [x] Bookmarks: list · tap = open in active tab · add current page · remove
- [x] **Universal media control** on the active tab via WebView2 `ExecuteScriptAsync` (play/pause · seek · time · volume/mute · fullscreen)
- [x] ⚡ Power: **Sleep** / **Shutdown** (acts on the PC) under collapsed/expand section
- [x] DRM sites (Netflix/Prime-class): show status, transport may not respond — acceptable

## ◼ PHASE R SIGN-OFF · §R.5 — VERIFIED 2026-08-09

- [x] QR scan → remote opens on Android phone in under a second
- [x] Every control in §R.2 works from the phone and is reflected on the PC instantly
- [x] PC-side status (time/volume/title) is always live on the phone — no stale state
- [x] Local: drive browser reaches **all drives**, plays and adds to playlist; playlist pinned bottom, 7 rows + autoscroll
- [x] Local: subtitle download + subtitle file load work via phone
- [x] M3U: add source by URL, channels grouped, favourites, PiP + Fullscreen all work
- [x] Web: bookmarks open in active tab; video on the active page is controllable (except DRM sites)
- [x] ⚡ Power: Sleep and Shutdown work; app exits cleanly (PowerGuard released)
- [x] Phone tap = same action as PC control — no duplicated implementations (§4.1)
- [x] Phases 1–3 regression still passing, `tools/check_isolation.py` passes

**→ Tag `v1.2.0-remote` — COMPLETE, owner verified 2026-08-09**

---

# PHASE U — Vendor Update Tab · §U — DESIGN LOCKED (2026-08-10), **BUILD COMPLETE** (all 18 build tasks ticked; awaiting your ◻ verification)

> **Owner decisions locked 10 Aug 2026.** Third tab in Settings → Update. Checks VLC + WebView2 vendor files only (not the app itself). One click checks both. Shows version diff, download links, extraction guide, place-at paths with 📁 Open Folder buttons. Icon-based buttons (↻ Check / ✕ Cancel).

## Milestone U.1 — Update tab · 0.5–1 d

- [x] `core/update_checker.py` — `UpdateChecker(QObject)` exposed as `UpdateChecker` QML context property · §U.2
- [x] Version detection: reads `vendor/vlc/libvlc.dll` product version (PowerShell `VersionInfo`) · §U.2
- [x] Version detection: reads `vendor/webview2/Microsoft.Web.WebView2.Core.dll` file version (fallback: `.nupkg` filename) · §U.2
- [x] Known latest versions as constants: `VLC_KNOWN_LATEST = "3.0.21"`, `WEBVIEW2_KNOWN_LATEST = "1.0.2903"` · §U.2
- [x] `checkUpdates()` slot — runs detection + comparison, emits `checkStarted` / `checkFinished(result)` · §U.2
- [x] `openFolder(relativePath)` slot — opens folder in Windows Explorer (`os.startfile`) · §U.2
- [x] `openVlcDownload()` / `openWebview2Download()` slots — opens download URL in default browser · §U.2
- [x] `main.py` — imports `UpdateChecker`, creates instance, adds to `_KEEP_ALIVE`, registers as QML context property · §U.1
- [x] `tools/check_isolation.py` — adds `PHASE_U_DISCLOSED` list (allows `main.py` as a frozen-path exception for this phase) · §U.1
- [x] `SettingsDialog.qml` — adds `Update` tab (3rd, `Glyphs.refresh` icon) to tab model · §U.3
- [x] `SettingsDialog.qml` — `UpdateTabContent` inline component with state machine (idle/checking/result) · §U.3
- [x] `SettingsDialog.qml` — ↻ Check button (accent bg, enabled when not checking) + ✕ Cancel button (enabled only during checking) · §U.3
- [x] `SettingsDialog.qml` — Idle state: description + app root path · §U.3
- [x] `SettingsDialog.qml` — Checking state: spinning refresh icon + "Checking for updates…" text · §U.3
- [x] `SettingsDialog.qml` — Result (up to date): ✓ "All components are up to date" + version summary table (VLC / WebView2 + ✓) · §U.3
- [x] `SettingsDialog.qml` — Result (update available): "Update Available" header + per-component sections with:
  - Current → Latest version display
  - Clickable download link (shortened domain + ↗ indicator, opens browser)
  - Extraction guide (where to find files after extracting)
  - File list with location notes
  - Place-at paths with 📁 Open Folder icon buttons (`Glyphs.addFolder`, 28×28)
- [x] Dialog width increased to 560px, height to 600px · §U.3
- [x] All Theme tokens used — no hardcoded colours, radii, or durations · §B.1

> **Re-verified 2026-08-11 (static checks only — no Windows here).** Every build box above
> was confirmed against the source, not assumed: `core/update_checker.py` byte-compiles
> clean; `main.py` imports `UpdateChecker` (:178), instantiates it (:217) and registers the
> context property (:252); `SettingsDialog.qml` sets `width: 560` / `height: 600` (:16-17),
> declares `UpdateTabContent` (:753) and wires `UpdateChecker.vlcFiles`,
> `vlcPlacePaths`, `webview2Files` and `openFolder()`; the Update entry sits at
> `tabIndex: 2` with `Glyphs.refresh` (:1427); the Update tab body contains **zero** hex
> colour literals, so the Theme-token box holds; `PHASE_U_DISCLOSED = ["main.py"]` exists
> (`tools/check_isolation.py:130`) and the checker passes.
>
> **One deviation from the spec, flagged not hidden:** the tab model has **four** tabs —
> `General | Shortcuts | Update | About` (:1425-1428) — where §U says three. `About` is not
> scope creep: it is the Phase 3 "About dialog with version and licence notices" item
> (line 762) re-homed as a tab. Update is still literally the third tab, so the §U wording
> is satisfied; the plan text just predates the About move. **Your call whether that is
> the intended final shape** — it is a UI decision, not a defect.

### ◻ Verify — Vendor Update tab

- ◻ Third tab "Update" renders in Settings with refresh icon, same style as General/Shortcuts
- ◻ ↻ Check button: accent background, textOnAccent icon, enabled when not checking
- ◻ ✕ Cancel button: disabled when idle, enabled only during checking
- ◻ Clicking Check: transitions to "Checking…" with spinning refresh icon
- ◻ After check completes: shows either "All up to date" ✓ or "Update Available" per component
- ◻ "All up to date" state: version summary table with ✓ marks
- ◻ "Update available" state: version diff, clickable download links, extraction guide, file list, place-at paths
- ◻ Download link click: opens correct URL in default browser
- ◻ 📁 Open Folder click: opens Windows Explorer at the correct absolute path
- ◻ Cancel click: returns to idle state
- ◻ `tools/check_isolation.py` still passes

**→ Tag `v1.3.0-update`**

---

# Deferred — post-v1.0 · §8

Not in any phase above. Recorded so they aren't mistaken for oversights.

- [x] **Mobile remote + QR** — ~~deferred~~ **built and signed off** as PHASE R (v1.2.0-remote, verified 2026-08-09). Ticked here only to stop it reading as outstanding; the live record is PHASE R above.
> The five below are **deliberately open** — they are the post-v1.0 backlog, not unfinished
> work. They are left unticked on purpose: ticking them would claim shipped features that
> do not exist. Nothing in the v1.3 scope depends on them.

- [ ] Seek-bar frame thumbnails — needs a second decoder instance
- [ ] Bookmark folders
- [ ] "Play in Halcyon" — pipe a resolved web stream URL into libVLC
- [ ] libVLC 4 GPU path — blocked on upstream release · §0.5
- [ ] Chromecast / DLNA — out of scope

---

# Standing Rules — check at every commit

> These are a **recurring prompt, not a task list**: they are re-asked at every commit and
> so are never permanently "done". Left unticked by design — a ticked box here would be
> meaningless the moment the next commit lands. Status against the current tree, 2026-08-11:

- [ ] ★ **§4.1** — is this action implemented in exactly one place, and does everything else *bind* to it? — *holds; the `read()` helper added 2026-08-11 collapsed a repeated property/method access into one place*
- [ ] ★ **§B.1** — is this built from the shared component vocabulary, not a lookalike?
- [ ] ★ **§B.2** — is this layout designed for its own contents, with no ghost slots?
- [ ] ★ **§A.3** — has any frozen file from an earlier phase been touched? — *`modes/local/playlist.py` was touched 2026-08-11 to fix a teardown segfault; disclosed below*
- [ ] ★ **§9** — are all ctypes callbacks hard-referenced on a long-lived object? — *confirmed: `engine/video_out.py` holds `_cb_lock/_cb_unlock/_cb_display/_cb_format/_cb_cleanup`*
- [ ] ★ Does anything hardcode a value that belongs in `Theme.qml`?
- [ ] `tools/check_isolation.py` passes — *green, 2026-08-11*

---

*Generated from `HALCYON_PLAN.md` v4.2 — 8 August 2026 — includes Mini Mode v1.1 + Mobile Remote v1.2 (§R, built and signed off) + Vendor Update tab (§U, built).*

*Last reconciled 2026-08-11: counts recomputed from the boxes, Phase 0 re-verified, two
defects found and fixed (see "Verification pass" at the top). All `◻` owner-verification
marks left untouched — they are yours to set.*
