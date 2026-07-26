# Halcyon — Media Player Architecture & Build Plan

> **Halcyon** *(hal-see-on)* — "calm, golden, untroubled."
> A media player that plays *everything*, looks like liquid glass, and has no seams.
>
> **Tagline:** *Every format. One pane of glass.*

| | |
|---|---|
| **Version** | Plan **v3.1** — 26 July 2026 |
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
| **Phase 1** | `Halcyon Local` — full local player | Everything in §P1.7 | ⬜ Not started |
| **Phase 2** | `Halcyon + M3U` — Local untouched, M3U added | §P2.6 (plus P1 regression) | ⬜ Blocked on P1 sign-off |
| **Phase 3** | `Halcyon Complete` — Web added, **in-window** | §P3.6 (plus P1+P2 regression) | ⬜ Blocked on P2 sign-off |

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
    osd_enabled:   bool     # §6.2
```

Phase 2 adds `modes/m3u/` containing its own `ModeSpec`, panel, and parser, then appends one line to a registration list. Phase 3 does the same for `modes/web/`.

**The mechanical test:** delete `modes/m3u/` and `modes/web/` from a finished build. The app must still start and Local must work perfectly. If it doesn't, isolation has been violated.

### A.3 Rules that hold across all phases

1. **No later phase edits an earlier phase's files.** Only exception: appending to the mode-registration list, and adding rows to the acceptance-test file. Any other edit means the foundation was wrong — stop and fix Phase 1 properly rather than patching around it.
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
- Control bar **grouping and order differ** — M3U doesn't inherit Local's left/centre/right clusters. It's laid out for six controls, centred and balanced, as if designed for six from the start.
- **No reserved gaps. No ghost slots. No "where the seek bar would have been."** M3U's bar is designed for M3U, not Local's bar with holes punched in it.
- Panel toolbars differ — four buttons in Local, one in M3U, three in Web — each spaced properly for its own count.

**The invariant is not "same positions." It is "same parts, same feel."** Switching modes should feel like changing bands on one radio: the machine is unmistakably the same, the panel is arranged for what this band does.

### B.3 The test that matters

Not a pixel-overlay comparison — that would enforce exactly the wrong thing. Instead:

- [ ] Screenshot all three modes side by side. Do they look like **one product**? Same glass, same icon weight, same corner radii, same type, same accent.
- [ ] Is any control drawn by a component that exists **only** for one mode? *(Should be no — except genuinely mode-unique things like the address bar and PiP.)*
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

Every example online uses `RV32` (BGRA, 4 bytes/px). Wrong default:

| Format | Bytes/px | 1080p frame | @60 fps |
|---|---|---|---|
| RV32 (BGRA) | 4.0 | 8.29 MB | 498 MB/s |
| **I420 (YUV 4:2:0)** | **1.5** | **3.11 MB** | **187 MB/s** |

**2.67× less traffic**, and I420 is what the decoder natively produces — requesting RV32 forces a CPU colour-space conversion on every frame before we even see it.

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

### OSD — Local only

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

**Equalizer** — `libvlc_audio_equalizer_*`, 10 bands (31 Hz–16 kHz), ±20 dB, preamp, ~18 built-in presets + user presets in `eq.json`. Right panel. Live. *Applies to any libVLC playback, so it works in M3U too (Phase 2) — same component, reached the same way, not a copy.*

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
- [ ] Glass transport bar renders **over** playing video, blur visible
- [ ] No flicker, tearing, or black flash on resize / maximise / fullscreen
- [ ] 1080p H.264 sustains 60 fps under 25% CPU
- [ ] Panels slide over video without artefacts

**Formats** — MKV · MP4 · AVI · MOV · WMV · TS · FLV · WebM · HEVC 10-bit · MP3 · FLAC · AAC · Opus
- [ ] All play without external codecs installed

**Transport** — every control in the P1.5 layout works
- [ ] Play, pause, stop, prev, next
- [ ] Seek ±10 s, scrubber drag, click-to-seek
- [ ] Volume slider, mute, both OSD-reported
- [ ] Time display toggles elapsed ↔ remaining on click
- [ ] Fullscreen via button, `F`, and double-click — all identical
- [ ] Repeat off/one/all; shuffle
- [ ] Speed 0.5×–2×

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
├── __init__.py        # ModeSpec for "m3u"
├── parser.py          # .m3u / .m3u8, #EXTINF, tvg-* attributes
├── playlist.py        # channel model
├── M3UPanel.qml       # left dock panel
└── M3UTransport.qml   # ★ single-row bar, arranged for six controls (§B.4)
ui/overlay/PipWindow.qml   # new shared component (Phase 2 owns it)
```

```python
# core/modes.py — the entire Phase 1 edit
REGISTRY = [local.SPEC, m3u.SPEC]   # ← one word added
```

## P2.3 Mode spec

```python
SPEC = ModeSpec(
    id="m3u", title="M3U",
    panel_qml="qrc:/modes/m3u/M3UPanel.qml",
    transport_qml="qrc:/modes/m3u/M3UTransport.qml",
    controls=["playPause", "prev", "next", "volume", "pip", "fullscreen"],
    osd_enabled=False,
)
```

