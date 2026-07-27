"""Local mode — the full local player (§P1).

Everything Local-specific lives in this directory. Nothing outside it imports
anything from here except ``core/modes.py``, which appends :data:`SPEC` to the
registry.

The mechanical test (§A.2) runs the other way too: delete ``modes/m3u/`` and
``modes/web/`` from a finished build and this mode must still work perfectly.
"""

from __future__ import annotations

from core.mode_api import ModeSpec

SPEC = ModeSpec(
    id="local",
    title="Local",
    panel_qml="qrc:/modes/local/LocalPanel.qml",
    transport_qml="qrc:/modes/local/LocalTransport.qml",
    # stage_qml defaults to the shared video surface — Local has no reason to
    # override it.
    osd_enabled=True,        # the OSD is Local's, and only Local's (§6.2)
    media_keys_enabled=True,
    uses_player=True,
)
