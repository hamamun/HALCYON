"""Local video-mode policy — §0.5.1 / §V.

One setting (``playback.videoMode``), three user-visible choices, and exactly
one place that decides what the engine should actually do:

``auto``
    Local only. Demanding media (3840×2160 at 60 FPS is the reference case)
    resolves to Turbo; everything else — including *anything* we could not
    measure — resolves to Soft.
``soft``
    The existing callback/I420 path with its RV32 fallback and full QML blur.
    This is the fallback for every uncertainty in this file: an unknown mode,
    an unreadable stream, a mode that is not allowed to use Turbo, a Turbo
    attempt that failed. Soft is never wrong, only slower.
``turbo``
    Native VLC/GPU output embedded in the single Halcyon window (§V.3).

Deliberately pure Python: no Qt, no libVLC, no imports from ``modes`` (§A.3
rule 2). The Qt-facing wiring lives in :class:`core.app.AppController` and the
native surface lives in ``engine/``, so the policy itself stays trivially
testable and has exactly one definition.
"""

from __future__ import annotations

AUTO = "auto"
SOFT = "soft"
TURBO = "turbo"

#: The user-facing choices, in dropdown order (§V.1).
MODES: tuple[str, ...] = (AUTO, SOFT, TURBO)

#: What the engine can actually be asked to do. ``auto`` is a *selection*, not
#: an output route — it always resolves to one of these two.
EFFECTIVE_MODES: tuple[str, ...] = (SOFT, TURBO)

#: Human labels. The dropdown shows these; settings store the values above.
LABELS: dict[str, str] = {AUTO: "Auto", SOFT: "Soft", TURBO: "Turbo"}

#: Legacy keys kept readable for migration only. Neither may ever reappear as
#: a user-facing control (§V.1).
LEGACY_TURBO_KEY = "playback.turboMode"
LEGACY_BACKEND_KEY = "video.backend"

#: 4K. At or above this pixel count software decode is already tight on a
#: mainstream CPU (§0.5's cost table), whatever the frame rate.
_UHD_PIXELS = 3840 * 2160

#: 1440p. Comfortable at 24–30 FPS, not at 50+.
_QHD_PIXELS = 2560 * 1440

#: Where "high frame rate" starts. 48 rather than 60 so 50 FPS broadcast
#: material is treated the same as 59.94.
_HIGH_FPS = 48.0

#: A small tolerance so 3840×2160 letterboxed to 3840×2076, or a stream that
#: reports 3830 columns, is still recognised as UHD.
_TOLERANCE = 0.95


def normalise(value: object, default: str = AUTO) -> str:
    """Coerce anything (settings value, QML string, ``None``) to a valid mode."""
    try:
        text = str(value).strip().lower()
    except Exception:  # pragma: no cover - str() on a hostile object
        return default
    return text if text in MODES else default


def label(mode: object) -> str:
    return LABELS.get(normalise(mode), LABELS[AUTO])


