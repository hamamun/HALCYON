# Halcyon — Media Player Architecture & Build Plan

> **Halcyon** *(hal-see-on)* — "calm, golden, untroubled."
> A media player that plays *everything*, looks like liquid glass, and has no seams.
>
> **Tagline:** *Every format. One pane of glass.*

| | |
|---|---|
| **Version** | Plan **v4.5** — 12 August 2026 *(status reconciled against the code 11 August 2026; Local video-mode policy recorded, implementation not started)* |
| **Changes in v4.5** | **Local video modes and Settings policy (§V) — design locked 12 Aug 2026.** The accepted normal Settings contract is one visible `Video mode` dropdown for Local with `Auto`, `Soft`, and `Turbo`; M3U shows the same control as disabled `Soft`; Web leaves Video mode disabled. `Auto` chooses Soft or Turbo only for Local media, Turbo setup failures fall back to Soft without interrupting playback, and the old `playback.turboMode` checkbox plus technical `video.backend` dropdown are not part of normal Settings. The dropdown must use readable contrasting background/text colours. This documentation entry contains no code implementation, commit, or push. |
| **Changes in v4.4** | **Vendor Update tab (§U) — design locked 10 Aug 2026; BUILT 10–11 Aug 2026, all 18 build tasks verified against the source 11 Aug 2026, awaiting owner sign-off (§U.5 boxes are hands-on-Windows checks).** Third tab in Settings → Update. Checks vendored VLC (3.0.21) and WebView2 DLLs against known latest versions. Two icon buttons (↻ Check / ✕ Cancel). When update available: shows version diff per component, clickable download link (↗ opens browser), extraction guide (where to find files inside the extracted archive), and place-at paths with 📁 "Open Folder" icon buttons (open Windows Explorer). "All up to date" state shows ✓ summary with current versions. Skips Halcyon app version — only checks VLC and WebView2 vendor dependencies. Owner decisions 10 Aug 2026. |
| **Changes in v4.3** | **Mobile Remote v1.2 — verified COMPLETE (owner, 9 Aug 2026), §R.** All 9 build steps + audit pass landed 2026-08-08 (remote/ package, QR PNG, status SSE, command channel via QueuedConnection, phone UI, Local chip, M3U chip, Web chip, Power). 27 new tests, 366 passed / 0 failed, isolation green, no player path modified (§4.1). Owner verification 09-08-2026: QR <1s, real-time sync, drive browser all drives, playlist pinned bottom 7 rows + autoscroll, subtitle download, M3U add URL + grouped/favourites + PiP/Fullscreen, Web active page + bookmarks + universal media control, Power Sleep/Shutdown. CHECKLIST.md Phase R 10/10 verified, tag `v1.2.0-remote` complete. No push/commit per owner request. |
| **Changes in v4.2** | **Mobile Remote (v1.2) — full spec locked (owner review, 8 Aug 2026), §R.** Phone controls the PC over Wi-Fi via a web page in the phone browser (no install). Tiny `aiohttp` server inside the app, **on by default, starts as the last step of startup loading**, stops on exit. Connect by scanning a **QR code in PC Settings → Mobile Remote** (or typing `http://<pc-ip>:8765`); QR/URL is the only key — **no PIN** (owner: keep it simple). Real-time sync, **PC is the source of truth**, phone is a mirror. One-shot build — no versions. Chip-wise scope: **Local** = transport, volume, drive browser (all drives), playlist pinned to the **bottom with max 7 rows + autoscroll**, tracks & subtitles incl. **subtitle download**, equalizer, now-playing (no lyrics — owner); **M3U** = transport **incl. PiP + Fullscreen**, sources (**add by URL only** — owner), grouped channels, favourites; **Web** = active-page only, bookmarks + **universal media control** via WebView2 `ExecuteScriptAsync` on the active tab; **⚡ Power** (collapsed, every chip) = Sleep / Shutdown on the PC. Build deliberately deferred until v1.0 ships (§8) — no remote code exists yet. |
| **Changes in v4.1** | **Mini Mode (v1.1) — Local compact bar (owner decision 7 Aug 2026).** Shell state, not a 4th ModeSpec: `miniModeActive` bool in `Main.qml` hides TitleBar, PanelHost, InfoPanel, Stage (kept alive, not destroyed, zero black flash). Bar is **fixed 400-420px × 44px** — height equals standard `Theme.titleBarHeight: 44px` so it sits cleanly on a Word/File Explorer title bar, width increased to accommodate controls but still title-bar sized. Controls: **grip ⋮⋮ (only grip drags) · prev track · seek -10s · play/pause with circular progress ring · stop · next track · seek +10s · volume/mute (vertical pop-up slider above bar) · return**. Toggle button **left of minimize** `[mini][─][□][✕]`, only enabled in Local when media loaded, grayed in M3U/Web or no media. **Innovative seek without width increase:** top 3px hairline of the bar IS the seek bar (2px rest, 6px + knob on hover, click/drag to seek) + circular progress ring around play button. No extra width. Always-on-top, first-time top-center, draggable only via grip, no close from mini (return to normal to quit), auto-return to normal on playlist finished, no auto-hide. |
| **Changes in v4.0** | **Phase 3 final design (owner decision, 4 Aug 2026), engine = Route A.** Web becomes a real browser **inside the main window** on Windows' built-in **Edge WebView2**, reached **directly via pythonnet** + the vendored 788 KB `Microsoft.Web.WebView2.Core.dll` connector (the same proven approach as the owner's Smart Player) — **no Qt WebView, no QtWebEngine, nothing bundled**. Qt WebView was dropped because its Windows backend silently **blocks all popup/new-window requests** (`qwebview2webview.cpp` — "FIXME actually handle new windows"); direct WebView2's `add_NewWindowRequested` routes site popups to **new Halcyon tabs**, never an outside window. Startup **detection** (registry + import test); missing runtime → the stage shows *"WebView2 is not available"*; profile lives in `%LOCALAPPDATA%\Halcyon\webview2_data`. Layout: title bar → **tabs row** → **address bar** → page. Tabs: none on entry (+ only), typing creates the first tab, **max 15** (in-chrome message "Maximum 15 tabs reached." — no toast), survive mode switches, never saved on exit. Bookmarks: **quick star** (empty→Add popup; filled→Edit/Remove/Cancel) + **Edge-style dropdown** (menu icon; closes on same icon/outside/Esc; text title+URL rows; a Halcyon-owned frameless popup window, §P3.2) + **Bookmarks Manager** internal tab (manual add title+URL / edit / delete / reorder / search; permanent store). Search default is **Google**; **Home** goes to the loaded site's homepage (Google's home page on a blank tab); bookmarks start **completely blank** — no defaults. **No left bookmark drawer** — Web has no dock panel; **no media controls, media panels, OSD or PiP**; site videos use their own controls. Two owner-approved generic capability changes (§A.3 rule 1): `panel_enabled` (Web hides the left dock) and `keep_stage_alive` (Web's stage is parked on mode switch so tabs/pages survive). |
| **Changes in v3.5** | **M3U polish (owner decision):** the channel filter gets a one-click clear ×, and M3U shows the shared transport toast for Play/Pause, Next/Previous (with the friendly channel name), volume, mute and fullscreen. Toast capability and the Local-only Info/Lyrics/Equalizer dock are now separate mode flags, so M3U gains feedback without gaining a right dock. |
| **Changes in v3.4** | **One-tuner rule (owner decision):** one engine plays one thing — switching the chip stops whatever is playing; there is never background audio. Entering M3U stops Local (playlist + position preserved; Local's resume prompt brings you back). Leaving M3U stops the stream (list and last channel intact; nothing auto-plays). Enforced from M3U's own `setup` hook — no Phase 1 file is edited. The earlier right-dock/OSD coupling is superseded by v3.5's distinct right-dock flag. |
| **Changes in v3.3** | **Owner decisions (2 Aug 2026):** M3U bar = **seven controls, one row** — stop joins, volume+mute retained. **M3U has no right panel** — Ctrl+I inert, EQ not offered in M3U (the §P1.5 EQ note is technically still true, but superseded: it's simply not exposed there). **Channel grouping selector:** By category (default) / By country / No group. **Playing channel stays highlighted and scrolled into view.** Chip label confirmed: **M3U.** |
| **Changes in v3.2** | **Phase 1 tagged `v0.1.0-local`** — the frozen baseline; `tools/check_isolation.py --phase 2` now actually guards the foundation. **Owner decision: the M3U Playlists manager (§P2.4)** — up to 7 saved sources (URL or local file, add/edit/delete) in M3U's own dialog, opened from the M3U panel toolbar. The title-bar Open idea is dropped (the title bar is frozen, and source management belongs inside the mode). **Loading a source stops the current stream.** §P2.3 snippet corrected to the shipped `ModeSpec` (the `controls=[...]` field never shipped — §B.4 is the mechanism). |
| **Changes in v3.1** | **Web mode now embeds inside the main window** — pywebview dropped for `QtWebEngineQuick`; the "separate window" limitation is gone. **M3U gains volume + mute.** Equalizer confirmed available in all playback modes. New §B: *One Machine, Three Channels* — shared component vocabulary, per-mode layout freedom. §A.1 corrected. |
| **Changes in v3.0** | Restructured into **three independently shippable phases**. Added §A (phase contract & isolation rules), §P1/§P2/§P3 (per-phase scope, deliverables, acceptance tests), repo/branch strategy, and per-phase definition-of-done. |
| **Supersedes** | `AETHER_PLAN.md`, `MPHP_PLAN.md` (both discarded) |
| **Target OS** | Windows 10 / 11 (x64) |
| **Language** | Python 3.12 — 100%, no C++ build step |
| **UI** | PySide6 / Qt Quick (QML) — GPU composited |
| **Engine** | libVLC 3.0.21 (bundled with the app) |
| **License posture** | Personal, non-commercial, not redistributed |

---

## READ THIS FIRST — How this plan is meant to be used

This document is now organised as **three sequential chapters**. Each ends with a running program you can install and test. Nothing from a later chapter is required to make an earlier chapter work.

| Chapter | Ship | You test | Status |
|---|---|---|---|
| **Phase 1** | `Halcyon Local` — full local player | Everything in §P1.7 | ✅ Complete / signed off |
| **Phase 2** | `Halcyon + M3U` — Local untouched, M3U added | §P2.6 (plus P1 regression) | ✅ Complete — tagged `v0.2.0-m3u` |
| **Phase 3** | `Halcyon Complete` — Web added, **in-window** (v4.0 design: Edge WebView2 browser) | §P3.6 (plus P1+P2 regression) | ✅ Complete — tagged `v1.0.0` |
| **Phase 4** | `Mini Mode v1.1` — Local compact 460×44 bar | Everything in §M.7 | ✅ **Built** (`ui/shell/MiniBar.qml`, 415 lines) — awaiting your §M.7 sign-off. **Ships 460px wide with a horizontal volume capsule and no tooltips**, not the 400–420px / vertical-slider / tooltip spec in §M.2–M.4 — see the note in `CHECKLIST.md` Phase 4 |
| **Phase R** | `Mobile Remote v1.2` — Android phone companion | Everything in §R.5 | ✅ **Complete — verified 2026-08-09, tagged `v1.2.0-remote`** |
| **Phase U** | `Vendor Update tab` — Settings → Update | Everything in §U.5 | ✅ **Built** — all 18 build tasks verified against source 2026-08-11, awaiting your §U.5 sign-off. Settings now has **four** tabs (About joined) |

**Do not begin a phase until the previous one is signed off.** Sign-off means every box in that phase's acceptance list is ticked by you, not by me.

---

## A. The Phase Contract

### A.1 What "not interrelated" means — the radio

**One machine. Three channels.**

A radio has one chassis, one faceplate, one set of knobs, one finish. Turning the dial from FM to AM to shortwave doesn't change the radio — it changes **what comes through it**. Some knobs stop doing anything on some bands. The radio is still one radio.

Halcyon is that radio. Local, M3U, and Web are **channels, not three appliances sharing a shelf**.

| | |
|---|---|
| **Independent** — content, data, logic | M3U's parser never touches Local. Local's queue never mixes with M3U's channel list. Bookmarks are their own store. Breaking one cannot break another. Deleting one leaves the others perfect. |
| **Identical** — the machine itself | One window, one title bar, one panel dock, one component vocabulary, one theme, one motion language. Built once. Never forked. Never "the M3U version of." |

The mistake to avoid is the one you've hit in other players: switching mode makes the UI **lurch** — buttons restyle, icons change weight, spacing shifts, things feel like a different program wearing the same skin. That happens when three UIs were built to *resemble* each other instead of being *the same UI*.

**So the contract is:**

> **The shared foundation is built once, in Phase 1, and frozen at sign-off.**
> **Phases 2 and 3 are purely additive: they register new modules against that foundation and modify no Phase 1 file.**
>
> **v3.5 exception (owner-approved):** the generic mode-capability split between
> transient feedback and the right dock updates the shared contract without
> naming M3U. It is documented in the changelog and covered by regression tests.

See **§B** for what "same machine" means concretely — and, importantly, what it does *not* constrain.

### A.2 What "additive only" means mechanically

Phase 1 builds a small **mode registry**. A mode is a plain object declaring five things:

```python
# core/mode_api.py — written once in Phase 1, never edited again
@dataclass(frozen=True)
class ModeSpec:
    id:            str      # "local" | "m3u" | "web"
    title:         str      # title-bar chip label
    panel_qml:     str      # left-dock panel
    stage_qml:     str      # centre stage; defaults to the video surface
    transport_qml: str      # the mode's own bar, built from shared parts (§B.4)
    osd_enabled:   bool     # transient feedback / §6.2
    right_dock_enabled: bool # Info / Lyrics / Equalizer availability
    # v4.0 owner-approved generic capabilities (changelogged · §A.3 rule 1):
    panel_enabled: bool = True       # Web hides the left dock entirely (§P3.3)
    keep_stage_alive: bool = False   # Web's stage is parked, not destroyed (§P3.3)
```

Phase 2 adds `modes/m3u/` containing its own `ModeSpec`, panel, and parser, then appends one line to a registration list. Phase 3 does the same for `modes/web/`.

**The mechanical test:** delete `modes/m3u/` and `modes/web/` from a finished build. The app must still start and Local must work perfectly. If it doesn't, isolation has been violated.

### A.3 Rules that hold across all phases

1. **No later phase edits an earlier phase's files.** Only exceptions: appending to the mode-registration list, adding rows to the acceptance-test file, and an owner-approved generic capability change documented in the version changelog (v3.5's `right_dock_enabled` split). Any other edit means the foundation was wrong — stop and fix Phase 1 properly rather than patching around it.
2. **No mode imports another mode.** Enforced by a lint check in CI (§A.5).
3. **Shared code lives in `engine/`, `core/`, `ui/shell/`, `ui/components/`.** Mode-specific code lives in `modes/<id>/`. Nothing else.
4. **Every phase ends with a tagged, installable build.** Not a branch, not a dev script — something you double-click.
5. **Regression is part of acceptance.** Phase 2 acceptance includes re-running the whole Phase 1 checklist.

### A.4 Repo & branch strategy

```
main                     ← only ever holds signed-off phases
 ├─ phase-1-local        → merge + tag v0.1.0-local
 ├─ phase-2-m3u          → merge + tag v0.2.0-m3u
 └─ phase-3-web          → merge + tag v1.0.0
```

Work happens on the phase branch. Merge only after your sign-off. Tags mean you can always go back to a known-good Local-only build.

Suggested `.gitignore`: `.venv/`, `__pycache__/`, `build/`, `dist/`, `*.spec`, `vendor/vlc/` *(large binaries — document how to fetch them in the README rather than committing 60 MB)*.

### A.5 Isolation guard (continued below in §B)

A ~30-line script, added in Phase 1, run before each merge:

```python
# tools/check_isolation.py
# Fails if:
#   • modes/<a>/ imports modes/<b>/
#   • anything in engine|core|ui/shell imports modes/*
#   • a phase-2+ commit touches a frozen phase-1 path
```

Cheap to write, and it makes §A.1's promise enforceable instead of aspirational.

---

## B. One Machine, Three Channels

*This section resolves a misunderstanding worth recording. I initially proposed that shared controls stay pixel-identical across modes — fixed slots, anchored clusters, so nothing ever moves. **That was wrong**, and it isn't what the radio analogy implies. A shortwave band with fewer functions gets a control layout that suits it; it doesn't inherit FM's spacing with gaps where knobs used to be.*

### B.1 What is shared — the vocabulary

**Built once in Phase 1. Never forked, never re-implemented, never "the M3U version of."**

| Shared | Meaning |
|---|---|
| **Window shell** | Frameless chrome, 8 resize handles, title bar, drag-move, snap — identical in every mode |
| **Component library** | `IconButton`, `GlassPanel`, `Slider`, `Menu`, `Popover`, `ListRow`, `Toolbar` — one implementation each |
| **Theme tokens** | `ui/Theme.qml` — colours, blur radii, corner radii, accent, type scale, motion curves |
| **Button anatomy** | 40×40 hit target, same icon set and stroke weight, same hover ring, same tooltip style, same press feedback |
| **Panel dock** | 300px left slot, same toolbar row height, same list row height, same selection highlight |
| **Motion language** | 220 ms `OutCubic`; nothing anywhere uses a different duration or curve without reason |
| **Engine + video path** | One `vlc_engine`; Soft callback pipeline plus bounded Local Turbo output policy |
| **Actions singleton** | §4.1 — one implementation per action |

A play button in M3U is **the same `IconButton` with the same icon, size, and hover behaviour** as in Local. Not a lookalike — the same component.

### B.2 What is free — the arrangement

**Each mode composes those shared parts into whatever layout fits its job.**

- Control bar **height differs** — Local ~72px (two rows: seek bar above buttons), M3U ~52px (one row), Web has a nav bar instead.
- Control bar **grouping and order differ** — M3U doesn't inherit Local's left/centre/right clusters. It's laid out for its seven controls, centred and balanced, as if designed for seven from the start.
- **No reserved gaps. No ghost slots. No "where the seek bar would have been."** M3U's bar is designed for M3U, not Local's bar with holes punched in it.
- Panel toolbars differ — four buttons in Local, one in M3U — each spaced properly for its own count. **Web has no dock panel** (v4.0 owner decision): its chrome is a tabs row + address bar inside the stage (§P3.4).

**The invariant is not "same positions." It is "same parts, same feel."** Switching modes should feel like changing bands on one radio: the machine is unmistakably the same, the panel is arranged for what this band does.

### B.3 The test that matters

Not a pixel-overlay comparison — that would enforce exactly the wrong thing. Instead:

- [ ] Screenshot all three modes side by side. Do they look like **one product**? Same glass, same icon weight, same corner radii, same type, same accent.
- [ ] Is any control drawn by a component that exists **only** for one mode? *(Should be no — except genuinely mode-unique things like the tabs row, the address bar and PiP.)*
- [ ] Does any mode define its own colour, blur value, corner radius, or animation duration outside `Theme.qml`? *(Should be no.)*
- [ ] Does each bar look **designed for its own contents** — balanced, no awkward gaps, no cramping?
- [ ] Does switching modes feel like the **same app changing channel**, not like a different app loading?

### B.4 Consequence for the plan

`TransportBar.qml` is no longer a single component filtering a list of controls. It becomes:

- **`ui/transport/`** — shared parts: `PlayButton`, `SeekBar`, `VolumeControl`, `TimeDisplay`, `TrackPopover`, `TransportScrim`
- **`modes/local/LocalTransport.qml`** — arranges them in the two-row Local layout
- **`modes/m3u/M3UTransport.qml`** — arranges a subset in the one-row M3U layout

Same building blocks, different assembly. This is *more* faithful to §4.1, not less: each control is still implemented exactly once. Only the arrangement is per-mode, and arrangement was never the thing being deduplicated.

---

## 0. The One Asterisk — Solved

*This section is Phase 1, Milestone 0. It gates the entire project.*

### 0.1 The problem, stated precisely

You want a **frameless glass UI with floating panels that overlap the video** — a translucent transport bar sitting *on top of* the picture, blurred panels sliding *over* it.

The default way to embed libVLC is `media_player.set_hwnd(winId)`. This makes VLC create a **native Win32 child window (HWND)** inside your window. On Windows, native child windows are composited by the OS *above* everything the Qt scene graph draws. Your glass bar renders — and is then painted over by the video. You cannot fix this with z-order, `raise()`, or stacking; it is how the desktop window manager works.

That is the "click-through / overlay bug." It is not a Qt bug and it is not a VLC bug. It is a fundamental consequence of mixing a native surface with a GPU-composited scene graph.

**Therefore: the Soft path will never give libVLC an HWND.** Soft video arrives as *pixels we own*, so it becomes an ordinary item inside the Qt scene graph — sortable, clippable, blurrable, and paintable *under* other items. The Local-only Turbo path is the explicit, bounded exception: it uses a native VLC child HWND only when the effective mode is Turbo, embeds that child inside the main Halcyon window with Qt's `QWindow.fromWinId()` + Qt 6.8+ `WindowContainer`, and hosts any controls/panels that must sit above it in a transparent QML child-window overlay. This is a window-layer composition route, not a claim that ordinary QML siblings can paint over an HWND.

### 0.2 Why the obvious fix is a trap

The standard answer is `video_set_callbacks()` — VLC's `vmem` output. VideoLAN's own documentation is blunt:

> *"Rendering video into custom memory buffers is considerably less efficient than rendering in a custom window… Hardware video decoding acceleration will either be disabled completely, or require (relatively slow) copy from video/DSP memory to main memory. Sub-pictures (subtitles, OSD) must be blent into the main picture by the CPU… Memory copying is required between LibVLC reference picture buffers and application buffers."*

And in practice people bolt a **second** copy on top. The canonical Qt6 recipe:

```python
frame.map(QVideoFrame.WriteOnly)
memcpy(frame.bits(0), vlc_buffer, nbytes)   # ← the killer
frame.unmap()
sink.setVideoFrame(frame)
```

Qt forum reports of "high CPU usage" from custom video sinks trace almost entirely to that `memcpy`. In Python it's worse — naive implementations round-trip `PIL.Image.frombuffer` → `numpy.array` → `QImage`, which is **three** full-frame copies per frame plus GC churn. At 1080p60 that's ~1.5 GB/s of pointless memory traffic, and it will stutter.

**The two costs are separable.** Cost A (no hardware decode) is inherent to `vmem`. Cost B (extra copies) is implementation sloppiness. Halcyon eliminates B entirely and manages A.

### 0.3 Soft solution — triple buffer → QSG texture

**Core insight:** VLC's `lock` callback asks *us* where to write. We hand it a pointer to memory **we allocated and keep for the callback lifetime**. VLC decodes *directly into our buffer*, with no callback-time format conversion or application memcpy before the frame is published. The render handoff still retains safe ownership before VLC can reuse a slot; that boundary is deliberately explicit rather than promising end-to-end GPU zero-copy.

The ring is the ownership boundary for the Soft path. A `QImage` may view a ring slot during callback work, but the render handoff must retain safe frame ownership before the callback can reuse that slot. The Soft path therefore preserves the existing I420 callback route, its plane uploads, and its RV32 fallback; it must not be described as an end-to-end zero-copy GPU path. Turbo exists separately for demanding Local media so Soft's CPU decode/upload cost is not a 4K60 hard wall.

```
┌──────────────────────────────────────────────────────────────┐
│  VLC decoder thread                                          │
│    lock()    → returns &ring[write_idx]   (no alloc, no copy)│
│    ...decodes + blends subtitles straight into our memory... │
│    display() → atomically publish write_idx, rotate buffers  │
└───────────────────────────┬──────────────────────────────────┘
                            │  (index handoff only — 8 bytes)
┌───────────────────────────▼──────────────────────────────────┐
│  Qt render thread — VideoSurface(QQuickItem)                 │
│    QImage/plane data retained for render handoff (Soft)      │
│    createTextureFromImage(...)  (GPU upload per plane)       │
│    QSGSimpleTextureNode → scene graph                        │
└──────────────────────────────────────────────────────────────┘
                            │
                   video is now a normal QML Item
              → glass bar, blur, rounded corners, shaders
                    all composite correctly, forever
```

**Triple buffering** makes this safe without blocking. VLC writes slot A while Qt reads slot C and slot B holds the newest complete frame. Neither thread waits; no tearing. A single `threading.Lock` protects only three integers — held for microseconds, never during pixel work.

**Bonus:** because frames live in *our* buffer, **any number of surfaces can read them**. Picture-in-Picture (Phase 2) becomes nearly free — a second window on the same buffer, no second decode.

### 0.4 Format choice: I420, not RV32

Every example online uses `RV32` (host-order RGB, 4 bytes/px). Wrong default:

| Format | Bytes/px | 1080p frame | @60 fps |
|---|---|---|---|
| RV32 (RGB) | 4.0 | 8.29 MB | 498 MB/s |
| **I420 (YUV 4:2:0)** | **1.5** | **3.11 MB** | **187 MB/s** |

**2.67× less traffic**, and I420 is what the decoder natively produces — requesting RV32 forces a CPU colour-space conversion on every frame before we even see it.

> **Byte-order gotcha (cost a bug):** libVLC's `RV32` is **not** BGRA. It is host-byte-order RGB — on little-endian x86 the bytes land as R, G, B, X. The QImage over that buffer must therefore be `Format_RGBX8888`; creating it as `Format_RGB32` (which reads B, G, R) swaps red and blue on every frame. The same trap catches `Format_BGRA8888`. See `engine/surface.py:_update_packed`.

YUV→RGB happens in a **fragment shader**, free on the GPU. Three single-channel textures, one BT.709 matrix multiply, ~20 lines of GLSL through `qsb`.

Subtitles survive: VLC blends ASS/SSA/PGS into the picture *before* the lock callback, so styled subs arrive already composited into the Y/U/V planes.

RV32 stays as a one-line fallback for odd hardware.

### 0.5 Managing Cost A — hardware decode

`vmem` disables GPU decode. Honest numbers, modern 6–8 core desktop CPU:

| Content | CPU | Verdict |
|---|---|---|
| 1080p H.264 | 8–15% | Effortless |
| 1080p HEVC 10-bit | 15–25% | Effortless |
| 1440p | 25–40% | Comfortable |
| 4K HEVC 10-bit 60fps | 60–90% | Tight |
| 4K AV1 | 80–100%+ | Struggles |

Three mitigations:

1. **`--avcodec-threads=0`** — every core. Default for the Soft callback path.
2. **Local video modes (§V)** — the visible Settings dropdown selects `Auto`, `Soft`, or `Turbo`. `Auto` resolves demanding Local media (for example, 3840×2160 at 60 FPS) to Turbo and ordinary Local media to Soft. Forced Turbo uses `set_hwnd()` + `--avcodec-hw=d3d11va`, but the native child is embedded in the single Halcyon window with `QWindow.fromWinId()` + `WindowContainer`; a dedicated transparent QML child-window overlay retains the controls/panels layer. M3U is always Soft and Web has no VLC path. Any Turbo setup, embedding, resize, or playback failure falls back to Soft without stopping playback.
3. **libVLC 4 path** — a future GPU-to-GPU output route, not a requirement for this feature. **Not usable today** — as of mid-2026 VLC 4.0 is still unreleased, VideoLAN still ships 3.0.x, and the first public beta on pre-release libVLC 4 only reached iOS in June 2026. Keep the current Soft/Turbo boundary isolated so a later libVLC 4 path remains replaceable.

### 0.5.1 Final Settings policy — Local video modes (12 August 2026)

This is the accepted policy for the next implementation pass. It supersedes the earlier Turbo checkbox, docked-bar trade-off, and technical backend-selector wording. It is a documentation decision only; this update does not implement code, create a commit, or push a branch.

| Active mode | Visible Settings control | Effective output |
|---|---|---|
| **Local** | Enabled dropdown labelled **Video mode**, with **Auto**, **Soft**, and **Turbo**; default **Auto** | `Auto` chooses Soft for ordinary Local media and Turbo for demanding media such as **3840×2160 at 60 FPS**. A forced choice is respected when it can be used. |
| **M3U** | The same dropdown remains visible, displays **Soft**, and is **disabled** | Always the existing Soft callback/I420 path, including the RV32 fallback where needed. Turbo is not switchable for M3U. |
| **Web** | Video mode is **completely disabled** and has no effect | Web remains unchanged: it has no VLC/Turbo path and does not drive the media player. |

The dropdown is a real select control, not radio buttons or icon buttons. Its background, text, selected item, and disabled-state colours must remain readable by using clearly contrasting colours; do not rely on a single low-contrast glass tint.

The internal setting is `playback.videoMode = "auto"`. `playback.turboMode` and the technical `video.backend` choices are legacy compatibility inputs at most (they may be migrated or ignored), and neither appears in normal Settings. There is one VLC engine/player: Turbo is native VLC/GPU output embedded inside the main Halcyon window, never a second background player or an outside video window.

**Soft/Turbo boundaries:** Soft retains the current callback/I420 path, QML blur, and I420/RV32 fallback behaviour. Turbo wraps the native VLC child HWND with `QWindow.fromWinId()` and Qt 6.8+ `WindowContainer`; controls and panels that need to appear above the native pixels live in a transparent QML child-window overlay. Ordinary QML `MultiEffect` blur still applies to Soft scene-graph pixels, not automatically to the separate native HWND surface.

**Failure boundary:** Turbo setup, HWND embedding, resize/reparenting, or playback failure must tear down the failed native route and continue the same media in Soft. The user must not lose playback merely because Turbo could not be initialised.

### 0.6 Verification gate

**Write no UI until this passes.** ~150-line throwaway script:

- 1080p H.264 through the Soft I420 callback path
- A `Rectangle`, 60% opacity, `MultiEffect` blur, rounded corners, sitting **over** the video
- An animated element crossing the video at a steady 60 fps

**Pass:** sustained 60 fps, CPU < 25%, no tearing, glass visibly blending with moving video, no flicker on resize.

Pass and everything after is ordinary application code. Fail and you know in a day, not month three.

---

# PHASE 1 — Local Mode

> **Ship target:** `v0.1.0-local` · **Estimate:** 15–18 working days
> **This is the biggest phase by far** — it carries the entire shared foundation plus the richest mode. Phases 2 and 3 are small by comparison. That front-loading is deliberate and correct.

## P1.1 Scope

**In:** frameless glass shell, title bar, mode registry, panel dock, Soft callback video, Local video-mode policy, full transport bar, OSD, local playlist, tracks/subtitles, equalizer, resume, lyrics, metadata, settings, hotkeys, packaging.

**Out:** M3U anything, web anything, PiP, mobile remote. The title bar shows only a `Local` chip — the mode switcher renders from the registry, so it grows on its own in later phases with no edit here.

## P1.2 Foundation built here (frozen after sign-off)

| Component | File | Why shared |
|---|---|---|
| Video pipeline | `engine/video_out.py`, `engine/surface.py` | All modes render video |
| VLC engine | `engine/vlc_engine.py` | All modes play media |
| Mode registry | `core/mode_api.py`, `core/modes.py` | The extension point |
| Actions singleton | `ui/Actions.qml` | §4.1 enforcement |
| Shell + title bar | `ui/shell/` | One window |
| Panel dock | `ui/shell/PanelHost.qml` | One slot, N panels |
| Transport **parts** | `ui/transport/` | Shared controls; each mode arranges its own bar (§B.4) |
| Stage host | `ui/shell/Stage.qml` | Hosts video *or* web content per `ModeSpec.stage_qml` |
| Design tokens | `ui/Theme.qml` | Visual consistency |
| Settings | `core/settings.py` | One store |

## P1.3 Structure

```
halcyon/
├── main.py
├── engine/
│   ├── vlc_engine.py          # lifecycle, playback, tracks, EQ
│   ├── video_out.py           # ★ Soft callback ring buffer (§0.3)
│   ├── surface.py             # ★ VideoSurface(QQuickItem) + QSG node
│   └── equalizer.py
├── core/
│   ├── mode_api.py            # ★ ModeSpec — the contract (§A.2)
│   ├── modes.py               # ★ registry; later phases append one line
│   ├── settings.py
│   ├── library.py             # recent + resume
│   ├── metadata.py
│   └── lyrics.py
├── modes/
│   └── local/
│       ├── __init__.py        # ModeSpec for "local"
│       ├── playlist.py        # queue model
│       ├── LocalPanel.qml     # left dock panel
│       └── LocalTransport.qml # ★ two-row bar, arranged for Local (§B.4)
├── ui/
│   ├── Main.qml
│   ├── Actions.qml            # ★ singleton (§4.1)
│   ├── Theme.qml              # ★ design tokens
│   ├── shell/
│   │   ├── Shell.qml          # frameless, 8 resize handles
│   │   ├── TitleBar.qml       # mode chips from registry + gear
│   │   ├── PanelHost.qml      # ★ single left slot
│   │   └── Stage.qml          # VideoSurface + OSD + idle art
│   ├── transport/             # ★ shared PARTS, not a fixed bar (§B.4)
│   │   ├── SeekBar.qml
│   │   ├── VolumeControl.qml
│   │   ├── TimeDisplay.qml
│   │   ├── TrackPopover.qml   # ⚙ speed / audio / subs
│   │   └── TransportScrim.qml
│   ├── panels/InfoPanel.qml   # right dock: info / lyrics / EQ
│   ├── overlay/Osd.qml        # ★ §6.2
│   ├── components/            # GlassPanel, IconButton, Menu…
│   └── shaders/yuv420p.frag(.qsb)
├── tools/check_isolation.py   # ★ §A.5
├── assets/
├── vendor/vlc/
└── config/                    # → %APPDATA%\Halcyon at runtime
```

Runtime config lives **only** in `%APPDATA%\Halcyon`. Repo `config/` holds first-run defaults, copied once.

## P1.4 UI architecture

### The Single-Placement Rule *(hard rule)*

> **Every action exists in exactly one place. If a second context needs it, that context invokes the *same* component — it does not draw its own copy.**

- **"Add Files" appears once** — Local panel toolbar. Not in a menu bar, not on the empty stage, not in the transport bar. The empty-stage prompt and `Ctrl+O` *call the same handler*.
- **Playback actions live only in the mode's transport bar**, built from shared `ui/transport/` parts. Not playlist rows, not the OSD, not the title bar. Each control is *implemented* once (§B.4); only its arrangement is per-mode.
- **Mode switching lives only in the title bar. Settings live only behind the gear.**

**Enforcement:** every action is a named entry in `ui/Actions.qml`. Components bind `Actions.addFiles`, `Actions.playPause`. Two components *binding* one action is correct; two *implementing* it is a bug. Review question: *"is this the only place it can be triggered from, or the only place it's implemented?"* — the second is required.

| Action | The one home |
|---|---|
| Add files / add folder | Local panel toolbar |
| Clear playlist / clear selected | Local panel toolbar |
| All playback controls | Transport bar |
| Audio track / subtitle select | Transport bar → ⚙ popover |
| Equalizer | Right panel, EQ tab |
| Repeat / shuffle | Transport bar |
| Mode switch | Title bar |
| Settings, Video mode (Auto / Soft / Turbo) | Title bar → gear; Local-enabled, M3U-disabled Soft, Web-disabled |
| Fullscreen | Transport bar (double-click stage and `F` bind to the same action) |

### Window anatomy

```
┌────────────────────────────────────────────────────────────────┐
│ ◆ Halcyon   [ Local ]                          ⚙  ─  □  ✕      │  TitleBar 44px
├──────────────┬─────────────────────────────────┬───────────────┤
│              │                                 │               │
│  PanelHost   │           Stage                 │  InfoPanel    │
│  (left 300)  │   video + OSD overlay           │  (right 320)  │
│              │                                 │  collapsible  │
│  LocalPanel  │                                 │               │
│              │                                 │  Info         │
│  ┌────────┐  │                                 │  Lyrics       │
│  │+File   │  │                                 │  Equalizer    │
│  │+Folder │  │                                 │               │
│  │⌫ Sel   │  │                                 │               │
│  │✕ All   │  │                                 │               │
│  └────────┘  │                                 │               │
│   queue…     ├─────────────────────────────────┤               │
│              │        TransportBar             │               │
│              │   (floats over video, 72px)     │               │
└──────────────┴─────────────────────────────────┴───────────────┘
```

Only one mode chip renders in Phase 1 — the switcher is registry-driven, so Phase 2 adds a chip without touching `TitleBar.qml`.

**Local Turbo window layering:** Soft uses the Stage scene graph shown above. When the effective Local video mode is Turbo, the VLC child HWND is wrapped as a `QWindow` and placed with Qt 6.8+ `WindowContainer` inside the same Stage bounds. A dedicated transparent QML child-window overlay hosts the transport, OSD, panels, and other controls that must sit above that native surface. This is still one Halcyon window and one VLC player; it is not a second background player or an outside video window. M3U never selects this route, and Web never creates it.

**Auto-hide:** playing + pointer still 2.5 s → transport and cursor fade (180 ms). Any movement/keypress restores instantly. Never hides while a popover is open, while scrubbing, or while paused.

## P1.5 Local mode detail

**Left panel toolbar** — the only place these four exist:

| Button | Behaviour |
|---|---|
| **Add Files** | Multi-select dialog, appends to queue |
| **Add Folder** | Recursive scan, media extensions only, appends |
| **Clear Selected** | Removes highlighted rows; enabled only with a selection |
| **Clear Playlist** | Empties queue; confirm if >1 item |

**Body:** index, title, duration, now-playing indicator, drag-to-reorder, double-click to play, `Delete` = Clear Selected. Explorer drag-and-drop anywhere in the window appends here — the *same* handler Add Files calls, not a second path.

**Right panel:** Info · Lyrics · Equalizer.

### Transport bar — YouTube-style

```
┌──────────────────────────────────────────────────────────────┐
│ ●━━━━━━━━━━━━━━━━━━━━━○·································    │  ← seek bar
│                                                              │
│  ▶  ⏹  ⏮  ⏪  ⏩  ⏭   🔊━━━━━      12:34 / 45:67            │
│                                    ⚙  🔁  🔀  ⛶              │
└──────────────────────────────────────────────────────────────┘
```

`modes/local/LocalTransport.qml` — **two rows, ~72px**, assembled from shared `ui/transport/` parts.

- Seek bar **above** the button row, full width, 4px at rest → **6px with knob on hover**
- Buffered region in lighter grey behind played region
- Hover timestamp tooltip; frame thumbnail deferred to v1.1
- Scrub-drag seeks live, snaps on release
- Volume icon-only at rest, **slider expands rightward on hover**
- **Time display click toggles** elapsed/total ↔ remaining — *one* click target, two states, not two widgets
- Gradient scrim for legibility over bright video
- Icons only, tooltips on hover, 220 ms `OutCubic`, 40×40 hit targets, glass hover ring
- **⚙ popover** groups speed, audio track, subtitle track, subtitle delay

### OSD — Local media feedback and M3U transport feedback

Transient overlay drawn above the video: in Soft it is a scene-graph item over the callback texture; in Turbo it is hosted by the dedicated transparent QML child-window overlay described in §0.5.1. The native HWND is never treated as an ordinary QML texture.

| Trigger | Shows |
|---|---|
| Volume change | Speaker glyph + level bar + % |
| Mute toggle | Muted / Unmuted glyph |
| Seek | ⏪/⏩ 10s + new position / duration |
| Play / Pause | Large centre glyph, quick fade |
| Speed change | `1.25×` |
| Audio switch | `Audio: English (AC3 5.1)` |
| Subtitle switch | `Subtitle: English` / `Subtitles Off` |
| Fullscreen | Enter/exit glyph |
| File open | Filename + resolution + duration, 3 s |
| Resume | `Resuming from 24:31` |

Top-left for status lines, centre for large glyphs. Glass pill, 8px blur, 800 ms hold + 250 ms fade. Repeats reset the timer rather than stacking. Never covers the subtitle safe area (bottom 20%). Suppressed while a menu or panel has focus.

### Features

**Equalizer** — `libvlc_audio_equalizer_*`, 10 bands (31 Hz–16 kHz), ±20 dB, preamp, ~18 built-in presets + user presets in `eq.json`. Right panel. Live. *Applies to any libVLC playback, so it works in M3U too (Phase 2) — same component, reached the same way, not a copy.* *(v3.3 note: still technically true, but superseded — the owner decided M3U has no right panel, so the EQ is not offered in M3U; see §P2.4.)*

**Video adjust** — `libvlc_video_set_adjust_*`: contrast, brightness, hue, saturation, gamma. 8 presets. Right panel, below EQ.

**Subtitles** — native ASS/SSA/SRT/SUB/PGS/VobSub, embedded + external. `add_slave()`, auto-load matching filenames. Delay ±, scale, encoding. Selected in ⚙, announced by OSD.

**Audio tracks** — enumerate and switch live, remembered per file, announced by OSD.

**Resume** — saved every 5 s and on close; prompt if >30 s in and >5% remaining. `recent.json`, capped 200.

**Lyrics** — sidecar `.lrc` (timed, auto-scroll) + embedded tags. Right panel.

**Window** — frameless, custom title bar, 8 resize handles, snap, double-click maximise, drag-to-move, remembered geometry.

**Hotkeys** — `Space` · `←/→` ±10 s · `Shift+←/→` ±60 s · `↑/↓` volume · `M` · `F` · `S` subs cycle · `A` audio cycle · `[`/`]` speed · `L` repeat · `Ctrl+E` EQ · `Ctrl+O` · `Ctrl+L`/`Ctrl+I` panels · `Esc`. Every binding invokes an `Actions` entry.

## P1.6 Milestones

| # | Milestone | Deliverable | Est. |
|---|---|---|---|
| **1.0** | **Compositing spike (§0.6)** | **Glass over live 1080p, 60 fps** | **1–2 d** |
| 1.1 | Engine core | `vlc_engine.py`: play/pause/seek/volume/state/events | 2 d |
| 1.2 | Shell + foundation | Frameless window, resize handles, `Theme`, `Actions`, `ModeSpec`, registry, `PanelHost`, isolation guard | 3 d |
| 1.3 | Transport | Shared `ui/transport/` parts + `LocalTransport.qml`, seek bar, volume, time toggle, auto-hide | 3 d |
| 1.4 | OSD | All triggers, timing, safe areas | 1 d |
| 1.5 | Local panel | Playlist model, 4-button toolbar, drag-drop, reorder | 2–3 d |
| 1.6 | Tracks & subs | ⚙ popover, delay, external load | 2 d |
| 1.7 | Equalizer + adjust | 10-band UI, presets, video adjust | 2 d |
| 1.8 | Library & polish | Resume, recent, lyrics, metadata, settings, animation pass | 2 d |
| 1.9 | Package | Nuitka build, bundled VLC, installer, icon | 2 d |

**15–18 days.** Milestone 1.0 gates everything; 1.2 gates §4.1 compliance.

## P1.7 Acceptance test — Phase 1

Tick every box before Phase 2 begins.

**Compositing (the whole reason for §0)**
- [x] Glass transport bar renders **over** playing video, blur visible
- [x] No flicker, tearing, or black flash on resize / maximise / fullscreen
- [x] 1080p H.264 sustains 60 fps under 25% CPU
- [x] Panels slide over video without artefacts

**Formats** — MKV · MP4 · AVI · MOV · WMV · TS · FLV · WebM · HEVC 10-bit · MP3 · FLAC · AAC · Opus
- [x] All play without external codecs installed

**Transport** — every control in the P1.5 layout works
- [x] Play, pause, stop, prev, next
- [x] Seek ±10 s, scrubber drag, click-to-seek
- [x] Volume slider, mute, both OSD-reported
- [x] Time display toggles elapsed ↔ remaining on click
- [x] Fullscreen via button, `F`, and double-click — all identical
- [x] Repeat off/one/all; shuffle
- [x] Speed 0.5×–2×

**OSD** — all 10 triggers fire, correct position, 800+250 ms timing, repeats reset, never covers subtitles

**Playlist** — Add Files · Add Folder · Clear Selected · Clear Playlist · drag-reorder · double-click play · `Delete` key · Explorer drop

**Tracks & subs** — multi-audio switch · embedded subs · external `.srt`/`.ass` · auto-load sidecar · delay adjust

**Equalizer** — 10 bands live · presets · preamp · persists across restart

**Library** — resume prompt · recent list · lyrics scroll · metadata + art

**Window** — all 8 resize handles · drag-move · double-click maximise · geometry remembered

**Isolation** — `tools/check_isolation.py` passes · no `modes/m3u` or `modes/web` references exist anywhere

**Stability** — 2-hour playback, no leak · 50 rapid track changes, no crash · close during playback is clean

---

# PHASE 2 — M3U Mode

> **Ship target:** `v0.2.0-m3u` · **Estimate:** 5–6 working days
> **Additive only. No Phase 1 file is edited** except one line appended to `core/modes.py`.

## P2.1 Scope

**In:** `modes/m3u/` — parser, channel model, panel, reduced control profile, PiP window.
**Out:** everything else. No changes to Local behaviour whatsoever.

## P2.2 What gets added

```
modes/m3u/
├── __init__.py            # ModeSpec for "m3u"
├── parser.py              # .m3u / .m3u8, #EXTINF, tvg-* attributes (+ remote fetch, stdlib only)
├── playlist.py            # channel model
├── sources.py             # ★ saved-sources store — max 7, owned by M3U alone (§P2.4, v3.2)
├── M3UPanel.qml           # left dock panel
├── M3USourcesDialog.qml   # ★ the playlists manager (§P2.4, v3.2)
└── M3UTransport.qml       # ★ single-row bar, arranged for seven controls (§B.4, v3.3)
ui/overlay/PipWindow.qml   # new shared component (Phase 2 owns it)
```

```python
# core/modes.py — registry integration
REGISTRY = [local.SPEC, m3u.SPEC]   # ← one word added
```

## P2.3 Mode spec

```python
SPEC = ModeSpec(
    id="m3u", title="M3U",
    panel_qml="qrc:/modes/m3u/M3UPanel.qml",
    transport_qml="qrc:/modes/m3u/M3UTransport.qml",
    osd_enabled=True,         # transport feedback, controlled by the global OSD setting
    right_dock_enabled=False, # M3U still has no Info/Lyrics/Equalizer dock
    media_keys_enabled=True,  # space/volume stay useful; seek keys no-op on live
    uses_player=True,
    setup=build_m3u_context,  # exposes the channel model to QML as modeContext_m3u
)
```

**Video output policy:** M3U always uses the existing Soft callback/I420 path (with the RV32 fallback where required). It never switches the shared VLC engine to Turbo, even if a legacy or Local preference says Turbo. The Settings dropdown remains visible as `Soft` and disabled while M3U is active.

> **Correction (v3.2):** earlier drafts showed a `controls=[...]` field on `ModeSpec`. The shipped, frozen `core/mode_api.py` has no such field — §B.4 replaced the idea: a mode ships *its own transport QML*, and the shell never filters control lists. The mechanism below is the law; the field was the mistake.

**Seven controls, one row: prev · play/pause · stop · next · volume+mute · PiP · fullscreen.** *(Seven, no more, no fewer — stop added and the volume pair retained by owner decision, 2026-08-02.)*

Volume was missing from earlier drafts — an oversight, corrected before Phase 1 sign-off. Without it, changing volume in M3U would have meant reaching for the Windows mixer, which is unacceptable for a player.

Per §B.2, `M3UTransport.qml` arranges these seven in a **single-row layout designed for seven** — roughly 52px tall, balanced and centred, built from the same `ui/transport/` component vocabulary. It is *not* Local's two-row bar with the seek row deleted and gaps left behind. There is **no seek bar, no time display, no repeat/shuffle, no subtitle/audio menu** — absent, not greyed. The buffering indicator and the retry affordance live in this mode's own files — a flaky IPTV stream must never add special cases to shared code (§A.3). The `setup` hook means `main.py` does not gain a single line: it calls each registered mode's `setup` and publishes the result (§A.2).

**One-tuner rule (owner decision, v3.4):** Local and M3U share one engine, and one engine plays one thing. Switching the chip **stops whatever is playing** — there is never background audio. Entering M3U stops Local playback: the playlist and the position are preserved, and coming back, Local's ordinary resume prompt returns you to where you left. Leaving M3U stops the stream: the channel list and the last channel stay highlighted, and nothing auto-plays on entry — playback only ever starts from a click. The one-tuner behaviour itself is enforced from M3U's own `setup` hook; v3.5's separate generic capability split is the documented shared exception. (Want the channel in the corner while you do something else? That is exactly what PiP is for, §P2.5.)

**Right dock in M3U:** none (§P2.4). The shell implements this generically through a dedicated `right_dock_enabled` mode flag, separate from `osd_enabled`: M3U can show lightweight transport feedback while Ctrl+I and the Info/Lyrics/Equalizer dock stay absent. Web can make the same independent choice later.

## P2.4 Panel

**Toolbar — exactly two buttons:**

| Button | Behaviour |
|---|---|
| **Playlists…** | Opens the Playlists manager (below) — the one home for every way a source enters M3U |
| **Clear Playlist** | Empties the channel list; confirm if >1 item |

> **Owner decision, 2026-08-02 — replaces the earlier "title-bar Open action" idea.** `TitleBar.qml` is frozen at Phase 1 sign-off, and the owner wants source management inside the mode: insert a stream URL *or* load a locally saved `.m3u`/`.m3u8`, with up to **seven saved sources** and add/edit/delete. Everything below lives in `modes/m3u/` — the additive rule (§A.3) is untouched, and nothing appears in the title bar.

### The Playlists manager — one dialog, one home (§4.1)

A glass dialog (the same dialog pattern as Settings and the subtitle downloader — same look, same motion) listing **up to 7 saved sources**. Each source is a **name + either a remote URL or a local `.m3u`/`.m3u8` file**.

- **Add URL…** — name + URL form (the "insert M3U URL" path)
- **Add File…** — file picker for a `.m3u` / `.m3u8` on disk
- **Edit / Delete** — act on the selected row; delete asks for confirmation
- **Cap of 7:** at seven, the Add buttons disable with the hint *"Remove one to add another"* — never a silent cap
- **Click a source row → it loads**, its channels fill the panel, the dialog closes
- ★ **Loading a source stops the current stream.** The playing channel is not in the new list, so it must not keep streaming (owner decision, 2026-08-02)
- **The panel's empty state** opens this same dialog — reached two ways, implemented once (§4.1)
- **Dropping an `.m3u`/`.m3u8` onto the M3U panel** opens it through the *same* handler Add File calls — a bind, not a second implementation (§4.1). It is not auto-saved to the seven; saving is a choice made inside the dialog.

**Store:** `sources.json` under `%APPDATA%\Halcyon`, owned by `modes/m3u/` alone (§A.1 — deleting the mode deletes its store, nothing else notices). The **last-used source reloads automatically** when M3U is opened.

**Fetch:** remote playlists are downloaded over HTTP(S) with the **standard library only — no new dependency**, parsed once, cached for the session. Failure → the panel shows *"Couldn't reach this playlist"* with **Retry**; a local file that has moved shows *"File not found"* with edit/remove. Never a crash, never a silent empty list — and the handling lives in M3U's own files, not in shared code.

**Source indicator:** the current source's name sits above the channel list as **plain text** — information, not a second trigger.

**Body:** parsed `#EXTINF` entries — channel name, `group-title`, `tvg-logo` thumbnail when present (loaded async, cached, graceful fallback). Filter box narrows the list. **Grouping selector: By category (`group-title`, default) / By country (`tvg-country`, missing → "Unknown") / No group — the choice is remembered.** Single-click to play. No reorder (the file defines the order). **The playing channel always shows:** highlighted, and the list scrolls to keep it visible when zapping with prev/next.

**Right panel:** **none in M3U** (owner decision, 2026-08-02). Ctrl+I is inert here; the equalizer stays Local-only and is simply not offered. Local's right dock is untouched — this changes nothing for Local.

**Transport toast:** on (owner decision, 2026-08-03). The shared toast gives feedback for Play/Pause, Next/Previous (using the channel's parsed name), volume, mute and fullscreen. It follows the global OSD setting; this does not enable the right panel.

> **On seeking:** M3U entries are frequently live streams where seeking is meaningless, hence no seek bar. If you later want scrubbing for VOD-heavy playlists, build a seek row into `M3UTransport.qml` from the shared `SeekBar` part — the vocabulary already supports it (§B.4).

## P2.5 Picture-in-Picture

Always-on-top borderless window, default 480×270, resizable, corner-snapping, bound to **the same ring buffer** as the main Stage (§0.3) — no second decode, no second player, ~0 extra CPU. Main window can minimise while PiP plays. Double-click to restore.

**Why M3U only:** PiP suits background channel-watching. Local mode is foreground viewing with a full control surface. Adding it to Local later is one word in the Local profile.

## P2.6 Acceptance test — Phase 2

**Regression first**
- [ ] **Entire §P1.7 checklist re-run and passing**
- [ ] Deleting `modes/m3u/` still leaves a working Local build
- [ ] `git diff phase-1..phase-2` touches no Phase 1 file except the one `core/modes.py` line
- [ ] `tools/check_isolation.py` passes

**M3U**
- [ ] Loads `.m3u` and `.m3u8`, local and remote entries
- [ ] Remote playlists load over HTTP(S) — standard library only, no new dependency
- [ ] `#EXTINF` name, `group-title`, `tvg-logo` parsed and shown
- [ ] HLS streams play
- [ ] Filter box narrows the list
- [ ] **Grouping selector: By category (default) / By country / No group — remembered**
- [ ] **Playing channel stays highlighted and scrolled into view**
- [ ] Toolbar holds exactly two buttons — **Playlists…** and **Clear Playlist** — and both work
- [ ] Malformed / unreachable entries fail gracefully with a message, no crash

**Playlists manager (owner decision, §P2.4)**
- [ ] Up to 7 saved sources; at 7, Add disables with the hint — never a silent cap
- [ ] Add by URL and add by local file both work; edit and delete work; delete confirms
- [ ] Clicking a source loads it **and stops the current stream**
- [ ] Last-used source reloads automatically when entering M3U
- [ ] Current source name shows above the channel list — as text, not a second trigger
- [ ] Dead URL → clear message + Retry; moved local file → message + edit/remove
- [ ] Dropping an `.m3u` on the panel opens it via the same handler as Add File (§4.1)

**Controls**
- [ ] **Exactly seven controls render, one row:** prev · play/pause · stop · next · volume+mute · PiP · fullscreen
- [ ] **No seek bar, no time display, no repeat/shuffle, no subtitle/audio menu** — absent, not greyed
- [ ] Volume slider and mute both work; volume persists across a mode switch
- [ ] **Transport toasts fire in M3U:** Play/Pause, Next/Previous with channel name, volume, mute and fullscreen; global OSD setting still suppresses them
- [ ] **No right panel in M3U — Ctrl+I does nothing; EQ not offered**
- [ ] M3U bar is its own layout — single row, correctly balanced, **no empty gaps where Local's controls would be** (§B.2)

**PiP**
- [ ] Opens, stays on top, resizes, snaps to corners
- [ ] Main window minimises while PiP keeps playing
- [ ] CPU rise vs non-PiP is negligible (confirms shared buffer)
- [ ] Double-click restores

**Mode switching**
- [ ] Both chips render in the title bar
- [ ] Local ↔ M3U swaps panel and control set correctly
- [ ] Local playlist survives a round-trip to M3U and back
- [ ] The two playlists never contaminate each other
- [ ] **One-tuner rule:** entering M3U stops Local; leaving M3U stops the stream — never background audio
- [ ] Back in Local, the resume prompt returns you to where you left; back in M3U, list + last channel intact, nothing auto-plays

---

# PHASE 3 — Web Mode

> **Ship target:** `v1.0.0` · **Estimate:** 5–6 working days
> **Additive only.** Web is a real browser **inside the main window** on Windows' built-in **Edge WebView2**, reached **directly via pythonnet** (Route A, owner decision, 4 Aug 2026) — no Qt WebView, no QtWebEngine, nothing bundled (§P3.2).

## P3.1 Scope — the final design (owner decision, 4 Aug 2026)

**In:** `modes/web/` — a full browser: **tabs row**, **address bar**, **bookmarks (quick star + dropdown + manager tab)** and page content on the Edge WebView2 engine, all inside the Halcyon window under the same glass shell.
**Out:** anything outside `modes/web/` — plus, by explicit owner decision: no media controls, no media panels, no OSD, no PiP, no left bookmark drawer.

**Layout, top to bottom:**

1. **Halcyon title bar** — unchanged, frozen.
2. **Tabs row** — on entering Web there is **no page tab, only the + button**. Typing a URL/search in the address bar creates the first tab. **Maximum 15 tabs**; at the cap the **+ button greys out** and any further open attempt shows the plain-text message *"Maximum 15 tabs reached."* inside the tabs row. Tabs **survive switching Web → Local/M3U → Web** within a session (the stage is parked — §P3.3). Tabs are **never saved after app restart** — Web opens empty.
3. **Address bar** — **icon-only buttons**: Back · Forward · Reload/Stop · Home · bookmark star · bookmarks/menu icon. Plus the **text URL/search field** (a URL, or a search — non-URL input goes to the search engine).
4. **Page content** — the WebView2 page, filling the rest of the stage **below** all of Halcyon's chrome.

**New windows / popups:** a website's popup/new-window requests open as a **new Halcyon tab** (15-cap applies). **No outside browser window ever appears.**

**Bookmarks**
- **Quick star** — empty = current page is not bookmarked → click opens the **Add bookmark** popup. Filled = already bookmarked → click opens **Edit / Remove / Cancel**.
- **Dropdown** — Edge-style, from the top browser bar (menu icon). Opens on click; closes on clicking the same icon again, clicking outside, or `Esc`. Rows are **text**: title + URL.
- **Manage Bookmarks** — pinned at the top of the dropdown; opens a **Bookmarks Manager** as an **internal tab**: add manual (fields **title** + **URL**), edit, delete, reorder, search. Bookmarks are **saved permanently**.
- **No left bookmark drawer** — Web mode has **no dock panel at all** (§P3.3).

**No media controls, by design (§P3.4):** no play/pause, no seek bar, no volume, no subtitles/audio menu, no repeat/shuffle, no PiP from Halcyon. No equalizer, no right Info/Lyrics/EQ panel, no media OSD. Website videos (YouTube etc.) use **their own** controls — Halcyon never draws over them.

**Visual contract:** every button is Halcyon's `IconButton` — same glass, same theme, same title bar, same app feeling. *Web mode feels like a browser inside Halcyon.*

## P3.2 Engine — direct Edge WebView2 via pythonnet (Route A)

**Owner decision (4 Aug 2026): Route A confirmed.** Halcyon talks to Windows' **built-in Edge WebView2 directly through pythonnet** — the approach already proven in the owner's Smart Player. No Qt WebView, no QtWebEngine, no bundling, no download.

**Why not Qt WebView:** Qt's own Windows backend (`qtwebview/src/plugins/windows/qwebview2webview.cpp`) **blocks every new-window request** — its code says *"FIXME actually handle new windows when QWebView has the API for them"* — and the module exposes **no popup signal at all**. The rule *"popups open as new Halcyon tabs"* is impossible there. Direct WebView2 exposes `add_NewWindowRequested`, so popups become tabs — and we also get user-agent control, downloads, certificate handling and **one shared engine for all tabs** (Qt WebView would spin up a separate browser process per tab).

**What "direct" means mechanically:**
- **`pythonnet`** (a normal pip package) loads the WebView2 SDK's managed connector **`Microsoft.Web.WebView2.Core.dll`** (788 KB) plus its native companion **`WebView2Loader.dll`** (win-x64) — both vendored in `vendor/webview2/` (**already present on the owner's machine, 4 Aug 2026**; a one-time manual copy from the official NuGet package; not pip-installable; **not committed to git**, fetched locally like `vendor/vlc/`). They are a **bridge, not a browser**: the actual engine is the **WebView2 Runtime already built into Windows** (the same engine as Edge; ships with Windows 11, preinstalled on eligible Windows 10).
- At first use the app **initialises COM** and creates **one shared `CoreWebView2Environment`** — user-data folder **`%LOCALAPPDATA%\Halcyon\webview2_data`** (cookies, cache, profile) — one browser engine for every tab, exactly how Edge itself runs.
- **Each tab is a child window**: a `QWindow` (its HWND) + `CreateCoreWebView2Controller` bound to it. The page fills the stage area **below** Halcyon's chrome. This is the same child-HWND trick Qt's own backend uses — nothing new to invent, and it fits the QML shell: only the page is a native window.
- **User agent** = current desktop Edge string with "WebView2" stripped, and `navigator.webdriver` hidden — the same login-friendly / anti-bot behaviour as Smart Player (a website can't tell it's an embedded view).

**Finding the installed WebView2 (startup check):**
- **Registry:** `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` proves the runtime is installed.
- **Import test:** `CreateCoreWebView2Environment` succeeds → the engine actually loads.
- If either fails (rare — enterprise-managed machines) the **stage shows "WebView2 is not available"** — a clear message, no crash, no blank page. **Never bundle, never download** (owner decision).

**The native-surface rule (same physics as §0.1):** the page is a native child window, and QML cannot paint on top of native child windows. This design **complies by construction**:

- Title bar, tabs row and address bar sit **above** the web area, never over it — Halcyon draws them in its own QML strip. This is why the **⋮ (three-dot) bookmarks dropdown works**: the button lives in Halcyon's address bar, above the page, so Halcyon opens its own dropdown there with no conflict.
- The **⋮ bookmarks dropdown** and the **★ bookmark popup** are **Halcyon-owned frameless popup windows** anchored to the address bar (the one documented exception to "no second window"). They are app chrome, not website windows, and they float above the page like any menu.
- App messages (e.g. the 15-tab limit) render as **plain text inside the tabs row** — a small glass pill — never over the page. (No toast in Web mode — owner decision.)
- Website fullscreen (HTML5 video) is handled by the WebView2 engine itself — the page's own fullscreen, not a Halcyon window.

**Setup notes for the build:**
- COM initialisation and pythonnet wiring happen **before any WebView is created** — a one-line disclosed v4.0 `main.py` change if required (changelogged + regression-tested, §A.3 rule 1).
- The connector DLL must be discoverable at runtime (vendored path added at startup; Nuitka includes it in M3.5).
- No graphics-backend conflict: the app keeps its Direct3D 11 scene graph; the web page is a native child window beside it, not a scene-graph texture.

## P3.3 What gets added

```
modes/web/
├── __init__.py              # ModeSpec for "web"
├── webview2_runtime.py      # ★ detection (registry + import) + shared CoreWebView2Environment
├── webview2_host.py         # ★ per-tab host: child HWND + CoreWebView2Controller, events, popups
├── browser.py               # ★ BrowserContext: tab model (≤15), navigation, popups → tabs,
│                            #   chrome messages — exposed to QML
├── bookmarks.py             # bookmark store — JSON under %APPDATA%\Halcyon, permanent
├── WebStage.qml             # ★ the whole browser: TabsRow + AddressBar + page area
├── TabsRow.qml              # tab strip + "+" (no tabs on entry)
├── AddressBar.qml           # icon-only nav buttons + text URL/search field
├── BookmarksDropdown.qml    # Edge-style menu (frameless popup window, §P3.2)
└── BookmarksManagerTab.qml  # internal tab: add/edit/delete/reorder/search

vendor/webview2/                 # present locally (owner, 4 Aug 2026) — not committed
├── Microsoft.Web.WebView2.Core.dll   # 788 KB managed connector (WebView2 SDK)
└── WebView2Loader.dll                # native loader (win-x64) — finds the OS-installed runtime
```

```python
SPEC = ModeSpec(
    id="web", title="Web",
    panel_qml="qrc:/modes/web/WebPanel.qml",    # placeholder — never shown (§P3.1)
    stage_qml="qrc:/modes/web/WebStage.qml",    # the whole browser
    transport_qml="",                           # no bottom bar — the frozen docstring
                                                # already anticipates this (§B.4)
    osd_enabled=False,          # no media OSD; only in-chrome messages like the 15-tab limit (§P3.4)
    right_dock_enabled=False,   # no Info/Lyrics/EQ dock
    media_keys_enabled=False,   # Space scrolls the page — hotkeys inert
    uses_player=False,          # Web does not drive libVLC
    panel_enabled=False,        # ★ v4.0 capability — no left dock in Web
    keep_stage_alive=True,      # ★ v4.0 capability — stage parked on switch
    setup=build_web_context,    # publishes BrowserContext as modeContext_web
)
```

`stage_qml` was declared in Phase 1 (defaulting to the video surface) precisely so Phase 3 stays additive — that still holds; Web overrides it with the whole browser.

**Two owner-approved generic capability changes (v4.0, §A.3 rule 1 — same class as v3.5's `right_dock_enabled` split; both changelogged and covered by regression tests):**

1. **`panel_enabled: bool = True`** on `ModeSpec`, gating the left dock. Web sets `False`: the dock hides, `Ctrl+L` is inert, and the browser gets the full window width. `panel_qml` stays mandatory — the placeholder satisfies validation and is never loaded.
2. **`keep_stage_alive: bool = False`** on `ModeSpec`, gating `Stage.qml`. Web sets `True`: switching away **parks** the stage component (hidden, not destroyed) and switching back restores it — which is what makes *"tabs stay while switching Web → Local/M3U → Web"* literally true: the pages are still loaded, scrolled where you left them. No other mode opts in.

**Video engine:** `uses_player=False`, on top of the one-tuner machinery, means switching to Web **stops and releases** whatever VLC was playing; switching back to Local/M3U behaves exactly as before. Deleting `modes/web/` must leave Local + M3U perfect (§A.2 mechanical test).

## P3.4 Browser chrome — tabs, address bar, no media controls

**The address bar is not a transport bar** (§B.4's shared vocabulary, but its own job). It sits at the top of the stage, built from the same `IconButton` parts:

- **Back · Forward · Reload/Stop · Home** — navigation only. Reload becomes **Stop** while a page loads (that is the only "progress" indicator — the owner's icon-only rule leaves no room for a separate progress bar). **Home** navigates the active tab to the **home page of the currently loaded site**; on a blank tab (or with no tab) it opens **Google** (google.com) — owner decision, 4 Aug 2026.
- **Bookmark star** and **bookmarks/menu icon** — §P3.5.
- **URL/search field** — plain text field: shows the active tab's URL, selects all on focus, `Enter` navigates; non-URL input goes to the search engine (default **Google** — owner decision, 4 Aug 2026). No autocomplete in v1.0.
- The active tab's page title is reflected in the window title.

**Tabs row:**
- Entering Web mode: **no tabs, only the + button**; typing in the address bar creates the first tab.
- **+** creates a new (empty) tab and focuses the URL field.
- Each tab shows the page title (falling back to the URL) with a close **×**; the active tab is highlighted.
- **Maximum 15 tabs.** At 15 the + button disables and any further open attempt (+, a site popup) shows *"Maximum 15 tabs reached."* as a small glass pill **inside the tabs row** — the row is chrome, not page (§P3.2) — sliding in over the tabs and fading after a few seconds or as soon as a tab closes. No toast, nothing over the page. (Owner decision, 4 Aug 2026.)
- **Persistence:** tabs (order, URLs, titles, active tab — and, thanks to `keep_stage_alive`, the live pages themselves) survive Web → Local/M3U → Web. **Nothing is saved on exit**: restarting Halcyon opens Web empty, as decided.

**New windows / popups:** a site's `window.open` / `target=_blank` request arrives at WebView2's `add_NewWindowRequested`; Halcyon routes it to a **new tab** (subject to the 15-cap; at the cap it is blocked with the in-chrome message). **No outside browser window ever appears** — this is exactly why we use direct WebView2 instead of Qt WebView (Route A, §P3.2).

**No media controls, by design:** no play/pause, no seek, no volume, no track/subtitle menu, no repeat/shuffle, no PiP. No media OSD (`osd_enabled=False`). Media hotkeys inert (`media_keys_enabled=False`) — `Space` scrolls the page, seek keys do nothing. The page owns its playback UI; Halcyon never draws over it.

## P3.5 Bookmarks — quick star, dropdown, manager tab

**Store:** `modes/web/bookmarks.py` — `bookmarks.json` under `%APPDATA%\Halcyon`, **permanent** (survives restart; only the user or the app deletes entries). Owned by Web alone (§A.1 — deleting the mode deletes its store, nothing else notices). *(The browser's own profile — cookies, cache, history — lives separately in `%LOCALAPPDATA%\Halcyon\webview2_data`, §P3.2.)*

**Blank start:** the store is created **completely empty — no default bookmarks** (owner decision, 4 Aug 2026).

**Quick star** (address bar):
- **Empty star** = the current page is not bookmarked → click opens the **Add bookmark** popup (title prefilled from the page, URL fixed).
- **Filled star** = already bookmarked → click opens **Edit / Remove / Cancel**.
- The star's state follows the active tab's URL as you navigate.

**Dropdown** (menu icon) — Edge-style, anchored under the button:
- **Opens** on the menu icon. **Closes** on: clicking the same icon again, clicking outside, or `Esc`.
- **Manage Bookmarks** pinned at the top.
- Rows are **text** (title + URL); clicking a row navigates the active tab. Other chrome controls remain icon-style (§B.1). Empty state: *"No bookmarks yet — use ★ to save this page."*

**Bookmarks Manager — an internal tab** (a Halcyon tab, not a website):
- **Add manual** bookmark: fields **title** + **URL**.
- **Edit** (title/URL) · **Delete** (with confirm) · **Reorder** (drag) · **Search** (filters as you type).
- Everything persists immediately to the store.

**No left bookmark drawer.** The one dock slot hosts only Local's queue and M3U's channels; Web uses the dropdown + manager tab (owner decision, 4 Aug 2026).

## P3.6 Acceptance test — Phase 3

**Regression first**
- [ ] **§P1.7 and §P2.6 both re-run and passing**
- [ ] Deleting `modes/web/` leaves Local + M3U fully working
- [ ] No Phase 1 or Phase 2 file edited except the one `core/modes.py` line and the **disclosed v4.0 changes** (see `PHASE3_DISCLOSED` in `tools/check_isolation.py`): `panel_enabled` + `keep_stage_alive` in `core/mode_api.py`, the shell's dock/stage gating in `ui/Main.qml` / `ui/shell/Stage.qml`, the COM/pythonnet init line in `main.py` if required — each changelogged and covered by a regression test
- [ ] `tools/check_isolation.py` passes

**Engine & layout**
- [ ] ★ **Web renders INSIDE the main window — no second window appears anywhere** (page content included)
- [ ] It is the **Edge WebView2** engine (confirm via `navigator.userAgent` on a page), reached **directly via pythonnet + the vendored connector DLL** (Route A)
- [ ] **Startup detection:** runtime missing → the stage shows *"WebView2 is not available"* — no crash, no blank page
- [ ] Browser profile lives under `%LOCALAPPDATA%\Halcyon\webview2_data` (cookies persist)
- [ ] Layout top→bottom: Halcyon title bar · tabs row · address bar · page
- [ ] Frameless glass shell, title bar and theme correct around the browser; **no dock panel** in Web
- [ ] Pages scroll, links work, text input works; HTML5 video plays with the page's own controls

**Tabs**
- [ ] Entering Web shows **no tab, only +**; typing a URL/search creates the first tab
- [ ] + opens a new tab and focuses the URL field; close **×** works; active tab highlighted
- [ ] **Max 15 tabs; the 16th shows "Maximum 15 tabs reached."** as an in-chrome glass pill in the tabs row (greyed +; fades on its own or on closing a tab) — never over the page
- [ ] Tabs survive Web → Local/M3U → Web (order, URLs, titles, active tab; pages still loaded)
- [ ] **Tabs are not saved after restart** — Web opens empty

**Address bar**
- [ ] Back · Forward · Reload/Stop · Home all work
- [ ] URL field shows the current URL, selects all on focus, `Enter` navigates; non-URL text searches
- [ ] No transport bar, no seek bar, no volume — **absent, not greyed**

**Popups**
- [ ] A site's popup/new-window request opens as a **new Halcyon tab** (WebView2 `NewWindowRequested`); at 15 tabs it is blocked with the in-chrome message
- [ ] **No outside browser window appears for any site request**

**Bookmarks**
- [ ] ★ Empty star = not bookmarked → Add popup; filled star = bookmarked → Edit / Remove / Cancel; state follows navigation
- [ ] Dropdown opens on the menu icon; closes on same icon, outside click and `Esc`
- [ ] Dropdown rows show title + URL text; click navigates; **Manage Bookmarks** pinned on top
- [ ] Manager tab: add manual (title + URL), edit, delete (confirm), reorder, search — all persist
- [ ] Bookmarks survive restart; **no left drawer** anywhere in Web

**Controls & integration**
- [ ] No media OSD fires in Web; media hotkeys inert (`Space` scrolls)
- [ ] Switching away from Web returns cleanly; video engine released (one-tuner)
- [ ] All three chips render; switching in any order is stable
- [ ] Three separate lists — local queue, M3U channels, bookmarks — never cross-contaminate
- [ ] Settings, theme, window geometry consistent across all modes; clean shutdown from any mode
- [ ] Installer works on a clean Windows machine — no VLC, no Python, **no extra web runtime installed**

**→ Merge to `main`, tag `v1.0.0`. 🎉**

---

# POST v1.0 — Local Video Modes (Settings + Local-only Turbo)

> **Design locked:** 12 August 2026 · **Implementation status:** built 12 August 2026 (see §V.6 for what is verified and what is not).
> **Scope:** one Settings control and one effective-output policy for Local/M3U/Web. This section supersedes all earlier Turbo checkbox, docked-bar, and `video.backend` wording.

## V.1 Settings surface — one visible dropdown

The normal Settings dialog contains one real select control labelled **Video mode**. It is a dropdown, not radio buttons or icon buttons.

- **Local:** the dropdown is visible and enabled. Choices are **Auto**, **Soft**, and **Turbo**; the default is **Auto**.
- **M3U:** the same dropdown remains visible, visibly displays **Soft**, and is disabled. It is informational only: M3U always uses the existing Soft callback/I420 path and cannot switch to Turbo.
- **Web:** Video mode is completely disabled and has no effect. Web otherwise remains unchanged and has no VLC/Turbo playback path.
- The dropdown's background and text, including selected and disabled states, must have clearly contrasting readable colours. Do not substitute a low-contrast glass tint, radio group, or icon-only selector.

The new internal setting is `playback.videoMode`, defaulting to `"auto"`. The old `playback.turboMode` checkbox and technical `video.backend` dropdown/choices are removed from normal Settings. For existing profiles those keys may be migrated or ignored for compatibility, but they must not reappear as user-facing controls.

## V.2 Effective mode resolution

- `Auto` is evaluated only for Local media. It chooses **Turbo** for demanding content such as **3840×2160 at 60 FPS**, and chooses **Soft** for ordinary Local media where possible.
- Forced `Soft` keeps the current callback/I420 path, QML blur, and RV32 fallback behaviour.
- Forced `Turbo` uses the native VLC/GPU path, not the callback surface. There is still **one VLC engine/player**: no second background player, no second decoder, and no outside video window.
- M3U is always Soft regardless of the stored Local preference. Web does not resolve a video mode at all.
- **Audio-only media is always Soft, under every selection including a forced `Turbo`.** Turbo's purpose is to put decoded pixels in a native child window; a media with no video track has none, so Turbo would embed an empty HWND, move the chrome onto the overlay window and drop the QML blur — all cost, no benefit — while the album-art card belongs on the ordinary scene graph. The decision reads the app's existing "has video" answer, in this order: the controller's own `_video_tracks` list (the same source as the public `hasVideo` property), then `Metadata.hasVideo`/`hasAudio` from the container parse, then the file extension. An extension in `AUDIO_EXTENSIONS` is enough to say Soft before either async source reports, so an audio file is never briefly routed to Turbo.
- An *unknown* track list is deliberately **not** read as audio-only. Unknown is the normal state for the first instant of every open; forcing Soft there would make an explicit `Turbo` choice open on Soft and re-open on Turbo a moment later — a visible blip on every file. Unknown geometry still means Soft under `Auto`, because that is a genuine absence of evidence for Turbo; unknown *track presence* is merely "not yet".

## V.3 Turbo window and overlay boundary

Turbo gives libVLC the native child HWND and enables the D3D11 hardware-decode route. The child is wrapped with `QWindow.fromWinId()` and embedded with Qt 6.8+ `WindowContainer` inside the Stage bounds of the single Halcyon window. A dedicated transparent QML child-window overlay hosts the transport, OSD, controls, and panels that need to appear above the native pixels. Ordinary QML siblings cannot paint over the HWND, and ordinary QML `MultiEffect` blur does not automatically sample it; full scene-graph blur remains the Soft-path guarantee.

M3U never creates this native route. Web remains the existing WebView2 mode and never creates a VLC/Turbo surface.

## V.4 Failure and lifecycle rule

If Turbo setup, HWND wrapping/embedding, resize/reparenting, or native playback fails, the engine must fall back to Soft and continue the same media without stopping playback. Any partially-created native child is cleaned up before the Soft surface is restored. Switching modes still obeys the one-tuner rule; it never leaves a background Turbo player running.

## V.5 Acceptance — Local video modes

- [x] Local Settings shows an enabled `Video mode` dropdown with `Auto`, `Soft`, and `Turbo`; default is `Auto`. — *`ui/panels/SettingsDialog.qml`; asserted live against the real ComboBox in `tests/test_video_mode_ui.py`.*
- [x] `Auto` selects Turbo for demanding Local media and Soft for ordinary Local media; forced Soft/Turbo choices behave accordingly. — *`core/video_mode.py` + `AppController`; `tests/test_video_mode_policy.py`, `tests/test_video_mode_controller.py`.*
- [x] M3U keeps the dropdown visible as disabled `Soft` and always renders through the Soft callback/I420 path, including RV32 fallback where required. — *`ModeSpec.turbo_allowed=False`; the shared `VideoStage.qml` is untouched.*
- [x] Web leaves Video mode disabled and otherwise behaves exactly as before. — *`uses_player=False` gates `videoModeAvailable`; no file under `modes/web/` was changed.*
- [x] The old `playback.turboMode` checkbox and `video.backend` dropdown are absent from normal Settings. — *Both removed; a repo-wide check for the legacy key in QML is part of the test suite.*
- [x] Dropdown background/text/selected/disabled colours are readable and clearly contrasting. — *Opaque `Theme.baseElevated` surface, `Theme.text`/`Theme.textMuted` pair, explicit selected-row accent.*
- [x] Turbo stays inside the single Halcyon window/player via the native child + `WindowContainer` route; no outside video window or second player appears. — *One `media_player_new()`; the child `QWindow` is never shown before the container adopts it.*
- [x] A Turbo setup/embedding/resize/playback failure falls back to Soft without stopping playback. — *`VlcEngine._enter_turbo` / `turbo_failed`; the same MRL is re-opened at the captured position, silently.*
- [x] Soft QML blur remains intact; no native-HWND path is introduced for M3U or Web. — *`VideoStage.qml` unchanged; `chromeBlurSource` keeps the Stage as the backdrop whenever Turbo is not running.*
- [x] Audio-only media resolves to Soft under every selection, including a forced `Turbo`, and a real video file still reaches Turbo when its track list arrives late. — *`AppController._current_has_video()` feeds `resolve(has_video=...)`; `tests/test_video_mode_controller.py` covers explicit-Turbo audio, extension-only pre-parse, video→audio and audio→video skips, and route thrashing.*

## V.6 Verification status — what was and was not executed

**Executed** (Linux, PySide6 6.11.1, offscreen Qt): the full 627-test suite, `tools/check_isolation.py --phase 2`, a live load of `ui/Main.qml`, and a live Soft → Turbo → Soft round trip driving the real window — the `WindowContainer` adopts a real `QWindow`, the chrome layer moves into the transparent overlay window and returns to `body` with its geometry intact, and a provider that yields no window is reported and falls back.

**Not executed, and not claimed:** `libvlc_media_player_set_hwnd()` is a Win32 entry point and `--avcodec-hw=d3d11va` is a Windows decoder path. Neither can run on this machine. The Windows-specific behaviour — libVLC actually rendering into the child HWND, D3D11 hardware decode engaging, and the composited result appearing inside the Halcyon window — has been **written and reviewed against the documented APIs, never observed**. `engine.turbo_surface.is_supported()` returns `False` off Windows, so those platforms deterministically stay on Soft; the lifecycle tests use `HALCYON_TURBO_FORCE=1` with a fake player to exercise create → attach → tear-down, which proves the *ordering and cleanup*, not the native embedding. This needs one manual pass on Windows with a populated `vendor/vlc/`.


## V.7 Title-bar route badge

The dropdown records a *request*; the badge reports the *result*. Those differ
whenever Turbo cannot run — audio-only media, an unsupported system, a failed
attempt that fell back mid-playback (§V.4) — and without a read-out the user
has no way to tell a working Turbo from a silent Soft.

**The rule: the badge always names the route the playing media is actually on.**
A `Turbo` selection running on Soft reads `S`. Anything else would misreport the
single fact the badge exists to convey.

| Token | Meaning |
|---|---|
| `AT` | Auto chose Turbo |
| `AS` | Auto chose Soft |
| `T`  | Turbo, chosen explicitly |
| `S`  | Soft — chosen explicitly, or forced |

The `A` prefix discloses that *Auto* decided, the one case where the route is
not evident from Settings. It is dropped where Auto cannot apply: M3U shows a
disabled `Soft` (§V.2), so its badge is a plain `S`.

There is deliberately **no fifth "fell back" token and no warning tint**. Soft
is the correct, ordinary outcome for most media; colouring it as a fault would
train the user to ignore it. Turbo takes `Theme.accent`, Soft `Theme.textMuted`
— both already dark-mode aware, so no theme branch is needed.

**Where it appears:** Local and M3U, while media is loaded and not fullscreen —
left of the gear, in its own slot so the window buttons never shift. Not in Web
(no video route of its own) and not in Mini Mode (its own chrome).

**Hover gives the reason,** as a full sentence: "Auto → Soft — software (CPU)
video output; this media is not demanding", "Soft …; Turbo is not available on
this system", "Soft …; this media is audio only". Precedence runs
Mini → mode-forced → audio-only → unavailable/failed → Auto → explicit, so the
sentence names the condition that actually forced the route.

**It is a read-out, not a control.** No click target: Settings owns the setting,
and a second hidden entry point beside the window buttons would be both a
duplicate and a mis-click hazard. Both properties come from the controller
(`videoModeBadge`, `videoModeTooltip`) so QML never re-derives the route — one
decision site, `core/video_mode.py`, exactly as §V.1 requires.

---

# POST v1.0 — Mini Mode (v1.1) — Local Compact Bar

> **Ship target:** `v1.1.0-mini` · **Est:** 0.5–1 day · **Branch:** `phase-4-mini` (or `main` post-v1.0)
> **Not a 4th ModeSpec.** Mini is a shell state, like Fullscreen — a `miniModeActive` bool in `ui/Main.qml`. Only available in Local mode when media loaded.
> 
> **Owner decisions locked 7 Aug 2026:** height equals standard title bar (`Theme.titleBarHeight: 44px`) so it can sit on Word/Explorer title bar without excess space; width may increase to accommodate controls (400–420px). Draggable only via grip `⋮⋮`, not whole bar. No close from mini (must return to normal to quit). Auto-return to normal on playlist finished. No cursor auto-hide. Volume vertical pop-up. Seek bar zero-width idea loved — hairline top + circular ring.

## M.1 Why not a ModeSpec

| | |
|---|---|
| **ModeSpec** = channel with panel + stage + transport (Local/M3U/Web) | Mini has no panel, no stage, no transport — it IS the whole window |
| **Isolation test** §A.2 | Deleting `modes/mini/` must still work — but mini has no `modes/mini/` folder, it's `ui/shell/MiniBar.qml` |
| **Simplicity** | Boolean toggle, saves/restores normal geometry, no new registry entry |

## M.2 What gets added / touched (disclosed v4.1 shell change — post-foundation, owner-approved)

```
ui/shell/MiniBar.qml          # ★ fixed 400-420 × 44, glass, 8 controls + grip
ui/shell/TitleBar.qml         # ★ add mini toggle left of minimize [mini][─][□][✕] — bound to Actions.toggleMiniMode
ui/Actions.qml                # ★ new action toggleMiniMode
ui/Theme.qml                  # maybe miniBarWidth token, if needed — height reuses titleBarHeight
ui/Main.qml                   # ★ miniModeActive bool, show/hide chrome, fixed window size, always-on-top, save/restore geometry
core/settings.py              # miniBarPos + firstTime flag
```

Frozen Phase 1 files are touched, but documented as v4.1 post-v1.0 feature — same class as v4.0 `panel_enabled` capability, covered by regression tests.

## M.3 Layout — 44px height equals TitleBar

```
┌─────────────────────────────────────────────────────────────┐ 3px hairline seek = top edge of bar itself
│●━━━━━━━━━━━━━○··············································│ 2px rest → 6px + knob on hover, click/drag seek
├─────────────────────────────────────────────────────────────┤
│ ⋮⋮  ⏮  ⏪  ▶  ⏹  ⏭  ⏩  🔊  ⤢  │  44px = Theme.titleBarHeight
│ 24  40  40  44  40  40  40  40  40  │ grip only drags via startSystemMove()
└─────────────────────────────────────────────────────────────┘
        400-420px fixed, frameless, always-on-top
```

- **Grip `⋮⋮` (24px):** only draggable part, `MouseArea` with `startSystemMove()`, cursor `OpenHand`. Simple, no whole-bar drag conflict.
- **Prev track / Next track:** `Actions.prev` / `Actions.next` — same action as Local transport
- **Seek -10s / +10s:** `Actions.seekRelative(-10s)` / `(+10s)` — same actions as transport
- **Play/Pause (44px, slightly larger):** `Actions.playPause` — **circular progress ring** around it (0-100% fill) = glanceable progress without width
- **Stop:** `Actions.stop`
- **Volume/Mute:** mute icon, click = `Actions.toggleMute`. Hover → vertical `GlassPanel` slider 140px tall pops ABOVE bar (overlay, not expanding width). Same shared volume logic.
- **Return (⤢ expand):** `Actions.toggleMiniMode` — returns to normal geometry

All built from §B.1 vocabulary: `IconButton`, `Theme` tokens, `Actions` singleton — no new colours/radii/durations.

## M.4 Innovative seek without width increase — owner loved

**Zero extra width, zero extra height beyond 44px:**

1. **Top-edge hairline seek bar:** Top 3px of MiniBar IS the seek bar. Rest: 2px thin line, played = accent gradient, buffered = `trackBuffered`. Hover: thickens to 6px + knob + time tooltip, live scrub. Click/drag anywhere on top edge to seek — same code as `SeekBar.qml` but ultra-thin.
2. **Circular progress ring:** The border of the play button itself fills circularly with accent colour = current position. At a glance progress without looking at hairline.

Together they give precise seek + glanceable status with **0px width increase**, fitting the "sit on Word title bar" requirement.

## M.5 Behaviour

- **Activation:** TitleBar button left of minimize `[mini]`. Enabled only when `activeModeId == "local"` && `hasMedia` (duration>0 / state!=stopped). Grayed + disabled otherwise (M3U/Web/no media). Tooltip "Mini Mode". Bound to `Actions.toggleMiniMode`.
- **Deactivation:** Return button in mini bar, `Esc`, or close request (Alt+F4/taskbar X) → interpreted as return to normal, not quit. Only normal mode can quit.
- **Fixed size:** `minimumWidth == maximumWidth == 400-420px`, `minimumHeight == maximumHeight == 44px`. 8 resize handles hidden in mini state.
- **Always-on-top:** `flags: StayOnTopHint` in mini, normal otherwise. First time: `x = screen.x + screen.width/2 - miniWidth/2`, `y = screen.y + 12`. After drag, save `miniBarPos` to settings.
- **Video hidden:** Stage `visible: !miniModeActive` but **kept alive** (not destroyed) — reader refcount stays, ring buffer still fills, no texture upload while hidden to save GPU. Return = instant picture, no black flash (see Risks).
- **Auto-return:** When playlist naturally ends (no next, repeat off) while in mini, automatically call toggle → normal mode.
- **No auto-hide / cursor hide:** Mini bar never hides. User works in other windows leaving it playing.
- **No PiP conflict:** PiP only exists in M3U (§P2.5), Mini only in Local, so mutually exclusive by definition. One-tuner rule already stops M3U when switching to Local.
- **Fullscreen lockout:** Mini toggle disabled while `isFullscreen`.

## M.6 Risks & mitigations

| Risk | Mitigation — simplest |
|---|---|
| **Black flash on return** | Keep Stage alive hidden, not destroyed — same as Web `keep_stage_alive`. On return, latest frame already in ring. Skip `createTextureFromImage` while hidden to save. |
| **Geometry restore** | Save normal `x,y,w,h,wasMaximized,wasFullscreen` before entering mini. On return restore. If wasMaximized, call `showMaximized()` after. |
| **Turbo child while Mini is active** | Turbo uses a native child HWND — a hidden Stage would leave an orphan. While Mini is active, force the effective Local output to the existing Soft I420 path; on return, re-resolve the selected `Video mode` (`Auto` or `Turbo`) and fall back to Soft if native setup fails. Do not resurrect the old Turbo checkbox. |
| **Fixed-size frameless drag** | Only grip calls `startSystemMove()`, not whole bar — avoids accidental drags. Handles hidden. |
| **Close from mini** | Intercept `onClosing` in mini: `close.accepted=false; toggleMiniMode()` → returns to normal. Only normal mode `Qt.quit()`. |

## M.7 Acceptance — Mini Mode

- [ ] Toggle button renders left of minimize as `[mini][─][□][✕]`, only enabled in Local when media loaded, grayed in M3U/Web/no media
- [ ] Click toggle → window becomes fixed 400-420 × 44, frameless, always-on-top, top-center first time, glass matches Theme
- [ ] Bar shows grip ⋮⋮ + 8 controls: prev track · seek -10s · play/pause (with circular progress ring) · stop · next track · seek +10s · volume/mute + vertical pop-up · return — same `IconButton` vocabulary, no new colours/radii
- [ ] Only grip drags the window (`startSystemMove()`), buttons click normally, no accidental drag
- [ ] Top 3px hairline is seek bar: 2px rest, 6px + knob on hover, click/drag seeks, buffered behind played
- [ ] Play button circular ring shows progress 0-100% without extra width
- [ ] Volume: mute icon click toggles mute, hover pops vertical slider above bar (no width increase), controls live
- [ ] Seek -10s/+10s, prev/next, play/pause, stop all work via same `Actions` entries as Local transport (§4.1)
- [ ] Video hidden, audio continues, CPU not higher than normal (no texture upload while hidden)
- [ ] Return via return button / Esc / Alt+F4 → normal window restores at previous geometry, video instantly resumes with no black flash
- [ ] Playlist naturally finished while in mini → auto-return to normal
- [ ] No close from mini — taskbar close / Alt+F4 returns to normal, only normal can quit
- [ ] No auto-hide, no cursor hide in mini
- [ ] Works while sitting on Word/Explorer title bar (44px height matches, 400px width fits in free title bar space)
- [ ] No PiP conflict (PiP only M3U, Mini only Local), one-tuner rule intact
- [ ] `tools/check_isolation.py` still passes, all Phase 1-3 regression still passing

**→ Tag `v1.1.0-mini`**

---

# POST v1.0 — Mobile Remote (v1.2) — Android phone companion · §R

> **Status: COMPLETE — VERIFIED 2026-08-09 (owner), tag `v1.2.0-remote`.** Built 2026-08-08 (all nine steps + audit pass, §R.6). Spec locked and implemented same day by owner decision (overrides earlier "deferred until v1.0" gate). Player code paths untouched: remote is second doorway onto existing `AppController` actions (§4.1); every step landed with full regression + isolation green. CHECKLIST Phase R: **10/10 verified 2026-08-09**.
> Verified 2026-08-08 at lock time: **no remote code existed** — no server, no QR, no phone UI. `aiohttp`/`qrcode` were commented out in `requirements-dev-full.txt`; both are now active (Phase R build).
> 2026-08-09: owner confirmed full functional remote, QR <1s, real-time sync, drive browser, playlist pinned bottom 7 rows + autoscroll, subtitle download, M3U + PiP/Fullscreen, Web active page + universal media control, Power Sleep/Shutdown. **Marked complete, no push/commit per request.**

## R.1 Product decisions — owner, 2026-08-08 (lock these)

| # | Decision | Owner call |
|---|---|---|
| 1 | Phone side | **Web page in the phone's browser** — no install, no Play Store, no APK. Scan the QR → page opens in Chrome. |
| 2 | Server on PC | Tiny HTTP server inside the app. **On by default — starts as the last step of startup loading**, stops when the app closes. |
| 3 | Connecting | QR code in **PC Settings → Mobile Remote** section. Scanning it (or typing `http://<pc-ip>:8765`) is the *only* key. |
| 4 | PIN | **None — keep it simple.** The QR/URL is the door; same Wi-Fi only; never exposed to the internet. |
| 5 | Sync | Real-time; **PC is the source of truth**, the phone mirrors it — instant, never stale, no two realities. |
| 6 | Look | Stunning dark-glass mobile UI matching Halcyon's theme; thumb-friendly. |
| 7 | Versions | **One shot — full remote in a single build.** No v0.x remote. |
| 8 | Local playlist position | **Pinned to the bottom** of the Local screen; **max 7 rows visible, then autoscroll** (it can be long). |
| 9 | Lyrics on mobile | **Not required** — excluded (owner). |
| 10 | M3U Add source | **URL field only** — no drive browser for M3U sources (owner). |
| 11 | Web mode | **Active page only**; bookmarks + **universal media control** via WebView2 `ExecuteScriptAsync` on the active tab's controller. |
| 12 | Power | Collapsible **⚡ Power** section (every chip) → **Sleep** / **Shutdown** buttons that act on the PC. |
| 13 | PiP / Fullscreen | **PiP + Fullscreen buttons included on the M3U chip** remote transport. |
| 14 | Subtitle download | **Included on the Local chip** — search + language filter + results + download, same backend as the PC dialog. |

## R.2 Chip-wise control list (final)

### Common — top of every chip
- 3 chips `Local` · `M3U` · `Web` — tapping a chip switches the **PC's** mode too (same as clicking it on the PC)
- Now Playing bar (title + time) · connection dot (phone ↔ PC link alive)
- ⚡ Power (collapsed) pinned at the bottom

### 🎬 Local chip
1. **Transport** — Play/Pause · Stop · Next/Previous · seek bar + **±10 s** quick-jump · playback speed 0.5×–2×
2. **Volume** — slider + mute
3. **Files (drive browser)** — **all drives** (C:, D:, …) · navigate folders · media-only filter · **tap file = plays on PC** · add file/folder to playlist
4. **Playlist** — **pinned to the bottom, max 7 rows visible + autoscroll** · tap to play · reorder · remove · clear · shuffle · repeat (off/all/one)
5. **Tracks & subtitles** — audio track picker · subtitle track picker · **Download subtitles** · load subtitle file (reuses drive browser) · subtitle delay +/−
6. **Equalizer** — all sliders + presets, same as the PC
7. **Now playing** — album art, title, artist *(no lyrics — owner R.1#9)*

### 📺 M3U chip
1. **Transport** — prev channel · Play/Pause · next channel · Stop · seek bar (on-demand) · volume + mute
2. **Extras** — **🖼 PiP** · **⛶ Fullscreen** (both act on the PC)
3. **Sources** — list saved sources · **+ Add source = URL field only** (no drive browser — owner R.1#10) · edit / remove
4. **Channels** — grouped list (sports/movies/…) · tap channel = plays on PC · search/filter · expand/collapse groups · favourites filter
5. **Favourites** — star / unstar · favourites-only view

### 🌐 Web chip *(active page only — owner R.1#11)*
1. **Active page card** — title + URL of the page currently open on the PC
2. **Bookmarks** — list · tap = open in the active tab · add current page · remove
3. **Universal media control** (appears only when the page has a video) — Play/Pause · seek bar · time · volume/mute · fullscreen on PC. *(Known exception: paid DRM-streaming sites such as Netflix/Prime Video resist scripted control — status still shown, transport may not respond.)*

### ⚡ Power (global, every chip)
- Collapsed bar at the bottom → expands to two buttons: **Sleep** · **Shutdown** (acts on the PC)

### ❌ Not on the remote
- App Settings (the QR code lives *inside* PC Settings) · Mini Mode · window controls · OSD toasts · lyrics

## R.3 Interface layouts (locked)

### Screen 0 — Common shell (frame on every chip)
```
┌──────────────────────────────┐
│  ◉ HALCYON  ● Connected      │   header + status dot
├──────────────────────────────┤
│  [ LOCAL ] [ M3U ] [ WEB ]   │   chips — tap switches PC too
├──────────────────────────────┤
│ ▶▶ Now Playing      12:34    │   now playing bar
├──────────────────────────────┤
│                              │
│   (chip content — scrolls)   │
│                              │
├──────────────────────────────┤
│  ▸ ⚡ Power                   │   collapsed by default
└──────────────────────────────┘
```

### Screen 1 — 🎬 Local chip
```
┌──────────────────────────────┐
│  [ LOCAL ] [ M3U ] [ WEB ]   │
├──────────────────────────────┤
│  Now Playing           12:34 │
├──────────────────────────────┤
│  ── TRANSPORT ────────────── │
│  ⏮  ▶/⏸  ⏭   ⏹             │
│  ───────●────────  seek bar  │
│  -10s         +10s   [1.0×]  │
│  ── VOLUME ───────────────── │
│  🔇 ────●────────  🔊         │
│  ── FILES ────────────────── │
│  [ 📁 Browse Drives ]        │  → Screen 2
│  [ ➕ Add folder to playlist]│
│  ── TRACKS & SUBTITLES ──── │
│  Audio track:   [English ▾] │
│  Subtitles:     [Off     ▾] │
│  [ ⬇ Download Subtitles ]   │  → Screen 3
│  [ 📄 Load subtitle file ]  │
│  Subtitle delay:   -0.5s ▾  │
│  ── EQUALIZER ────────────── │
│  ▸ collapsed — sliders +     │
│     presets when expanded    │
│  ── NOW PLAYING ──────────── │
│  🖼 Album art   Title         │
│                Artist        │
├──────────────────────────────┤
│  ── PLAYLIST ────────────── │   pinned BOTTOM —
│  🔀 Shuffle   🔁 Repeat      │   7 rows max, then
│  Track 1  ▸  (current)       │   autoscroll
│  Track 2             ↕  ✕   │
│  ... (max 7 visible)         │
├──────────────────────────────┤
│  ▸ ⚡ Power                   │
└──────────────────────────────┘
```

### Screen 2 — 📁 Drive browser (from Local → Files)
```
┌──────────────────────────────┐
│  ◀ Back          Select file │
├──────────────────────────────┤
│  My PC ▸  This PC            │
│  ── DRIVES ───────────────── │
│  💽 C:  Windows              │
│  💽 D:  Movies               │
│  💽 E:  Backup               │
├──────────────────────────────┤
│  📁 Videos    📁 Music       │
│  ▶ Movie1.mkv        ▶  ▶ + │
│  ▶ Song2.mp3         ▶  ▶ + │
│  (only media files shown)    │
│  ▶ tap file = play on PC     │
│  + tap + = add to playlist   │
├──────────────────────────────┤
│        [ Play selected ]     │
└──────────────────────────────┘
```

### Screen 3 — ⬇ Subtitle download (from Local → Tracks & subtitles)
```
┌──────────────────────────────┐
│  ◀ Back         Subtitles    │
├──────────────────────────────┤
│  [ Search for subtitles… ]   │
│  [ 🔍 Search ]               │
│  ── LANGUAGE ─────────────── │
│  [EN][FR][ES][DE][+]         │
│  ── RESULTS ──────────────── │
│  Movie.2024.1080p  EN ⬇     │
│  Movie.2024.BluRay  FR ⬇    │
│  Status: ✔ Downloaded       │
├──────────────────────────────┤
│  ▸ ⚡ Power                   │
└──────────────────────────────┘
```

### Screen 4 — 📺 M3U chip
```
┌──────────────────────────────┐
│  [ LOCAL ] [ M3U ] [ WEB ]   │
├──────────────────────────────┤
│  Now Playing  ESPN HD  45:12│
├──────────────────────────────┤
│  ── TRANSPORT ────────────── │
│  ⏮◀ ▶/⏸ ▶⏭    ⏹            │
│  ────●────────  seek (VOD)   │
│  🔊 ──●──────  ── 🔇          │
│  ── EXTRAS ───────────────── │
│  [ 🖼 PiP ]  [ ⛶ Fullscreen ]│
│  ── SOURCES ──────────────── │
│  [ ➕ Add source ]            │   → name + URL field only
│  ▸ Sports Pack     (7 srcs)  │
│  ▸ News Mix        (URL)     │
│  ── CHANNELS ─────────────── │
│  [ 🔍 Search… ]  [★ filter]  │
│  ▾ SPORTS  (12)              │
│    ⭐ ESPN HD        ▶ ▶     │
│    ☆ Sky Sports      ▶ ▶     │
├──────────────────────────────┤
│  ▸ ⚡ Power                   │
└──────────────────────────────┘
```

### Screen 5 — 🌐 Web chip
```
┌──────────────────────────────┐
│  [ LOCAL ] [ M3U ] [ WEB ]   │
├──────────────────────────────┤
│  Now Playing   (web page)    │
├──────────────────────────────┤
│  ── ACTIVE PAGE ──────────── │
│  🌐 youtube.com/watch?v=…    │
│  "How to build a PC"         │
│  ── BOOKMARKS ────────────── │
│  [ ⭐ Add current page ]      │
│  ▸ YouTube            ✕      │   tap = opens in
│  ▸ GitHub             ✕      │   active tab on PC
│  ── MEDIA CONTROL ────────── │
│   (only when video detected) │
│  ▶/⏸                        │
│  ───────●────────  seek      │
│  4:32 / 12:05                │
│  🔊 ──●────  ── ⛶ Fullscreen │
├──────────────────────────────┤
│  ▸ ⚡ Power                   │
└──────────────────────────────┘
```

### Screen 6 — PC Settings: Mobile Remote section (QR)
```
┌──────────────────────────────┐
│  Mobile Remote               │
│   ┌──────────────┐           │
│   │  ░░▒▒▓▓▒▒░░  │           │   QR code
│   └──────────────┘           │
│  Scan with your phone camera │
│  (or open:                   │
│   http://192.168.1.5:8765)   │
│  ● Remote server: ON         │
└──────────────────────────────┘
```

## R.4 Technical notes (for the build phase)

- **Deps:** uncomment `aiohttp>=3.9`, `qrcode[pil]>=7.4` in `requirements-dev-full.txt`.
- **Server:** aiohttp on `0.0.0.0:8765`; starts at the end of `main()` bootstrap; stops on `aboutToQuit`.
- **§4.1 stays intact:** the remote is a new *doorway* onto the existing `Actions`/`AppController` — no action is re-implemented on the phone side.
- **Drive browser:** small new Python API (list drives → list folder → media-only filter) served over HTTP; forward slashes in paths (Windows gotcha); gated only by the QR/URL access.
- **Web media control:** reuse `WebViewHost.ExecuteScriptAsync` (already in `modes/web/webview2_host.py`), addressed to the **active tab only** via `BrowserContext.activeTabIndex`.
- **Subtitle download:** reuse the `core/subtitles.py` backend.
- **Power:** Sleep / Shutdown via OS command; release `core/power.py` `PowerGuard` before shutdown.
- **Real-time status:** WebSocket (or SSE) pushed PC → phone; phone sends commands, PC executes and confirms.

## R.5 Acceptance — Phase R (build-time)

Build tasks and verification boxes live in **CHECKLIST.md → PHASE R**. Sign-off = every box ticked; regression: Phases 1–3 still pass, `tools/check_isolation.py` passes.

## R.6 Build log (owner fixations — what was done, when)

Each step lands with: new tests green · full regression green · isolation green · no player code path modified.

| Date | Step | What landed | Status |
|---|---|---|---|
| 2026-08-08 | 1 — Server skeleton | `remote/` package (§R.4): aiohttp server on `0.0.0.0:<port>` (default 8765, ephemeral for tests), `/` + `/health` routes, dedicated daemon thread + own asyncio loop, **guarded start** (no aiohttp → app runs exactly as before, warning only), starts as **last** startup step in `main.py`, stops **first** in `on_quit()`. Settings `remote.enabled` / `remote.port` defaults. `aiohttp>=3.9` activated in `requirements-dev-full.txt`. `tools/check_isolation.py`: `PHASE_R_DISCLOSED` + `remote/` in dangling-ref scan. Tests: `tests/test_remote_server.py` (8). Baseline before: 331 passed — after: 339 passed, 0 failed. | ✅ landed |
| 2026-08-08 | 2 — QR + pairing | `remote/qr.py` (guarded qrcode → PNG bytes, `/qr.png` route), **Settings → Mobile Remote** section in `ui/panels/SettingsDialog.qml` (QR image + live URL via `RemoteBridge.serverUrl`), `qrcode[pil]>=7.4` activated. | ✅ landed |
| 2026-08-08 | 3 — Status channel | `remote/status.py` (thread-safe StatusStore) + `remote/bridge.py` poller (500 ms Qt-thread snapshot: player, now-playing, tracks, playlist, m3u, web, eq, subs) + `/api/status` + **SSE `/api/events`** (push on version change). PC is source of truth; server thread reads only plain dicts. | ✅ landed |
| 2026-08-08 | 4 — Command channel | `RemoteBridge.request()` emits a **`QueuedConnection` signal** → `_dispatch` runs on the Qt thread, mapping ~45 actions onto the *existing* `AppController`/engine/context methods (§4.1, no re-implementation). `POST /api/cmd`. Signals `toggleFullscreenRequested` (Main.qml → actionHost) and `togglePipRequested` (M3UTransport → `pipOpen`) for window PiP/fullscreen. | ✅ landed |
| 2026-08-08 | 5 — Common shell + chips | `remote/static/` phone web app (`index.html`/`style.css`/`app.js`): aurora-glass theme, header + connection dot, 3 chips that switch the PC's mode, Now Playing bar, ⚡ Power expander. Served at `/` + `/static/*`. | ✅ landed |
| 2026-08-08 | 6 — Local chip | Drive browser (`remote/drives.py` + `/api/drives` + `/api/browse`; all drives, media-only filter, forward slashes), transport/volume/±10 s/speed, tracks & subtitles incl. **subtitle download** (subs.search/download/languages), **playlist pinned bottom, 7 rows max + autoscroll**, equalizer (presets/preamp/bands/reset). | ✅ landed |
| 2026-08-08 | 7 — M3U chip | Sources (list/add-by-URL-only/remove/load), grouped channels (client-side expand, play by view row), search/filter, favourites (star + filter), PiP + Fullscreen buttons. | ✅ landed |
| 2026-08-08 | 8 — Web chip | Active-page card + bookmarks (list/add/remove/open-in-active-tab) via existing `BookmarksStore`; **universal media control**: `get_media_probe_script()` in `webview2_runtime.py`, `WebMessageReceived` → `mediaStatusChanged`, `WebViewHost.media_control()` (play/pause/toggle/seek/seekBy/volume/mute/fullscreen), `BrowserContext.mediaControl()`/`media_status()` on the **active tab only**. DRM sites documented as the exception. | ✅ landed |
| 2026-08-08 | 9 — Power + polish | ⚡ Power (collapsed) → Sleep / Shutdown via `remote/power.py` (injectable OS commands; `PowerGuard` untouched — app shutdown path already releases it). Full sweep: 27 new remote tests, **366 passed / 47 skipped, 0 failed**, isolation OK, `py_compile` OK, live end-to-end smoke test OK (UI + QR PNG + SSE + queued command). | ✅ landed |
| 2026-08-08 | **Audit pass** | Full end-to-end re-audit: (1) `RemoteBridge.stop()` added — status poller halted in `on_quit` before engine teardown; (2) phone UI fixes — M3U groups now key on the actual grouping mode (category/country/language) and remember expand/collapse across pushes, playlist autoscroll only on track change (no fighting user scroll), sliders not overwritten mid-drag, file **＋ add-to-playlist** and **"Add this folder"** buttons added per §R.2 spec; (3) dead code removed, server stop nulls its runner/site refs; (4) demo fakes `subs.languages` setter. Re-verified: **366 passed / 47 skipped / 0 failed**, isolation OK, syntax OK, `node --check` OK, live endpoints re-tested. | ✅ done |

---

# POST v1.0 — Vendor Update Tab · §U

> **Design locked 10 Aug 2026 (owner decisions).** Third tab in Settings → Update. Checks vendored VLC and WebView2 files against known latest versions. Does NOT check the Halcyon app version itself — only the two vendor dependencies the user downloaded manually.
>
> **Owner decisions locked 10 Aug 2026:**
> - Check VLC + WebView2 together at one click (Option B) — simple, no app version
> - Show extraction guide: after extracting the downloaded archive, tell user WHERE inside the extracted folder to find the files
> - Show place-at paths with 📁 "Open Folder" icon button (opens Windows Explorer at that location)
> - Download links as clickable URLs (shortened domain + ↗ external-link indicator)
> - "All up to date" state: ✓ summary with current versions, skip Halcyon version
> - Icon-based buttons only (↻ Check / ✕ Cancel)

## U.1 What gets added / touched

```
core/update_checker.py              # ★ Python backend — version detection, check logic, folder opening
ui/panels/SettingsDialog.qml        # ★ New inline component UpdateTabContent (3rd tab)
main.py                             # ★ Register UpdateChecker as QML context property
tools/check_isolation.py            # ★ Add PHASE_U_DISCLOSED for main.py (frozen-path exception)
```

No frozen Phase 1-3 files are touched except `SettingsDialog.qml` (which already has a tabbed layout designed to grow — adding a tab is a model entry + inline component) and `main.py` (one import, one instance, one context property — same pattern as every service; `main.py` is added to `PHASE_U_DISCLOSED` in `tools/check_isolation.py`).

## U.2 Python backend — `core/update_checker.py`

The `UpdateChecker(QObject)` class is exposed to QML as the `UpdateChecker` context property.

**Version detection (reads from disk, no HTTP):**
- VLC: reads `vendor/vlc/libvlc.dll` product version via PowerShell `VersionInfo.ProductVersion`
- WebView2: reads `vendor/webview2/Microsoft.Web.WebView2.Core.dll` file version, or falls back to parsing the `.nupkg` filename

**Known latest versions (hardcoded constants — updated when new releases ship):**
- `VLC_KNOWN_LATEST = "3.0.21"`
- `WEBVIEW2_KNOWN_LATEST = "1.0.2903"`

**Qt properties (read by QML):**
- `checking: bool` — true while a check is running
- `vlcCurrentVersion: str` — detected local VLC version
- `webview2CurrentVersion: str` — detected local WebView2 version
- `updateAvailable: QVariant` — dict `{vlc: {update, current, latest}, webview2: {...}}`
- `lastResult: QVariant` — full result dict including `anyUpdate` bool
- `vlcDownloadUrl / webview2DownloadUrl: str` — official download URLs (constant)
- `vlcFiles / webview2Files: QVariantList` — files to extract + where they sit after extraction
- `vlcPlacePaths / webview2PlacePaths: QVariantList` — destination folders + what goes in each
- `vlcExtractionGuide / webview2ExtractionGuide: str` — human-readable extraction instructions
- `appRootPath: str` — absolute path of the application root (for display)

**Qt slots (called from QML):**
- `checkUpdates()` — runs version detection + comparison, emits `checkStarted` then `checkFinished(result)`
- `openFolder(relativePath)` — opens `ROOT / relativePath` in Windows Explorer (`os.startfile`)
- `openVlcDownload()` — opens VLC download URL in default browser
- `openWebview2Download()` — opens WebView2 NuGet URL in default browser

## U.3 QML UI — Update tab in `SettingsDialog.qml`

**Tab bar:** Three tabs — `General | Shortcuts | Update`. Update uses `Glyphs.refresh` icon. Tab width 120px (same as existing tabs).

**Inline component `UpdateTabContent`:**
- State machine: `idle` → `checking` → `result`
- `Connections` block on `UpdateChecker` — `onCheckStarted` → state=checking; `onCheckFinished(result)` → updateResult=result, state=result

**Layout (top to bottom):**

```
┌─────────────────────────────────────────────┐
│ [↻ Check] [✕ Cancel]                        │  icon buttons, 40×40
├─────────────────────────────────────────────┤
│ (scrollable content — see states below)     │
└─────────────────────────────────────────────┘
```

**Button states:**
- **Check Update** (`Glyphs.refresh`): enabled when not checking. Accent background (`Theme.accent`), `textOnAccent` icon, no ring.
- **Cancel** (`Glyphs.cancel`): enabled only while checking. Dismisses to idle state.

**State: Idle**
- Description text: "Check if VLC and WebView2 have newer versions available."
- App root path (monospace, faint)

**State: Checking**
- Spinning `Glyphs.refresh` icon (rotation animation, `NumberAnimation on rotation`, 360° infinite loop, 1s duration)
- "Checking for updates…" text

**State: Result — All up to date**
- ✓ checkmark (`Glyphs.check`, `Theme.success`) + "All components are up to date" (bold)
- Version summary table:
  ```
  VLC         3.0.21    ✓
  WebView2    1.0.2903  ✓
  ```

**State: Result — Update available**
- "Update Available" header (bold, `Theme.warning` colour)
- Per-component sections (only shown when that component has an update):

  ```
  ── VLC Media Player ─────────────────────────
  Current: 3.0.20  →  Latest: 3.0.21

  🔗 download.videolan.org ↗   (clickable, opens browser)

  After extraction, these files are at the root of the extracted folder:
    • libvlc.dll          ← root of extracted folder
    • libvlccore.dll      ← root of extracted folder
    • plugins/ (folder)   ← root of extracted folder

  Place at:
    vendor\vlc             (libvlc.dll, libvlccore.dll)  [📁]
    vendor\vlc\plugins     (contents of the plugins/ folder)  [📁]

  ── WebView2 Runtime ─────────────────────────
  Current: 1.0.2800  →  Latest: 1.0.2903

  🔗 nuget.org ↗   (clickable, opens browser)

  Rename .nupkg to .zip, extract, then navigate to build\native\x64\:
    • Microsoft.Web.WebView2.Core.dll  ← build\native\x64\
    • WebView2Loader.dll               ← build\native\x64\

  Place at:
    vendor\webview2        (both DLLs)  [📁]
  ```

**📁 Open Folder buttons:** `IconButton` with `Glyphs.addFolder`, 28×28, tooltip "Open folder in Explorer". Calls `UpdateChecker.openFolder(path)`.

## U.4 Owner decisions (locked 10 Aug 2026)

| # | Decision | Rationale |
|---|---|---|
| 1 | Check VLC + WebView2 only — no app version | Simple, focused on the vendor files the user manages |
| 2 | One click checks both | No need for separate checks per component |
| 3 | Icon buttons only (↻ / ✕) | Consistent with Halcyon's IconButton vocabulary (§B.1) |
| 4 | Show extraction guide | User needs to know WHERE inside the extracted archive to find the files |
| 5 | 📁 Open Folder button per path | Opens Windows Explorer — far better UX than copy-pasting paths |
| 6 | Download links as shortened text + ↗ | Clean look; ↗ indicates external browser; full URL in tooltip |
| 7 | "All up to date" = ✓ + version summary | Clear confirmation; no app version clutter |
| 8 | Versions hardcoded as constants | No HTTP dependency for basic check; update constants when new releases ship |

## U.5 Acceptance — Phase U

- [ ] Third tab "Update" renders in Settings with `Glyphs.refresh` icon
- [ ] Tab bar shows three tabs: General | Shortcuts | Update — same style, same width
- [ ] ↻ Check button has accent background, ✕ Cancel button disabled when idle
- [ ] Clicking Check transitions to "Checking…" state with spinning refresh icon
- [ ] Check reads local VLC DLL version from `vendor/vlc/libvlc.dll`
- [ ] Check reads local WebView2 DLL version from `vendor/webview2/`
- [ ] If all up to date: shows ✓ "All components are up to date" + version summary table
- [ ] If update available: shows "Update Available" header + per-component sections
- [ ] Each component section shows: current version → latest version
- [ ] Each component section shows: clickable download link (opens browser)
- [ ] Each component section shows: extraction guide (where files are after extracting)
- [ ] Each component section shows: file list with location notes
- [ ] Each component section shows: place-at paths with 📁 Open Folder buttons
- [ ] 📁 Open Folder opens Windows Explorer at the correct absolute path
- [ ] Cancel button enabled only during checking; returns to idle
- [ ] Dialog dimensions adjusted for the new content (560×600)
- [ ] All Theme tokens used — no hardcoded colours, radii, or durations
- [ ] `core/update_checker.py` compiles cleanly
- [ ] `main.py` registers UpdateChecker as QML context property
- [ ] No Phase 1-3 frozen files modified except `SettingsDialog.qml` (tab model + inline component) and `main.py` (one import, one instance, one context property)

**→ Tag `v1.3.0-update`**

---

# POST v1.0 — Scrub Preview · §S

> **Design locked 13 Aug 2026 (owner decisions).** A still-frame preview that
> follows the pointer over the seek bar in Local mode: hover anywhere on the
> bar → a small floating window shows the video frame at that position; move
> the mouse away → it disappears. **Still image only** — no moving clip
> preview, nothing on pause. Owner decisions, locked 13 Aug 2026:
> - Still image only (snapshot frame). No clip preview while paused.
> - New Settings toggle **"Scrub preview"**, placed **directly below the
>   "On-screen display" toggle** in Settings → General.
> - Default **ON**.
> - Must work in **fullscreen** too (the bar auto-hides; preview rides along
>   whenever the bar is visible).
> - Local mode only (video files). Live streams / radio have no past frame to
>   preview; M3U and Web are untouched by design (§B.2).

## S.1 What gets added / touched

```
engine/scrub_preview.py          # ★ NEW — hidden second decoder (libVLC), snapshot pipeline
engine/vlc_engine.py             # ★ owns a ScrubPreview; feeds it on media change; shutdown
core/settings.py                 # ★ new default: "ui.scrubPreviewEnabled": True
ui/transport/SeekBar.qml         # ★ generic: exposes hoverFraction (-1..1) + hovering
ui/overlay/ScrubPreview.qml      # ★ NEW — the floating popup (image + time, glass style)
Halcyon/Overlay/qmldir           # ★ register ScrubPreview in the Halcyon.Overlay module
modes/local/LocalTransport.qml   # ★ arrangement: popup above the bar, wires Player.preview
ui/panels/SettingsDialog.qml     # ★ toggle row under "On-screen display"
ui/Main.qml                      # ★ bindTransport(): scrubPreviewEnabled from Settings
tools/check_isolation.py         # ★ PHASE_S_DISCLOSED for the frozen-path rule
tests/test_scrub_preview.py      # ★ NEW — settings default, decoder fakes, engine wiring
tests/test_scrub_preview_qml.py  # ★ NEW — GUI-gated: SeekBar hoverFraction, popup shown/time
```

Frozen Phase 1 paths touched (all disclosed in `PHASE_S_DISCLOSED`, same
mechanism as every phase since 2): `core/settings.py` (one default),
`engine/vlc_engine.py` (owns the helper + two call sites), `ui/transport/
SeekBar.qml` (two generic read-only properties — no behaviour change for
existing consumers: M3U does not use SeekBar, the tooltip is untouched).
`engine/scrub_preview.py` is a new file under the frozen `engine/` tree, hence
disclosed like `engine/turbo_surface.py` was. Everything else lives in
non-frozen paths (`ui/overlay/`, `modes/local/`, `ui/panels/`, `Halcyon/`).

## S.2 How it works

**The hidden decoder.** `ScrubPreview(QObject)` owns a *second*, headless
libVLC instance — `--vout=dummy` (frames are decoded but never drawn; libVLC's
`video_take_snapshot` still captures them), `--no-audio`, `--avcodec-hw=none`.
It is created eagerly with the engine but initialises libVLC **lazily** on the
first local file, so a broken libVLC never takes the main player down with it.
It is intentionally **not** a second `VlcEngine`: no vmem ring, no surface, no
poll timer — just play → pause at the first frame → seek → snapshot.

**Snapshot pipeline (all on the GUI thread, timer-driven):**

1. `set_source(mrl)` — called from the engine whenever media changes. Non-`file://`
   MRLs (live streams, network URLs) and audio-only files (no vout) mark the
   decoder *unavailable* and the popup stays hidden.
2. `request(ms)` — QML-facing slot called while the pointer is over the bar.
   Requests are **coalesced**: rapid mouse moves only update the latest pending
   position; one seek→settle→snapshot chain serves the newest value, so a fast
   sweep cannot queue up behind itself.
3. Seek the hidden player to `ms` → wait ~70 ms for the dummy vout to decode
   the target frame → `video_take_snapshot(0, path, 320, 0)` (width 320,
   height 0 = keep aspect). One retry if the first snapshot lands too early.
4. `MediaPlayerSnapshotTaken` → emit `snapshotReady(file://...)` → the popup's
   `Image` shows the frame. Snapshots rotate between two temp PNGs in
   `%TEMP%\halcyon-scrub\` so QML's image cache always sees a fresh URL.
   Temp files are removed at shutdown.

**The popup (`ui/overlay/ScrubPreview.qml`).** 160×90 still, rounded glass
border, mono time label at the bottom-right, opacity fade (`Theme.durFast`).
Pure display — it knows nothing about the player. LocalTransport positions it
above the bar, centred on the hover point and clamped to the window, and is
the *only* place that talks to `Player.preview` (the arrangement rule, §B.4).

**SeekBar stays generic.** It gains two read-only properties —
`hoverFraction` (0..1 under the pointer, `-1` when the pointer is away) and
`hovering` — driven by its existing hover/drag MouseAreas. The existing time
tooltip and every other consumer are unchanged. M3U never instantiates
SeekBar, so the feature is Local-only with zero mode knowledge in the shared
part (the same reason the bar has no preview inside it at all).

**Settings.** `ui.scrubPreviewEnabled` default `True`; toggle lives directly
under "On-screen display" in Settings → General; LocalTransport reads it via
the shell's `bindTransport()` (same binding pattern as every other bar flag).

**Fullscreen.** The bar and popup live inside the transport Loader; when the
chrome auto-hides in fullscreen, both fade out together and reappear on the
next pointer move — the preview can never float over a hidden bar.

## S.3 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Second decoder is extra CPU while hovering | Decoder plays only long enough to reach Playing, then **pauses**; a hover chain is ~1 seek + 1 snapshot. Idle cost ≈ 0. |
| Snapshot lags a fast sweep | Coalescing serves the newest position; intermediate frames are skipped, never queued. Best-effort by design — a stale frame for one frame-time is acceptable. |
| libVLC instance failure (missing binary, weird file) | Lazy init + every step wrapped: any failure marks the decoder unavailable and the popup simply never appears. The main player is never affected. |
| Two instances, one process | `vlc.Instance` objects are independent; `modes/local/playlist.py` already runs short-lived instances beside the main player. Teardown mirrors `VlcEngine.shutdown` (stop → settle → detach → release), §9 order. |
| Temp PNGs accumulate | Two rotating files, removed on shutdown (best effort). |
| Mini Mode / M3U / Web / Remote | Untouched. MiniBar has its own hairline seek (§M) and is out of scope; M3U/Web have no local seekable media; Remote mirrors the main transport's actions, which are unchanged. |

## S.4 Acceptance — Scrub Preview

- [ ] Hover over the Local seek bar → 160×90 still frame appears above the bar at the hovered position
- [ ] Moving the pointer along the bar updates the frame to the new position
- [ ] Moving the pointer away hides the popup
- [ ] Works while dragging (scrubbing) too
- [ ] Works in fullscreen whenever the bar is visible; never floats over a hidden bar
- [ ] Works for video files; never appears for audio files or live streams
- [ ] Playback of the main video is unaffected: no flicker, no jump, no stutter while hovering
- [ ] Toggle "Scrub preview" sits directly below "On-screen display" and defaults to ON
- [ ] Toggling OFF removes the preview immediately and hides the popup
- [ ] Popup is clamped to the window (never clipped off-screen at the left/right edges)
- [ ] All Theme tokens used — no hardcoded colours, radii, or durations
- [ ] `engine/scrub_preview.py` compiles clean; no module-level `import vlc`
- [ ] `tools/check_isolation.py` still passes with `PHASE_S_DISCLOSED` in place
- [ ] No Phase 1-3 frozen files modified except the four disclosed paths

**→ Tag `v1.4.0-scrub`**

---

## 7. Visual Design *(applies to all phases — set in Phase 1)*

**Aurora glass.** Deep charcoal base, slow-drifting aurora gradient, frosted panels floating above.

| Token | Value |
|---|---|
| Base | `#0B0E14` |
| Glass fill | `rgba(255,255,255,0.06)` |
| Glass border | `rgba(255,255,255,0.12)` 1px |
| Scrim (under transport) | vertical `rgba(0,0,0,0)` → `rgba(0,0,0,0.72)` |
| Blur | 32 panels · 48 modals · 8 OSD pill |
| Radius | 18 panels · 12 controls · 999 pills |
| Accent | `#5EEAD4` → `#A78BFA` |
| Played / buffered | accent gradient / `rgba(255,255,255,0.28)` |
| Type | Inter / Segoe UI Variable |
| Motion | 220 ms `OutCubic`; OSD 250 ms `OutQuad` |

- **Idle** — aurora + album art, slow Ken Burns, audio-reactive bars
- **Playing** — video full-bleed, chrome floating and auto-hiding
- **Fullscreen** — chrome slides out, slim progress hairline remains

All of it works *only because of §0.3*.

---

## 8. Deferred — post-v1.0

Deliberately excluded from all three phases to keep each shippable:

| Feature | Why deferred |
|---|---|
| **Mobile remote + QR** | Was Phase-scoped in v2.0; it's a whole second UI with its own server, and it must mirror each mode's control set — which doesn't stabilise until Phase 3. Building it earlier means building it twice. **Own phase after v1.0 — full spec locked in §R (v4.2, 8 Aug 2026); implementation started 8 Aug 2026 by owner decision (see §R.6).** |
| **Seek-bar frame thumbnails** | ~~Needs a second decoder instance; nice-to-have~~ — **built and shipped as PHASE S (v1.4.0-scrub, 13 Aug 2026, §S)**. Still-image hover preview over the Local seek bar via a hidden second decoder; on by default, toggle under "On-screen display". |
| Bookmark folders | v1 flat list is enough |
| Tab favicons | v1 flat list is enough; WebView2 exposes favicons (`FaviconChanged`) — easy post-v1.0 if wanted |
| "Play in Halcyon" from Web | Depends on per-site URL resolution |
| libVLC 4 GPU path | Blocked on upstream release (§0.5) |
| Chromecast / DLNA | Out of scope |

**Note:** the remote was in v2.0's build order at 3–4 days. Moving it out is why v3.0's total is shorter despite adding phase overhead. It isn't lost — it's sequenced correctly, and its **full spec now exists in §R** (v4.2) so nothing needs re-deciding when the build starts.

---

## 9. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| 4K60 software decode too heavy | Med | Local `Auto`/`Turbo` policy (§0.5.1/§V); demanding Local media may use native D3D11 output, while every failure falls back to Soft without stopping playback; libVLC 4 remains future work |
| ctypes callback GC'd mid-playback | **High** | **Hold hard references on a long-lived object.** Classic `python-vlc` segfault — a callback going out of scope crashes instantly. Bites in Milestone 1.0 |
| `stop()` race on close | Med | Stop → await `Stopped` event → release; never release from a Qt slot |
| GIL contention on callbacks | Med | Callbacks do *zero* pixel work — index swap only |
| **Foundation wrong, discovered in Phase 2** | **High** | **Registry + isolation guard from Milestone 1.2.** If Phase 2 needs a Phase 1 edit, stop and fix Phase 1 — don't patch around it |
| UI duplication creeping back | Med | `Actions` singleton + §4.1 review question |
| PiP window steals the ring buffer | Med | Buffer read-only to surfaces; refcount readers; main Stage never unbinds |
| Shader fails on old iGPU | Low | RV32 + `Format_RGBX8888` fallback (VLC RV32 is host-order RGB, **not** BGRA — see §0.4) |
| Nuitka misses VLC plugins | Med | Explicit `--include-data-dir`; set `VLC_PLUGIN_PATH` at startup |
| HiDPI fractional scaling blur | Low | `PassThrough` rounding, DPR-aware texture sizing |
| WebView2 overlay limit (native child window) | Med | The page is a native child HWND — QML cannot paint over it (§0.1 physics). All chrome lives above the web area; the ⋮/★ popups are Halcyon-owned frameless popup windows; app messages render as plain text in the tabs row (§P3.2/§P3.4). Design complies by construction |
| Turbo HWND embedding / resize failure | Med | Keep Turbo behind the effective-mode boundary; if `QWindow.fromWinId()` / `WindowContainer` setup, reparenting, resize, or native playback fails, clean up and continue the same media on Soft. M3U and Web never enter this path (§V.3–V.4) |
| Turbo overlay cannot receive ordinary scene-graph blur | Med | Host controls/panels in the dedicated transparent QML child-window overlay; keep full `MultiEffect` blur as a Soft-path guarantee rather than pretending it samples native HWND pixels (§V.3) |
| COM / pythonnet interop bugs | Med | Use the proven Smart Player recipe: one shared CoreWebView2Environment, hard-referenced event handlers, COM init per thread. Spike first in M3.1 (§P3.2) |
| WebView2 runtime missing (rare) | Low | Evergreen Runtime ships with Windows 11 and eligible Windows 10 (§P3.2). Startup registry + import check; if absent the stage shows "WebView2 is not available" — no crash, no bundling |
| pythonnet + Nuitka packaging | Low | Vendor the WebView2 SDK bridge files (Microsoft.Web.WebView2.Core.dll + WebView2Loader.dll win-x64) in vendor/webview2/ and make them discoverable in the frozen build. Verify in M3.5 (§10) |

---

## 10. Bundle & Licensing

**Size:** libvlc + libvlccore ≈ 8 MB; VLC plugins ≈ 55 MB; PySide6 core ≈ 45 MB; the web engine is **Edge WebView2 — OS-provided, nothing bundled** (v4.0, Route A). **Installer ≈ 110–145 MB** — the only additions are `pythonnet` (≈ 2 MB) and the **WebView2 SDK bridge files** (≈ 1.5 MB total: `Microsoft.Web.WebView2.Core.dll` 788 KB + `WebView2Loader.dll` win-x64 — bridge files, not a browser; vendored in `vendor/webview2/`). Dropping QtWebEngine's ~130 MB Chromium is the point of the owner's WebView2 decision (4 Aug 2026): the same official Edge engine, zero bundling, smaller installer. The Evergreen WebView2 Runtime ships with Windows 11 and has been installed on eligible Windows 10 machines; the app detects it at startup and shows a clear message if absent.

**Licensing:** libVLC is LGPL-2.1, plugins are mixed LGPL/GPL. For a **personal, non-distributed** player this is entirely unencumbered — those obligations attach to *distribution*, and there is none.

---

## 11. Requirement Coverage

| Requirement | Phase | Status |
|---|:---:|---|
| Frameless glass UI | 1 | ✅ |
| **No overlay / click-through bug** | 1 / V | ✅ Soft uses the scene graph; Turbo uses the dedicated child-window overlay boundary — ordinary QML is never expected to paint over a native HWND |
| **Local Video mode dropdown: Auto / Soft / Turbo** | V | ◻ **Design locked §V; implementation not started** |
| **Local Auto chooses Soft/Turbo; Turbo failure falls back to Soft** | V | ◻ **Design locked §V; implementation not started** |
| **M3U visible disabled Soft control + existing Soft callback/I420 path** | 2 / V | ◻ **Design locked §V; implementation not started** |
| **Web Video mode disabled; Web otherwise unchanged** | 3 / V | ◻ **Design locked §V; implementation not started** |
| **Legacy `playback.turboMode` and `video.backend` absent from normal Settings** | V | ◻ **Design locked §V; implementation not started** |
| Vast format support, no codec install | 1 | ✅ bundled libVLC |
| **OSD — Local + M3U transport feedback** | 1 / 2 | ✅ |
| **Local: play/pause/stop/prev/next** | 1 | ✅ |
| **Local: seek ±, seek bar** | 1 | ✅ |
| **Local: volume + mute** | 1 | ✅ |
| **Local: elapsed/remaining toggle** | 1 | ✅ one target, two states |
| **Local: media time, fullscreen** | 1 | ✅ |
| **YouTube-style controls** | 1 | ✅ |
| **Local playlist: add files/folder, clear selected/all** | 1 | ✅ |
| Equalizer, video adjust | 1 | ✅ |
| Embedded + external subtitles | 1 | ✅ |
| Multi audio tracks | 1 | ✅ |
| Resume, lyrics, metadata | 1 | ✅ |
| Repeat / shuffle | 1 | ✅ local only |
| Frameless + 8 handles | 1 | ✅ |
| **M3U: prev/play-pause/stop/next/volume/PiP/fullscreen** | 2 | ✅ seven controls, one row |
| **M3U: own bar layout, not Local's with gaps** | 2 | ✅ §B.2 |
| **M3U playlist: clear playlist only** | 2 | ✅ |
| M3U / M3U8 / HLS | 2 | ✅ |
| Picture-in-Picture | 2 | ✅ shared buffer |
| **Web: no media controls** | 3 | ✅ §P3.4 — tabs + address bar only |
| **Web embedded in main window** | 3 | ✅ §P3.2 — Edge WebView2 inside the window |
| **Web tabs (≤15) + bookmarks (star, menu, manager)** | 3 | ✅ §P3.4 / §P3.5 |
| **Web popups → new Halcyon tabs** | 3 | ✅ WebView2 `NewWindowRequested` → tab · §P3.4 |
| Web browsing | 3 | ✅ **Direct Edge WebView2 via pythonnet — built-in engine, embedded in main window** |
| **No duplicated actions** | all | ✅ §4.1 + `Actions` |
| **Separate playlists per mode** | all | ✅ one slot, three panels |
| **Modes independently testable** | all | ✅ §A + per-phase acceptance |
| **One machine, three channels** | all | ✅ §B — shared vocabulary, per-mode layout |
| **Mini Mode v1.1: Local compact bar 400×44, grip only drag, prev/seek ±10/play/stop/next/volume/mute/return, hairline top seek + circular play ring, vertical volume pop-up, always-on-top top-center, no close from mini, auto-return on finished** | 4 | ✅ §M — shell state not ModeSpec, 44px = TitleBar height |
| Mobile remote + QR | R (v1.2) | ✅ **COMPLETE — verified 2026-08-09, tag `v1.2.0-remote`** — §R, full remote: server on by default, QR in Settings, real-time sync, Local/M3U/Web chips, playlist pinned bottom 7 rows, drive browser all drives, subtitle download, PiP+Fullscreen, universal media control, Power Sleep/Shutdown |

**One conscious trade-off, bounded:** demanding Local media may need Turbo (§0.5.1/§V), but Turbo is Local-only, remains inside the single Halcyon window/player, and falls back to Soft without stopping playback. *The separate-window limitation from earlier drafts is resolved by the explicit child-window embedding boundary — see §V.3 and §P3.2.*

---

## 12. Getting started — Phase 1 only

```bash
git init halcyon && cd halcyon
git checkout -b phase-1-local

py -3.12 -m venv .venv && .venv\Scripts\activate
pip install PySide6 python-vlc
```

*(Phase 3 adds `pythonnet` — the bridge to Windows' built-in Edge WebView2 — plus the vendored WebView2 SDK bridge files (`Microsoft.Web.WebView2.Core.dll` + `WebView2Loader.dll`, §P3.2). `aiohttp`/`qrcode` not until the remote — see §R (spec locked v4.2). Install per phase — a smaller surface is easier to debug.)*

Then build **Milestone 1.0** and nothing else. Prove the glass sits over the video at 60 fps before writing a single line of application UI.

---

*Halcyon — every format, one pane of glass.*
