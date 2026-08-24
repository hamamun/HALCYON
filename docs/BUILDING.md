# Building & developing Halcyon

Everything the public README leaves out — full setup, the installer pipeline,
debugging and architecture guard rails.

> If you just want the app, get the installer from the
> [latest release](https://github.com/hamamun/HALCYON/releases/latest). This
> document is for running from source or rebuilding the installer.

## Requirements

- Windows 10 / 11 x64 (the app targets Windows; the pure-Python parts run anywhere)
- Python 3.12 (3.11 also works)
- latest stable libVLC x64 binaries in `vendor/vlc/` — **not committed**, see below
- WebView2 SDK bridge files (`Microsoft.Web.WebView2.Core.dll` +
  `WebView2Loader.dll`) in `vendor/webview2/` — **not committed**, fetched
  locally (see below)

## Setup (zero-coder — single file)

All Python dependencies are in **one file**: `requirements.txt`.

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

### Fetching libVLC (not committed — ~60 MB)

1. Download the **latest stable Win64 7z/zip** build of VLC from
   <https://download.videolan.org/pub/videolan/vlc/last/win64/>.
   The Windows build fetcher resolves the ordinary `vlc-*-win64.7z` archive
   and verifies its upstream SHA-256 checksum.
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

   It should print the bundled libVLC version. The exact version is also
   recorded in `vendor/vlc/VERSION.txt`.

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

## Windows installer build

The release installer is built by GitHub Actions on Windows
(`.github/workflows/build-installer.yml`):

1. resolves and downloads the latest stable VLC x64 into `vendor/vlc/` and verifies its SHA-256 checksum;
2. prunes VLC plugins using `packaging/vlc-plugin-whitelist.txt`;
3. keeps `vendor/vlc/hrtfs/` beside `libvlccore.dll` for spatial audio;
4. downloads the WebView2 bridge DLLs from the official NuGet package into
   `vendor/webview2/` and unblocks them;
5. downloads the VC++ and WebView2 Runtime installers into `packaging/redist/`;
6. builds the Nuitka standalone app;
7. builds `Halcyon-Setup.exe` with Inno Setup.

The workflow runs on every push to `main` (artifact + latest GitHub Release),
matching `v*` tag (artifact + GitHub Release), and manual dispatch. The release
body records the exact VLC and WebView2 SDK versions fetched for that build.

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

The version number lives in **one place**: `core/version.py`. The Inno Setup
script and Nuitka build read it from there, so a release cannot ship with
mismatched version metadata.

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

## Layout

```
main.py                 app bootstrap
engine/                 libVLC + zero-copy video path   ← shared, frozen after P1
core/                   mode registry, settings, library ← shared, frozen after P1
ui/                     shell, theme, shared components  ← shared, frozen after P1
  transport/            shared transport PARTS (each mode arranges its own bar)
modes/<id>/             everything mode-specific
tools/                  isolation guard + dev utilities
vendor/vlc/             bundled libVLC (fetched, gitignored)
vendor/webview2/         WebView2 SDK bridge files — Core.dll + WebView2Loader.dll (fetched locally, not committed)
config/                 first-run defaults, copied to %APPDATA%\Halcyon
```

**Isolation rule:** no mode imports another mode; nothing shared imports a mode.
Enforced by:

```bash
python tools/check_isolation.py
```

## Video backends

`HALCYON_VIDEO_BACKEND` selects the pixel path:

| Value | Format | Bytes/px | Notes |
|---|---|---|---|
| `auto` *(default)* | I420 → packed grayscale texture + YUV shader | 1.5 | fewest bytes over the bus |
| `i420` | as above, forced | 1.5 | |
| `rv32` | RGB straight to `createTextureFromImage` | 4.0 | fallback for odd GPUs |

Both paths do **one** texture upload per frame from a triple-buffered ring that
libVLC decodes straight into — no CPU memcpy anywhere.
