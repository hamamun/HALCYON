"""Web mode — real browser inside the main window on Edge WebView2 (§P3).

Phase 3 is additive (§A.3): everything Web-specific lives in this directory,
and the only touch to Phase 1 code is one entry appended to ``core/modes.py``
in Milestone 3.2, plus the disclosed v4.0 generic mode capability changes
(``panel_enabled`` and ``keep_stage_alive``). Deleting this directory leaves
Local and M3U perfect (§A.2).

Engine: Windows' built-in Edge WebView2 via pythonnet (Route A, owner decision
4 Aug 2026). No Qt WebView, no QtWebEngine, nothing bundled (§P3.2).
"""

from __future__ import annotations

from core.mode_api import ModeSpec


def build_web_context(engine, controller, settings):
    """The ``setup`` hook (§A.2). Publishes browser context as modeContext_web."""
    from modes.web.browser import BrowserContext

    return BrowserContext(controller=controller)


SPEC = ModeSpec(
    id="web",
    title="Web",
    panel_qml="qrc:/modes/web/WebPanel.qml",
    stage_qml="qrc:/modes/web/WebStage.qml",
    transport_qml="",
    osd_enabled=False,
    right_dock_enabled=False,
    media_keys_enabled=False,
    uses_player=False,
    panel_enabled=False,
    keep_stage_alive=True,
    setup=build_web_context,
)
