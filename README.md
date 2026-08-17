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
| **1 — Local** | `v0.1.0-local` | ✅ complete / signed off — frozen at tag `v0.1.0-local` |
| **2 — M3U** | `v0.2.0-m3u` | ✅ complete / signed off — frozen at tag `v0.2.0-m3u` |
| **3 — Web** | `v1.0.0` | ✅ complete / signed off — full Halcyon v1.0.0 release |
| **4 — Mini v1.1** | `v1.1.0-mini` | ✅ built — compact 400×44 bar |
| **R — Remote v1.2** | `v1.2.0-remote` | ✅ **complete / verified 2026-08-09** — phone remote, QR in Settings, real-time sync, Local/M3U/Web control, Power |

Phase 2 & 3 guard: `python tools/check_isolation.py --phase 3` verifies that new
modes touch nothing frozen without disclosure.

---

## Requirements

- Windows 10 / 11 x64 (the app targets Windows; the pure-Python parts run anywhere)
- Python 3.12 (3.11 also works)
- libVLC 3.0.21 x64 binaries in `vendor/vlc/` — **not committed**, see below
- **Phase 3:** WebView2 SDK bridge files (`Microsoft.Web.WebView2.Core.dll` + `WebView2Loader.dll`) in `vendor/webview2/` — **not committed**, fetched locally (see §Web Phase / plan §P3.2)

---

## Setup (zero-coder — single file)

All Python dependencies are now in **one file**: `requirements.txt` (merged 2026-08-09 from the old 3 files).

**Windows / PowerShell / CMD:**

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Alternative (if `pip` alone doesn't work):**

```bash
python -m pip install -r requirements.txt
```

That's it — Local + M3U + Web + Remote + tests all installed.
Old files `requirements-phase1.txt`, `requirements-dev.txt`, `requirements-dev-full.txt` have been removed.

### Fetching libVLC (not committed — ~60 MB)

1. Download the **Win64 7z/zip** build of VLC **3.0.21** from
   <https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/>
   (file: `vlc-3.0.21-win64.7z`).
2. Extract it and copy into `vendor/vlc/`:

   ```
   vendor/vlc/
   ├── libvlc.dll
   ├── libvlccore.dll
   ├── plugins/          ← the whole directory
   └── hrtfs/            ← the whole directory (spatial audio, see below)
   ```

   `hrtfs/` holds `dodeca_and_7channel_3DSL_HRTF.sofa`, which libVLC's
   binauralizer uses to render multichannel audio for headphones. It resolves
   that path relative to the directory containing `libvlccore.dll`, so the
   folder name **must** be `hrtfs`. Without it, playing a 5.1 track prints
   `Could not load the SOFA HRTF` to stderr — bypassing Halcyon's logging,
   since it happens inside libVLC — and the audio falls back to a plain
   downmix. Playback is otherwise unaffected, so it is easy to miss.

   A `.sofa` left loose in `vendor/vlc/` is also picked up: Halcyon then passes
   `--hrtf-file` explicitly at startup and logs `using bundled HRTF at …`.

3. Verify:

   ```bash
   python -c "import vlc; print(vlc.libvlc_get_version())"
   ```

   It should print the bundled libVLC version (3.0.21).

Halcyon sets `VLC_PLUGIN_PATH` and pre-loads the bundled DLLs at startup, so a
system-wide VLC installation is neither needed nor used.

On Linux/macOS (development only) Halcyon falls back to the system libVLC if
`vendor/vlc/` is absent.

### WebView2 bridge files (Windows Web mode)

Place these files with these **exact names** in `vendor/webview2/`:

```text
vendor/webview2/
├── Microsoft.Web.WebView2.Core.dll
└── WebView2Loader.dll
```

They come from the official `Microsoft.Web.WebView2` NuGet package and are only
the pythonnet bridge. The actual Edge WebView2 Runtime is supplied by Windows
11 and most supported Windows 10 installations; Halcyon shows an in-app
`WebView2 is not available` message if Windows does not have a usable runtime.

Downloads use WebView2's normal secure save prompt. Certificate problems are
left to Edge/WebView2's secure error page; Halcyon never auto-accepts an invalid
certificate.

---

## Windows installer build

The release installer is built by GitHub Actions on Windows:

1. downloads VLC 3.0.21 x64 into `vendor/vlc/`;
2. prunes VLC plugins using `packaging/vlc-plugin-whitelist.txt`;
3. keeps `vendor/vlc/hrtfs/` beside `libvlccore.dll` for spatial audio;
4. downloads the WebView2 bridge DLLs from the official NuGet package into
   `vendor/webview2/` and unblocks them;
5. downloads the VC++ and WebView2 Runtime installers into `packaging/redist/`;
6. builds the Nuitka standalone app;
7. builds `Halcyon-Setup.exe` with Inno Setup.

Manual Windows build equivalent:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install nuitka ordered-set zstandard
powershell -ExecutionPolicy Bypass -File packaging/fetch_vendor_windows.ps1
python tools/build_shaders.py
python tools/build_nuitka.py --output-dir dist
iscc packaging\installer\Halcyon.iss
```

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
vendor/webview2/         WebView2 SDK bridge files — Core.dll + WebView2Loader.dll (fetched locally, not committed, §P3.2)
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
