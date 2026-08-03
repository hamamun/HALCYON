"""Web mode — Microsoft Edge WebView2 browser channel (§P3)."""

from __future__ import annotations

from core.mode_api import ModeSpec


def build_web_context(engine, controller, settings):
    from modes.web.webview2_host import build_web_context as _build

    return _build(engine=engine, controller=controller, settings=settings)


SPEC = ModeSpec(
    id="web",
    title="Web",
    panel_qml="",                 # no left drawer; bookmarks live in dropdown/manager tab
    stage_qml="qrc:/modes/web/WebStage.qml",
    transport_qml="",             # Web has top navigation chrome, not a bottom transport bar
    osd_enabled=False,
    right_dock_enabled=False,
    media_keys_enabled=False,
    uses_player=False,
    setup=build_web_context,
)
