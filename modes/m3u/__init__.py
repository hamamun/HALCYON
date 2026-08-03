"""M3U mode — network playlists and live streams (§P2).

Phase 2 is additive (§A.3): everything M3U-specific lives in this directory,
and the only touch to Phase 1 code is the one entry appended to
``core/modes.py``. Deleting this directory leaves Local perfect (§A.2).

The seven-control bar, the sources manager, the no-right-panel rule and the
one-tuner rule are owner decisions of 2026-08-02 — see the plan's v3.2–v3.4
change notes.
"""

from __future__ import annotations

from core.mode_api import ModeSpec


def build_m3u_context(engine, controller, settings):
    """The ``setup`` hook (§A.2). Imported lazily so the registry itself never
    pays for Qt at import time."""
    from modes.m3u.playlist import M3UContext

    return M3UContext(engine=engine, controller=controller, settings=settings)


SPEC = ModeSpec(
    id="m3u",
    title="M3U",
    panel_qml="qrc:/modes/m3u/M3UPanel.qml",
    transport_qml="qrc:/modes/m3u/M3UTransport.qml",
    # stage_qml defaults to the shared video surface — M3U plays through the
    # same pipeline as Local (§P2.2).
    # M3U deliberately gets lightweight transport toasts, but not Local's
    # Info/Lyrics/Equalizer dock.
    osd_enabled=True,
    right_dock_enabled=False,
    media_keys_enabled=True,  # space/volume stay useful; seek keys no-op on live
    uses_player=True,
    setup=build_m3u_context,
)
