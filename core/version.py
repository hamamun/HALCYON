"""Single source of truth for the Halcyon application version.

Kept deliberately tiny so it can be imported from anywhere — packaging
scripts, QML, the error dialog — without pulling in Qt or libVLC. The
Inno Setup script and Nuitka build read this value so a release cannot
ship with mismatched version metadata.
"""

from __future__ import annotations

#: Application version. Bump for every tagged release; keep in sync with
#: packaging/installer/Halcyon.iss (MyAppVersion) and tools/build_nuitka.py
#: (--file-version / --product-version).
__version__ = "1.2.1"

#: Human-readable build channel, surfaced in the title bar and the fatal
#: error dialog so a screenshot proves which installer is running.
BUILD_CHANNEL = "release"
