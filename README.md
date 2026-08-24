<div align="center">

<img src="assets/halcyon.png" alt="Halcyon" width="96" />

# HALCYON

**Every format. One pane of glass.**

A sleek, glass-morphism media player for Windows —
local files, M3U playlists and web streams, with a phone remote.

[![Latest release](https://img.shields.io/github/v/release/hamamun/HALCYON?label=latest%20release&color=00b3a4)](https://github.com/hamamun/HALCYON/releases/latest)
[![Download count](https://img.shields.io/github/downloads/hamamun/HALCYON/total?color=00b3a4)](https://github.com/hamamun/HALCYON/releases)
[![Platform](https://img.shields.io/badge/Windows-10%2F11%20x64-0078d6)](https://github.com/hamamun/HALCYON/releases/latest)
[![Made with](https://img.shields.io/badge/Python%20%2B%20Qt%20Quick%20%2B%20libVLC-3776ab?logo=python&logoColor=white)](https://github.com/hamamun/HALCYON)

</div>

---

## ⬇ Download

**[Get Halcyon-Setup.exe](https://github.com/hamamun/HALCYON/releases/latest)** — one installer, Windows 10/11 x64.
No Python, no VLC install needed: everything is bundled.

> Every push to `main` builds and publishes the current source as the GitHub
> latest Release. Each release also ships a `SHA256SUMS.txt` so you can verify
> your download.

## ✨ Why Halcyon

- **True glass over video** — a frameless "aurora glass" window that genuinely
  composites *over* the picture. No black rectangle, no click-through bugs.
- **One pane of glass** — local files, M3U playlists and web streams in a single player.
- **Phone remote** — control playback, playlists and power from your phone over
  Wi-Fi. Pair instantly with a QR code from Settings.
- **Headphone surround** — bundled HRTF keeps 5.1 audio spatialised on headphones.
- **Polished around the edges** — startup splash branding, last-folder memory,
  and hardened shutdown: close it and it's gone, no lingering processes.

Built on **Python 3.12 · PySide6 / Qt Quick · the latest stable libVLC**, packaged with
**Nuitka + Inno Setup**.

## 🚀 Run from source

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Full developer setup — fetching the bundled libVLC/WebView2 files, building the
installer yourself, debugging tips and the video-backend internals — lives in
[`docs/BUILDING.md`](docs/BUILDING.md). The architecture story is in
[`HALCYON_PLAN.md`](HALCYON_PLAN.md).

## 🗺 What's inside

| Mode | What it plays |
|---|---|
| **Local** | Folders and files on your PC — with library, playlists and resume |
| **M3U** | Internet TV/radio playlists (`.m3u`, `.m3u8`, `.pls`) |
| **Web** | Web videos and streams through the built-in browser pane |
| **Remote** | All of the above, controlled from your phone |

## 💬 Questions?

Found a problem? Open an [issue](https://github.com/hamamun/HALCYON/issues).
Just want to talk? Use [discussions](https://github.com/hamamun/HALCYON/discussions).

## ⚖️ Licence

Halcyon is released under the **MIT Licence** — see
[`LICENSE`](LICENSE). It bundles libVLC and other third-party components with
their own licences; details in [`NOTICE.md`](NOTICE.md).
