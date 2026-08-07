# Halcyon — Media Player Architecture & Build Plan

> **Halcyon** *(hal-see-on)* — "calm, golden, untroubled."
> A media player that plays *everything*, looks like liquid glass, and has no seams.
>
> **Tagline:** *Every format. One pane of glass.*

| | |
|---|---|
| **Version** | Plan **v4.1** — 7 August 2026 |
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
| **Phase 4** | `Mini Mode v1.1` — Local compact 400×44 bar | Everything in §M.7 | 🟡 Design locked v4.1 — awaiting implementation |

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
| **Engine + video path** | One `vlc_engine`, one zero-copy pipeline |
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

**Therefore: Halcyon will never give libVLC an HWND.** Video must arrive as *pixels we own*, so it becomes an ordinary item inside the Qt scene graph — sortable, clippable, blurrable, and paintable *under* other items.

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

### 0.3 The solution — zero-copy triple buffer → QSG texture

**Core insight:** VLC's `lock` callback asks *us* where to write. We hand it a pointer to memory **we allocated and keep forever**. VLC decodes *directly into our buffer*. No copy on our side — VLC's write is the same write it would have made into its own vout buffer anyway.

A `QImage` constructed over a raw pointer is a **view, not a copy**. It goes straight to `QQuickWindow.createTextureFromImage()` — a single DMA upload, unavoidable for *any* renderer including VLC's own.

**Net result: exactly one hardware texture upload per frame, zero CPU memcpy.** The theoretical floor for libVLC 3.

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
│    QImage view over ring[read_idx]        (zero copy)        │
│    createTextureFromImage(..., NoOwnership)  (1 DMA upload)  │
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

1. **`--avcodec-threads=0`** — every core. Default.
2. **Turbo Mode** — opt-in, switches that media to `set_hwnd()` + `--avcodec-hw=d3d11va`. ~3% CPU. Trade: transport bar drops to a solid strip *below* the video (HWND rule from §0.1 returns). Lives in Settings. 4K is never a hard wall.
3. **libVLC 4 path** — `libvlc_video_set_output_callbacks()` renders GPU-to-GPU into a texture we own: hardware decode *and* perfect compositing. **Not usable today** — as of mid-2026 VLC 4.0 is still unreleased, VideoLAN still ships 3.0.x, and the first public beta on pre-release libVLC 4 only reached iOS in June 2026. All video output is isolated behind `engine/video_out.py`, so switching later is a single-file change.

### 0.6 Verification gate

**Write no UI until this passes.** ~150-line throwaway script:

- 1080p H.264 through the zero-copy I420 path
- A `Rectangle`, 60% opacity, `MultiEffect` blur, rounded corners, sitting **over** the video
- An animated element crossing the video at a steady 60 fps

**Pass:** sustained 60 fps, CPU < 25%, no tearing, glass visibly blending with moving video, no flicker on resize.

Pass and everything after is ordinary application code. Fail and you know in a day, not month three.

---

# PHASE 1 — Local Mode

> **Ship target:** `v0.1.0-local` · **Estimate:** 15–18 working days
> **This is the biggest phase by far** — it carries the entire shared foundation plus the richest mode. Phases 2 and 3 are small by comparison. That front-loading is deliberate and correct.

## P1.1 Scope

**In:** frameless glass shell, title bar, mode registry, panel dock, zero-copy video, full transport bar, OSD, local playlist, tracks/subtitles, equalizer, resume, lyrics, metadata, settings, hotkeys, packaging.

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
│   ├── video_out.py           # ★ zero-copy ring buffer (§0.3)
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
| Settings, Turbo Mode | Title bar → gear |
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

Transient overlay drawn *in the scene graph over the video* — possible only because of §0.3.

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
| **Turbo Mode HWND child** | Turbo uses native child HWND — hidden Stage would leave orphan. On entering mini, force switch to I420 soft path keeping position; on return, if Turbo setting ON, re-enable hw. Simplest: disable Turbo while mini. |
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
| **Mobile remote + QR** | Was Phase-scoped in v2.0; it's a whole second UI with its own server, and it must mirror each mode's control set — which doesn't stabilise until Phase 3. Building it earlier means building it twice. **Own phase after v1.0.** |
| Seek-bar frame thumbnails | Needs a second decoder instance; nice-to-have |
| Bookmark folders | v1 flat list is enough |
| Tab favicons | v1 flat list is enough; WebView2 exposes favicons (`FaviconChanged`) — easy post-v1.0 if wanted |
| "Play in Halcyon" from Web | Depends on per-site URL resolution |
| libVLC 4 GPU path | Blocked on upstream release (§0.5) |
| Chromecast / DLNA | Out of scope |

**Note:** the remote was in v2.0's build order at 3–4 days. Moving it out is why v3.0's total is shorter despite adding phase overhead. It isn't lost — it's sequenced correctly.

---

## 9. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| 4K60 software decode too heavy | Med | Turbo Mode (§0.5); libVLC 4 later |
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
| **No overlay / click-through bug** | 1 | ✅ **structurally impossible — §0** |
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
| Mobile remote + QR | post-v1.0 | ⏸ §8 |

**One conscious trade-off, bounded:** 4K60 needs Turbo Mode (§0.5). *The separate-window limitation from earlier drafts is resolved — see §P3.2.*

---

## 12. Getting started — Phase 1 only

```bash
git init halcyon && cd halcyon
git checkout -b phase-1-local

py -3.12 -m venv .venv && .venv\Scripts\activate
pip install PySide6 python-vlc
```

*(Phase 3 adds `pythonnet` — the bridge to Windows' built-in Edge WebView2 — plus the vendored WebView2 SDK bridge files (`Microsoft.Web.WebView2.Core.dll` + `WebView2Loader.dll`, §P3.2). `aiohttp`/`qrcode` not until the remote. Install per phase — a smaller surface is easier to debug.)*

Then build **Milestone 1.0** and nothing else. Prove the glass sits over the video at 60 fps before writing a single line of application UI.

---

*Halcyon — every format, one pane of glass.*
