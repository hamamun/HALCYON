# Third-party notices

The Halcyon installer bundles the following third-party components. Halcyon's
own code is covered by [LICENSE](LICENSE); these components keep their own
licences, which apply to them.

## libVLC (VideoLAN)

- **Component:** libVLC 3.0.21 (`libvlc.dll`, `libvlccore.dll`)
- **Licence:** GNU Lesser General Public License v2.1 (LGPL-2.1)
- **Source:** <https://www.videolan.org/vlc/>
- **Licence text:** <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>

## VLC plugins

- **Component:** the bundled VLC plugin set (decoders, demuxers, filters, …)
- **Licence:** mixed LGPL-2.1 / GPL-2.0-or-later (the plugins bundled by the
  Halcyon build are the standard set distributed by VideoLAN)
- **Source:** <https://www.videolan.org/vlc/>
- **Licence text:** <https://www.gnu.org/licenses/old-licenses/gpl-2.0.html>

The plugin set shipped with the installer is pruned to a whitelist
(`packaging/vlc-plugin-whitelist.txt`); the unmodified originals are available
from the VideoLAN download server.

## Python runtime and Python packages

The Nuitka build embeds CPython and bundles third-party Python packages
(PySide6, python-vlc, and others listed in `requirements.txt`), each under its
own licence. Their licences are included with the installed application and
are listed in `requirements.txt`.

## Microsoft Edge WebView2 Runtime

- **Component:** WebView2 Evergreen Runtime (installed on demand from
  Microsoft's official installer if missing)
- **Licence:** Microsoft proprietary, redistributable under the Microsoft
  Edge WebView2 distribution terms
- **Source / terms:** <https://developer.microsoft.com/microsoft-edge/webview2/>

## Microsoft Visual C++ Redistributable

- **Component:** VC++ 2015–2022 x64 Redistributable (installed on demand from
  Microsoft's official installer if missing)
- **Licence:** Microsoft proprietary, redistributable under the Microsoft
  Software Licence Terms for Visual C++ Redistributables
- **Source / terms:** <https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist>

Halcyon is an independent project and is not affiliated with, endorsed by, or
sponsored by VideoLAN, Microsoft, or any of the upstream projects listed above.
