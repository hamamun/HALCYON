# Halcyon

> *Every format. One pane of glass.*

A Windows media player built on **PySide6 / Qt Quick** + **libVLC 3.0.21**, with a frameless
"aurora glass" UI where the chrome genuinely composites **over** the video — no HWND, no
click-through bug, no black rectangle punched through the window.

See [`HALCYON_PLAN.md`](HALCYON_PLAN.md) for the architecture and
[`CHECKLIST.md`](CHECKLIST.md) for build status.

---

## Status

| Phase | Ship | State |
|---|---|---|
| **1 — Local** | `v0.1.0-local` | 🟡 in progress |
| **2 — M3U** | `v0.2.0-m3u` | ⬜ blocked on P1 sign-off |
| **3 — Web** | `v1.0.0` | ⬜ blocked on P2 sign-off |

---

## Requirements

- Windows 10 / 11 x64 (the app targets Windows; the pure-Python parts run anywhere)
- Python 3.12 (3.11 also works)
- libVLC 3.0.21 x64 binaries in `vendor/vlc/` — **not committed**, see below

---

## Setup

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-phase1.txt
```

### Fetching libVLC (not committed — ~60 MB)

1. Download the **Win64 7z/zip** build of VLC **3.0.21** from
   <https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/>
   (file: `vlc-3.0.21-win64.7z`).
2. Extract it and copy into `vendor/vlc/`:

   ```
   vendor/vlc/
   ├── libvlc.dll
   ├── libvlccore.dll
   └── plugins/          ← the whole directory
   ```

3. Verify:

   ```bash
   python -m tools.check_vlc
   ```

   It should print the libVLC version and the plugin path it resolved.

Halcyon sets `VLC_PLUGIN_PATH` and pre-loads the bundled DLLs at startup, so a
system-wide VLC installation is neither needed nor used.

On Linux/macOS (development only) Halcyon falls back to the system libVLC if
`vendor/vlc/` is absent.

---

## Running

```bash
python main.py
```

### Debugging

```bash
python main.py --debug          # or: set HALCYON_DEBUG=1
```

In VS Code, press **F5** and pick **Halcyon (debug)** (`.vscode/launch.json`).

Debug mode does two things that matter when a control "does nothing and prints
no error":

* raises Halcyon's own logging to `DEBUG`;
* installs a Qt message handler, so **QML** warnings — a mistyped property, a
  `ReferenceError` inside a signal handler, a binding loop — land in the same
  console as the Python logs, with file and line:

```
09:29:09 WARNING qml   file:///…/ui/Main.qml:601: ReferenceError: Libary is not defined
09:29:09 DEBUG   core.library   resume /movies/film.mkv at 867000 ms
```

QML warnings are logged at **any** level, not just in debug — a warning there
means a binding is dead, which is otherwise invisible from a bug report.

### The compositing spike (Milestone 1.0 — the gate)

Before trusting the architecture, run the standalone spike. It proves glass blur
composites over live 1080p video at 60 fps:

```bash
python spike.py path\to\some_1080p.mkv
```

Pass criteria are printed on screen and listed in `CHECKLIST.md` → Milestone 1.0.

---

## Layout

```
main.py                 app bootstrap
spike.py                Milestone 1.0 compositing gate (throwaway, kept for regressions)
engine/                 libVLC + zero-copy video path   ← shared, frozen after P1
core/                   mode registry, settings, library ← shared, frozen after P1
ui/                     shell, theme, shared components  ← shared, frozen after P1
  transport/            shared transport PARTS (each mode arranges its own bar)
modes/<id>/             everything mode-specific
tools/                  isolation guard + dev utilities
vendor/vlc/             bundled libVLC (fetched, gitignored)
config/                 first-run defaults, copied to %APPDATA%\Halcyon
```

**Isolation rule (§A.3):** no mode imports another mode; nothing shared imports a mode.
Enforced by:

```bash
python tools/check_isolation.py
```

---

## Video backends

`HALCYON_VIDEO_BACKEND` selects the pixel path (see §0.3–0.4 of the plan):

| Value | Format | Bytes/px | Notes |
|---|---|---|---|
| `auto` *(default)* | I420 → packed grayscale texture + YUV shader | 1.5 | fewest bytes over the bus |
| `i420` | as above, forced | 1.5 | |
| `rv32` | RGB straight to `createTextureFromImage` | 4.0 | fallback for odd GPUs; §9 |

Both paths do **one** texture upload per frame from a triple-buffered ring that
libVLC decodes straight into — no CPU memcpy anywhere.

---

## Licence

Personal, non-commercial, not redistributed. libVLC is LGPL-2.1; its plugins are mixed
LGPL/GPL. Those obligations attach to distribution, of which there is none.
