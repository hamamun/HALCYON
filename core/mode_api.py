"""The mode contract — §A.2.

Written once in Phase 1. **Never edited again.**

A mode is a plain, frozen description of what the shell should load. It declares
*what* to show, never *how* — the shell owns the window, the dock, the stage and
the theme (§B.1); the mode owns its panel, its bar and its data (§B.2).

Phases 2 and 3 add a ``ModeSpec`` inside ``modes/<id>/__init__.py`` and append one
entry to ``core.modes.REGISTRY``. That is the entire integration surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: Default stage: the zero-copy video surface (§0.3). Web mode overrides it (§P3.3).
DEFAULT_STAGE_QML = "qrc:/ui/shell/VideoStage.qml"


@dataclass(frozen=True, slots=True)
class ModeSpec:
    """Everything the shell needs to know about a mode.

    Frozen on purpose: a mode cannot mutate its own registration at runtime, so
    the shell can cache anything derived from it.
    """

    #: Stable identifier — ``"local"`` | ``"m3u"`` | ``"web"``. Used for QML
    #: loader keys, settings sub-trees and per-mode state. Never shown to users.
    id: str

    #: Title-bar chip label (§P1.4).
    title: str

    #: Left-dock panel, a QML URL.
    panel_qml: str

    #: The mode's own control bar, assembled from shared ``ui/transport/`` parts
    #: (§B.4). Empty string = the mode draws no bar at all (Web uses its own
    #: address bar, which is *navigation*, not transport — §P3.4).
    transport_qml: str

    #: Centre stage. Defaults to the video surface. Declared in Phase 1 with a
    #: default precisely so Phase 3 can override it without editing this file
    #: (§P3.3) — the foundation is designed before it is needed.
    stage_qml: str = DEFAULT_STAGE_QML

    #: Whether the OSD layer is live in this mode (§6.2). Local only in practice.
    osd_enabled: bool = False

    #: Whether media hotkeys (space, seek, volume…) do anything here. Web is inert
    #: (§P3.6) because the page owns its own playback UI.
    media_keys_enabled: bool = True

    #: Whether this mode drives the shared libVLC player. Web does not.
    uses_player: bool = True

    #: Optional per-mode Python setup, called once at startup with the app
    #: context. Returns an object exposed to QML as ``modeContext_<id>``, or
    #: ``None``. Keeps mode-specific wiring out of ``main.py``.
    setup: Callable[..., object] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.id or not self.id.isidentifier():
            raise ValueError(f"ModeSpec.id must be a valid identifier, got {self.id!r}")
        if not self.title:
            raise ValueError(f"ModeSpec({self.id}).title must not be empty")
        if not self.panel_qml:
            raise ValueError(f"ModeSpec({self.id}).panel_qml must not be empty")

    @property
    def has_transport(self) -> bool:
        return bool(self.transport_qml)

    @property
    def context_property(self) -> str:
        """Name this mode's context object takes in QML."""
        return f"modeContext_{self.id}"