**Six controls: play/pause, prev, next, volume+mute, PiP, fullscreen.**

Volume was missing from earlier drafts — an oversight, now corrected. Without it, changing volume in M3U would have meant reaching for the Windows mixer, which is unacceptable for a player.

Per §B.2, `M3UTransport.qml` arranges these six in a **single-row layout designed for six** — roughly 52px tall, balanced and centred. It is *not* Local's two-row bar with the seek row deleted and gaps left behind.

## P2.4 Panel

**Toolbar: Clear Playlist only.**

*Loading an `.m3u`/`.m3u8` happens via the title-bar Open action, not a panel button — a playlist file is a **document you open**, not an item you append. This is why the Local panel has Add buttons and this one doesn't.*

**Body:** parsed `#EXTINF` entries — channel name, `group-title`, `tvg-logo` thumbnail when present. Filter box. Single-click to play. No reorder (the file defines the order).

**Right panel:** hidden by default; EQ still reachable via `Ctrl+I` — the *same* component, not a copy.

**OSD:** off.

> **On seeking:** M3U entries are frequently live streams where seeking is meaningless, hence no seek bar. If you later want scrubbing for VOD-heavy playlists, add `"seekBar","time"` to the `controls` list above. One line — the UI already supports it.

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
- [ ] `#EXTINF` name, `group-title`, `tvg-logo` parsed and shown
- [ ] HLS streams play
- [ ] Filter box narrows the list
- [ ] Clear Playlist works; it is the *only* toolbar button
- [ ] Malformed / unreachable entries fail gracefully with a message, no crash

**Controls**
- [ ] **Exactly six controls render:** play/pause, prev, next, volume+mute, PiP, fullscreen
- [ ] **No seek bar, no time display, no stop, no repeat/shuffle, no subtitle/audio menu** — absent, not greyed
- [ ] Volume slider and mute both work; volume persists across a mode switch
- [ ] **No OSD fires in M3U mode**
- [ ] M3U bar is its own layout — single row, correctly balanced, **no empty gaps where Local's controls would be** (§B.2)
- [ ] Equalizer reachable in M3U via the right panel and applies to the playing stream

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

---

# PHASE 3 — Web Mode

> **Ship target:** `v1.0.0` · **Estimate:** 5–6 working days
> **Additive only.** Doesn't use the video pipeline — but renders in the same window, in the same scene graph (§P3.2).

## P3.1 Scope

**In:** `modes/web/` — embedded `WebEngineView`, address bar, bookmarks panel.
**Out:** changes to anything else.

## P3.2 Correction from earlier drafts — Web is *inside* the window

Plans up to v3.0 said Web mode had to open a second top-level window. **That was wrong, and it's now fixed.**

The error was assuming `pywebview` (which hosts WebView2 in its own OS window) was the only route. It isn't. **Qt ships its own Chromium: `QtWebEngineQuick`.** Its `WebEngineView` is a **`QQuickItem`** — per Qt's own documentation, the web views *"tie into the scene graph as a QQuickItem… Chromium renders the web content and uploads the results as textures to the GPU."*

That is **exactly the same architecture as our video surface** (§0.3). Web content becomes a scene-graph node, not a native child window. Which means:

- ✅ Embeds directly in the Stage, in the same window, under the same frameless glass shell
- ✅ QML panels, the address bar, and overlays composite **over** it correctly
- ✅ No HWND anywhere — §0.1's rule is respected, not bent
- ✅ True "one machine, three channels" (§A.1) with **no exception**

`pywebview` is **dropped from the stack entirely.**