def _positive(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number <= 0:  # NaN or nonsense
        return 0.0
    return number


def is_demanding(width: object, height: object, fps: object = None) -> bool:
    """Is this media heavy enough that software decode is a bad bet?

    Unknown geometry is never demanding: the whole point of the fallback is
    that we only choose Turbo when we can *show* the reason.
    """
    w = _positive(width)
    h = _positive(height)
    if w <= 0 or h <= 0:
        return False
    pixels = w * h
    rate = _positive(fps)
    if pixels >= _UHD_PIXELS * _TOLERANCE:
        return True
    if pixels >= _QHD_PIXELS * _TOLERANCE and rate >= _HIGH_FPS:
        return True
    return False


def resolve(
    selected: object,
    *,
    turbo_allowed: bool = False,
    has_video: bool | None = None,
    width: object = None,
    height: object = None,
    fps: object = None,
) -> str:
    """Return the effective output route: :data:`SOFT` or :data:`TURBO`.

    ``turbo_allowed`` is the active mode's capability (``ModeSpec.turbo_allowed``).
    M3U passes ``False`` and therefore always gets Soft, even when the stored
    Local preference says Turbo (§V.2).

    ``has_video`` is the app's existing "does this media have a video track"
    answer, as three states:

    ``False``
        Known audio-only. Always Soft, *including* an explicit Turbo
        selection. Turbo's whole job is to put decoded pixels in a native
        child window; with no video track there are no pixels, so it would
        create and embed an empty HWND, push the chrome onto the overlay
        window and lose the QML blur — all cost, no benefit. The album-art
        card belongs on the ordinary scene graph.
    ``True``
        Known to have video. Normal rules.
    ``None``
        Not known yet — tracks have not arrived and the container has not
        been parsed. Deliberately **not** treated as Soft: unlike geometry
        (where unknown means "we cannot justify Turbo"), an unknown track
        list is the normal state for the first instant of every video file,
        and forcing Soft here would make an explicit Turbo choice open on
        Soft and then re-open on Turbo a moment later — a visible blip on
        every file. The caller re-resolves when tracks land, and the
        audio-only case is caught then (or immediately, by extension).
    """
    mode = normalise(selected)
    if not turbo_allowed:
        return SOFT
    if has_video is False:
        return SOFT
    if mode == SOFT:
        return SOFT
    if mode == TURBO:
        return TURBO
    return TURBO if is_demanding(width, height, fps) else SOFT


#: Badge glyphs. Single letters so the badge stays a glance, not a read.
TURBO_LETTER = "T"
SOFT_LETTER = "S"
AUTO_PREFIX = "A"


def badge(selected: object, effective: object, *, turbo_allowed: bool = True) -> str:
    """The title-bar badge text: ``"AT"``, ``"AS"``, ``"T"`` or ``"S"``.

    The letter is always the route the player is **actually** on — never the
    request. A user who picked Turbo and got Soft (audio-only media, an
    unsupported system, a failed attempt) sees ``S``, because a badge that
    claimed ``T`` while the CPU did the decoding would be lying about the one
    thing it exists to report.

    The ``A`` prefix discloses that *Auto* made the choice, which is the only
    case where the route is not self-evident from Settings. It is omitted when
    the mode cannot honour Auto anyway: M3U forces Soft and its dropdown reads
    a plain disabled "Soft", so its badge is a plain ``S`` to match.
    """
    letter = TURBO_LETTER if normalise(effective, SOFT) == TURBO else SOFT_LETTER
    if not turbo_allowed:
        return letter
    return AUTO_PREFIX + letter if normalise(selected) == AUTO else letter


def describe(
    selected: object,
    effective: object,
    *,
    turbo_allowed: bool = True,
    has_video: bool | None = None,
    mini_mode: bool = False,
    turbo_available: bool = True,
    pending: bool = False,
    soft_failed: bool = False,
) -> str:
    """The badge's hover tooltip: what is running, and *why*.

    "Soft" on its own invites "I selected Turbo, so why is it not on?" — so
    every Soft answer that the user did not directly ask for carries its
    reason. The order below is precedence, not preference: the first condition
    that forced the route is the one worth naming.

    ``pending`` means Settings changed but the new choice has not been
    applied yet: Soft / Auto / Turbo only take effect when the next video
    starts, so a Turbo selection still playing on Soft is not a failed start.
    ``soft_failed`` means Soft had video tracks but produced no picture and
    was rescued to Turbo (task 1).
    """
    mode = normalise(selected)
    route = normalise(effective, SOFT)

    if route == TURBO:
        if soft_failed:
            if mode == AUTO:
                return "Auto \u2192 Turbo \u2014 Soft failed to generate video, rescued to hardware (GPU) output"
            return "Turbo \u2014 Soft failed to generate video, rescued to hardware (GPU) output"
        if mode == AUTO:
            text = "Auto \u2192 Turbo \u2014 hardware (GPU) video output"
        else:
            text = "Turbo \u2014 hardware (GPU) video output"
        if pending and mode != TURBO:
            return text + "; the new choice applies when the next video starts"
        return text

    soft = "Soft \u2014 software (CPU) video output"
    if pending and mode != route and not mini_mode:
        return f"{soft}; the new choice applies when the next video starts"
    if mini_mode:
        return f"{soft}; Mini Mode always uses Soft"
    if not turbo_allowed:
        return f"{soft}; this mode always uses Soft"
    if has_video is False:
        return f"{soft}; this media is audio only"
    if mode == TURBO:
        if not turbo_available:
            return f"{soft}; Turbo is not available on this system"
        return f"{soft}; Turbo could not start"
    if mode == AUTO:
        return "Auto \u2192 Soft \u2014 software (CPU) video output;" \
               " this media is not demanding"
    return f"{soft}; selected in Settings"


def migrate_legacy(data: dict) -> dict:
    """Fold the removed Turbo checkbox into ``playback.videoMode``.

    Called by :class:`core.settings.Settings` on load. The rules:

    * an existing ``playback.videoMode`` always wins — the user chose it in the
      new UI, so a stale legacy key must not override it;
    * ``playback.turboMode: true`` with no new key becomes ``"turbo"``, which is
      the closest honest reading of "this profile asked for hardware output";
    * ``playback.turboMode: false`` is simply the old default and is dropped
      rather than pinned to ``"soft"``, so those profiles get the new ``auto``;
    * ``video.backend`` is *not* migrated. It selects the Soft chroma (I420 vs
      RV32) and still does, internally — it was never a Turbo switch, and §V
      only removes it from the visible Settings.

    ``playback.turboMode`` is removed from the loaded profile either way, so
    nothing downstream can resurrect it as user-facing state. The dict is
    mutated in place and returned for convenience.
    """
    legacy_turbo = data.pop(LEGACY_TURBO_KEY, None)
    if "playback.videoMode" in data:
        data["playback.videoMode"] = normalise(data["playback.videoMode"])
    elif legacy_turbo is True or str(legacy_turbo).strip().lower() == "true":
        data["playback.videoMode"] = TURBO
    return data
