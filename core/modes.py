"""The mode registry — §A.2.

**This is the one Phase 1 file later phases are allowed to touch, and only to
append a single entry to :data:`REGISTRY`.** Anything else means the foundation
was wrong; stop and fix Phase 1 rather than patching around it (§A.3 rule 1).

    Phase 2:  REGISTRY = [local.SPEC, m3u.SPEC]
    Phase 3:  REGISTRY = [local.SPEC, m3u.SPEC, web.SPEC]

The title bar renders its chips from this list, so adding a mode needs no edit to
``TitleBar.qml`` (§P1.4).
"""

from __future__ import annotations

from core.mode_api import ModeSpec
from modes import local

# ---------------------------------------------------------------------------
# THE REGISTRY — later phases append exactly one entry each.
# ---------------------------------------------------------------------------
REGISTRY: list[ModeSpec] = [
    local.SPEC,
]
# ---------------------------------------------------------------------------


def all_modes() -> list[ModeSpec]:
    return list(REGISTRY)


def mode_ids() -> list[str]:
    return [m.id for m in REGISTRY]


def get(mode_id: str) -> ModeSpec:
    for spec in REGISTRY:
        if spec.id == mode_id:
            return spec
    raise KeyError(f"no mode registered with id {mode_id!r}")


def find(mode_id: str) -> ModeSpec | None:
    for spec in REGISTRY:
        if spec.id == mode_id:
            return spec
    return None


def default_mode() -> ModeSpec:
    """First registered mode. Local, always — it is the one that must survive
    the deletion of every other mode directory (§A.2 mechanical test)."""
    if not REGISTRY:
        raise RuntimeError("mode registry is empty — Halcyon cannot start")
    return REGISTRY[0]


def _validate() -> None:
    seen: set[str] = set()
    for spec in REGISTRY:
        if spec.id in seen:
            raise RuntimeError(f"duplicate mode id in REGISTRY: {spec.id!r}")
        seen.add(spec.id)


_validate()