**Cost:** QtWebEngine adds ~130 MB to the bundle (it's a full Chromium). You've said size doesn't matter — that was the only reason it was ever passed over, so the objection is gone.

**Two setup notes for the build:**
- QtWebEngine and Qt Quick must agree on the graphics backend. If the view renders blank, force OpenGL before `QGuiApplication` is constructed: `QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)`. Known, documented, one line.
- `QtWebEngineQuick.initialize()` must be called **before** the QML engine is created.

## P3.3 What gets added

```
modes/web/
├── __init__.py        # ModeSpec for "web"
├── bookmarks.py       # URL store
├── WebPanel.qml       # bookmarks list (left dock)
├── WebStage.qml       # WebEngineView — fills the Stage
└── AddressBar.qml     # nav chrome (in place of a transport bar)
```

```python
SPEC = ModeSpec(
    id="web", title="Web",
    panel_qml="qrc:/modes/web/WebPanel.qml",
    stage_qml="qrc:/modes/web/WebStage.qml",   # ← overrides video stage
    transport_qml="qrc:/modes/web/AddressBar.qml",
    osd_enabled=False,
)
```

`stage_qml` is the one addition to `ModeSpec` that Phase 3 needs. **It is declared in Phase 1** (defaulting to the video stage) precisely so Phase 3 stays additive — a good example of why the foundation is designed before it's needed.

## P3.4 No media controls — by design

The page owns its own playback UI. Drawing ours over it would be exactly the duplication §4.1 forbids, and the two would fight over state. Streaming sites ship their own player; we don't second-guess it.

**The address bar is not a transport bar.** Back · Forward · Reload · Home · URL field · loading indicator. That's *navigation* — a different role, no overlap. It occupies the same screen region as Local's transport bar and is built from the same `IconButton` vocabulary (§B.1), but it is its own component with its own job.

## P3.5 Bookmarks panel

Toolbar: **Add Bookmark** (captures current URL + title) · **Edit** · **Delete**. Body: saved URLs, click to navigate, drag to reorder. Folders deferred.

Third and final panel in the one dock slot. Three panels, one slot, zero duplication.

*Optional v1.1:* a "Play in Halcyon" action that pipes a resolved stream URL into libVLC and switches to Local — full EQ and subtitle support on a web stream.

## P3.6 Acceptance test — Phase 3

**Regression first**
- [ ] **§P1.7 and §P2.6 both re-run and passing**
- [ ] Deleting `modes/web/` leaves Local + M3U fully working
- [ ] No Phase 1 or Phase 2 file edited except the one `core/modes.py` line
- [ ] `tools/check_isolation.py` passes

**Web**
- [ ] **Web renders INSIDE the main window** — no second window appears anywhere
- [ ] Chromium content displays correctly; page scrolls, links work, text input works
- [ ] The frameless glass shell, title bar, and left panel remain visible and correct around it
- [ ] Address bar: navigate, back, forward, reload, home
- [ ] HTML5 video plays with the page's own controls
- [ ] Bookmarks add / edit / delete / reorder / navigate, persist across restart

**Controls**
- [ ] **No transport bar renders in Web mode**
- [ ] **No OSD fires**
- [ ] Media hotkeys are inert in Web mode
- [ ] Closing the browser window returns cleanly to the previous mode

**Final integration**
- [ ] All three chips render; switching in any order is stable
- [ ] Three separate lists — local queue, M3U channels, bookmarks — never cross-contaminate
- [ ] Settings, theme, and window geometry consistent across all modes
- [ ] Clean shutdown from any mode
- [ ] Installer produces a working build on a clean Windows machine with no VLC installed

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
| Shader fails on old iGPU | Low | RV32 + `Format_BGRA8888` fallback |
| Nuitka misses VLC plugins | Med | Explicit `--include-data-dir`; set `VLC_PLUGIN_PATH` at startup |
| HiDPI fractional scaling blur | Low | `PassThrough` rounding, DPR-aware texture sizing |
| QtWebEngine blank / backend mismatch | Med | Force `GraphicsApi.OpenGL` before app construction; call `QtWebEngineQuick.initialize()` first (§P3.2) |
| QtWebEngine + Nuitka packaging | Med | Ships a helper process + resources; needs explicit inclusion. Budget extra time in Milestone 1.9 / Phase 3 |

---

## 10. Bundle & Licensing

**Size:** libvlc + libvlccore ≈ 8 MB; VLC plugins ≈ 55 MB; PySide6 core ≈ 45 MB; **QtWebEngine ≈ 130 MB** (full Chromium). **Installer ≈ 240–270 MB.** Larger than v3.0's estimate — that's the cost of embedding the browser properly instead of shelling out to a second window, and you've confirmed size is not a concern.

**Licensing:** libVLC is LGPL-2.1, plugins are mixed LGPL/GPL. For a **personal, non-distributed** player this is entirely unencumbered — those obligations attach to *distribution*, and there is none.

---

## 11. Requirement Coverage

| Requirement | Phase | Status |
|---|:---:|---|
| Frameless glass UI | 1 | ✅ |
| **No overlay / click-through bug** | 1 | ✅ **structurally impossible — §0** |
| Vast format support, no codec install | 1 | ✅ bundled libVLC |
| **OSD — local only** | 1 | ✅ |
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
| **M3U: play/pause/prev/next/volume/fullscreen/PiP** | 2 | ✅ six controls |
| **M3U: own bar layout, not Local's with gaps** | 2 | ✅ §B.2 |
| **M3U playlist: clear playlist only** | 2 | ✅ |
| M3U / M3U8 / HLS | 2 | ✅ |
| Picture-in-Picture | 2 | ✅ shared buffer |
| **Web: no media controls** | 3 | ✅ nav bar only |
| **Web embedded in main window** | 3 | ✅ §P3.2 — QQuickItem, no second window |
| **Web panel: bookmark URL list** | 3 | ✅ |
| Web browsing | 3 | ✅ **QtWebEngine, embedded in main window** |
| **No duplicated actions** | all | ✅ §4.1 + `Actions` |
| **Separate playlists per mode** | all | ✅ one slot, three panels |
| **Modes independently testable** | all | ✅ §A + per-phase acceptance |
| **One machine, three channels** | all | ✅ §B — shared vocabulary, per-mode layout |
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

*(`PySide6-Addons` supplies QtWebEngine and isn't needed until Phase 3; `aiohttp`/`qrcode` not until the remote. Install per phase — a smaller surface is easier to debug.)*

Then build **Milestone 1.0** and nothing else. Prove the glass sits over the video at 60 fps before writing a single line of application UI.

---

*Halcyon — every format, one pane of glass.*
