"""The application controller — the Python half of the Actions host.

QML's ``actionHost`` (ui/Main.qml) routes UI intent here; this object owns the
behaviour and talks to the engine, the library and the active mode's data. One
implementation per action, on both sides of the QML boundary (§4.1).

**Mode neutrality.** This class knows about ``ModeSpec`` and about the *active*
mode's context object, never about a specific mode by name. Local's playlist is
reached through a registered context object, so Phase 2 can add M3U without a
single edit here (§A.3).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import modes as mode_registry
from core import paths
from core import video_mode as video_policy
from core.media_types import AUDIO_EXTENSIONS, is_media_path, is_subtitle_path
from core.mode_api import ModeSpec

log = logging.getLogger(__name__)


class ModeList(QObject):
    """Exposes the registry to QML so the title bar can render its chips
    without knowing which modes exist (§P1.4)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._specs = mode_registry.all_modes()

    @Property("QVariantList", constant=True)
    def list(self) -> list:
        return [self._as_dict(spec) for spec in self._specs]

    @Slot(str, result="QVariant")
    def spec(self, mode_id: str):
        """Look up a mode, falling back to the default rather than to null.

        QML calls this during binding evaluation, sometimes before
        ``App.activeMode`` has propagated. Returning ``None`` there turns every
        downstream ``modeSpec.usesPlayer`` into a TypeError, so an unknown id
        resolves to the default mode — Local — which is always registered.
        """
        found = mode_registry.find(mode_id)
        if found is None:
            log.warning("unknown mode %r — falling back to the default", mode_id)
            found = mode_registry.default_mode()
        return self._as_dict(found)

    @staticmethod
    def _as_dict(spec: ModeSpec) -> dict:
        # Modes declare their QML as qrc: URLs (the packaged form). Resolve them
        # to real files when running from a checkout — see core.paths.qml_url.
        return {
            "id": spec.id,
            "title": spec.title,
            "panelQml": paths.qml_url(spec.panel_qml),
            "stageQml": paths.qml_url(spec.stage_qml),
            "transportQml": paths.qml_url(spec.transport_qml),
            "osdEnabled": spec.osd_enabled,
            "rightDockEnabled": spec.right_dock_enabled,
            "mediaKeysEnabled": spec.media_keys_enabled,
            "usesPlayer": spec.uses_player,
            # Generic shell capabilities.  They must cross the Python/QML
            # boundary or a mode merely *declares* its separation while the
            # shared shell continues to render the old chrome.
            "panelEnabled": spec.panel_enabled,
            "keepStageAlive": spec.keep_stage_alive,
            # Local video modes (§V.1): the Settings dropdown is enabled only
            # where Turbo is actually selectable. M3U shows it disabled on
            # "Soft"; Web disables Video mode entirely (usesPlayer is false).
            "turboAllowed": spec.turbo_allowed,
        }


class AppController(QObject):
    """Behaviour behind the Actions."""

    activeModeChanged = Signal()
    # Mode-neutral title contribution.  A context that has a title (Web's
    # active page, for example) publishes it through this generic protocol;
    # Local and M3U remain free to return an empty string.
    modeWindowTitleChanged = Signal()
    subtitleDelayChanged = Signal()
    tracksChanged = Signal()
    resumePrompted = Signal(str, int)
    mediaNameChanged = Signal()
    #: A playlist mutation removed the active media and left no replacement
    #: playing.  This is deliberately separate from engine.mediaChanged:
    #: stop() clears the engine without opening another media, so no media
    #: change is announced.  Shared UI such as the OSD uses this lifecycle
    #: signal to retire controls that would otherwise still target that media.
    playlistPlaybackCleared = Signal()
    #: The selected video mode (auto/soft/turbo) or the effective route
    #: (soft/turbo) changed — §V.2. The Settings dropdown and the Turbo stage
    #: both bind to this rather than polling the engine.
    videoModeChanged = Signal()

    def __init__(
        self,
        engine,
        settings,
        library,
        metadata,
        lyrics,
        equalizer,
        video_adjust=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._settings = settings
        self._library = library
        self._metadata = metadata
        self._lyrics = lyrics
        self._equalizer = equalizer
        self._video_adjust = video_adjust

        self._active_mode = settings.get("ui.mode", "local")
        if mode_registry.find(self._active_mode) is None:
            self._active_mode = mode_registry.default_mode().id

        #: Per-mode playlist/context objects, registered at startup. The
        #: controller never names a mode; it looks one up.
        self._contexts: dict[str, QObject] = {}

        self._subtitle_delay = 0
        self._audio_tracks: list[dict] = []
        self._video_tracks: list[dict] = []
        self._subtitle_tracks: list[dict] = []
        #: Drives the CC button's availability badge (§P1.6): true only when
        #: the current video has subtitles the user could switch on. Recomputed
        #: in _refresh_tracks so it tracks reality the instant tracks arrive.
        self._subtitles_available = False
        # Split views of the same spu list: tracks found inside the media vs
        # files this session attached (add_slave). One spu id appears in
        # exactly one of them.
        self._embedded_subtitle_tracks: list[dict] = []
        self._local_subtitle_tracks: list[dict] = []
        self._current_audio_id = -1
        self._current_subtitle_id = -1
        #: Basenames of every external subtitle attached for the current
        #: media — the only trace libVLC leaves of an add_slave spu is its
        #: file name, so classification matches on it (see _split_* below).
        self._external_sub_files: list[str] = []
        #: Ground-truth {spu_id -> full path} for every file attached via
        #: add_slave during this media. Populated from a before/after diff of
        #: the SPU list — the only race-proof way to bind an add_slave spu to
        #: the file that produced it (libVLC's SPU description on many builds
        #: is "Track N", not the file name).
        self._local_subtitle_map: dict[int, str] = {}
        #: When a media has a saved resume position, the Now Playing toast must
        #: be suppressed and only the resume toast shown. mediaChanged fires
        #: synchronously inside engine.open(), before resumePrompted, so QML's
        #: resumeShowing guard (opacity>0) is still false at that moment. This
        #: flag suppresses mediaNameChanged at the source for that one open.
        self._suppress_next_media_name: bool = False
        #: Enforces the "subtitles start off" rule. Set on every media change;
        #: consumed on the first Playing tick, when libVLC has settled on its
        #: auto-picked default subtitle. Once consumed it stays False until the
        #: next media, so a resume-from-pause never wipes the user's selection.
        self._force_subs_off_pending: bool = False

        #: The user's choice from the Settings dropdown (§V.1). "auto" until a
        #: profile says otherwise; a legacy profile has already been migrated
        #: by core.settings, so nothing here has to know about turboMode.
        self._video_mode = video_policy.normalise(
            settings.get("playback.videoMode", video_policy.AUTO)
        )
        #: The selection that was last handed to the engine. Settings changes
        #: update ``_video_mode`` immediately but do *not* switch the live
        #: route — Soft / Auto / Turbo only apply when the next video starts.
        self._last_applied_selection = self._video_mode
        #: Guards the Auto re-resolution against thrashing: Auto is evaluated
        #: once per media, when metadata for that media is available.
        self._video_mode_media = ""
        #: Last known answer to "does the current media have a video track",
        #: as the same tri-state :func:`core.video_mode.resolve` takes: True,
        #: False, or None for "not established yet". Cached so a change — the
        #: moment a track list or a parse turns "unknown" into "audio-only" —
        #: can re-resolve the route exactly once instead of on every one of
        #: the many tracksChanged/metadata signals a single open produces.
        self._video_mode_has_video: bool | None = None
        #: True while Mini Mode is active. Mini deliberately runs on Soft
        #: (§M / §V.4): a 460×44 bar has nowhere to put a native child window,
        #: and an orphaned hidden HWND is exactly what the failure rule
        #: forbids. The selected mode is re-resolved on the way back out.
        self._mini_mode = False
        #: Re-entrancy guards for the route switch — see _schedule_video_mode.
        self._video_mode_pending = False
        self._video_mode_applying = False

        engine.mediaChanged.connect(self._on_media_changed)
        engine.endReached.connect(self._on_end_reached)
        engine.timeChanged.connect(self._lyrics.update_position)
        engine.tracksChanged.connect(self._refresh_tracks)
        engine.stateChanged.connect(self._on_state_changed)
        # Auto needs the media's geometry, which libVLC parses asynchronously
        # (core/metadata.py retries for ~2 s). Re-resolving when metadata lands
        # is what lets a 4K60 file reach Turbo instead of being judged on the
        # empty first read — and the "unknown -> Soft" rule means the interim
        # answer is always the safe one.
        changed = getattr(metadata, "changed", None)
        if changed is not None and hasattr(changed, "connect"):
            changed.connect(self._on_metadata_changed)
        # The engine reports its *actual* route, including a Turbo attempt that
        # failed and fell back (§V.4). Mirrored so QML shows the truth.
        route_changed = getattr(engine, "videoRouteChanged", None)
        if route_changed is not None and hasattr(route_changed, "connect"):
            route_changed.connect(lambda _route: self.videoModeChanged.emit())

    # ---------------------------------------------------------- registration ---
    def register_context(self, mode_id: str, context: QObject) -> None:
        self._contexts[mode_id] = context
        # Contexts may optionally expose a `windowTitleChanged` Qt signal.  The
        # shared controller deliberately does not import/know a concrete mode;
        # it simply forwards this small display protocol to QML.
        changed = getattr(context, "windowTitleChanged", None)
        if changed is not None and hasattr(changed, "connect"):
            changed.connect(self.modeWindowTitleChanged.emit)

    def context(self, mode_id: str | None = None) -> QObject | None:
        return self._contexts.get(mode_id or self._active_mode)

    @property
    def playlist(self):
        """The active mode's list-like context, if it has one."""
        return self._contexts.get(self._active_mode)

    # ------------------------------------------------------------------ mode ---
    @Property(str, notify=activeModeChanged)
    def activeMode(self) -> str:  # noqa: N802 - QML-facing
        return self._active_mode

    @Property(str, notify=modeWindowTitleChanged)
    def modeWindowTitle(self) -> str:  # noqa: N802 - QML-facing
        """Optional active-mode title for the OS taskbar/window list.

        The protocol intentionally accepts either a Python method or a Qt/QML
        property-like value, so the chassis stays independent of every mode.
        """
        context = self.context()
        if context is None:
            return ""
        value = getattr(context, "window_title", "")
        try:
            value = value() if callable(value) else value
        except Exception:
            log.debug("mode %r window title failed", self._active_mode, exc_info=True)
            return ""
        return str(value or "")

    @Slot(str)
    def setActiveMode(self, mode_id: str) -> None:  # noqa: N802 - QML-facing
        """Change the band, not the radio (§A.1).

        Each mode keeps its own data, so switching away and back leaves a
        playlist exactly as it was. Nothing is cleared and nothing crosses over.
        """
        if mode_id == self._active_mode:
            return
        target_spec = mode_registry.find(mode_id)
        if target_spec is None:
            return
        # One-tuner rule for non-player modes (Web mode, §P3.3): stop video engine
        if not target_spec.uses_player:
            self._engine.stop()
            self._metadata.load("")
            self._lyrics.load("")
        self._active_mode = mode_id
        self._settings.set("ui.mode", mode_id)
        self.activeModeChanged.emit()
        self.modeWindowTitleChanged.emit()
        # The new mode may not be allowed to use Turbo (M3U, Web). Re-resolving
        # here is what enforces "M3U is always Soft regardless of the stored
        # Local preference" (§V.2) without either mode knowing it exists.
        self._video_mode_media = ""
        self._schedule_video_mode()
        log.info("mode -> %s", mode_id)

    # -------------------------------------------------------- video mode ---
    #
    # One setting, one resolver, one place that talks to the engine (§V.2).
    # Everything else — the Settings dropdown, the stage, Mini Mode — reads
    # these properties or calls setVideoMode(); none of them decides anything.

    @Property(str, notify=videoModeChanged)
    def videoMode(self) -> str:  # noqa: N802 - QML-facing
        """The user's selection: "auto", "soft" or "turbo"."""
        return self._video_mode

    @Property(str, notify=videoModeChanged)
    def effectiveVideoMode(self) -> str:  # noqa: N802 - QML-facing
        """What the engine is actually doing: "soft" or "turbo".

        Reads the engine when it can, because a Turbo attempt that failed has
        already fallen back and the dropdown must not claim otherwise.
        """
        route = getattr(self._engine, "videoRoute", None)
        if isinstance(route, str) and route in video_policy.EFFECTIVE_MODES:
            return route
        return self._resolve_video_mode()

    @Property(bool, notify=activeModeChanged)
    def videoModeEnabled(self) -> bool:  # noqa: N802 - QML-facing
        """Is the Video mode dropdown interactive in the active mode?

        Local: yes. M3U: no — visible, disabled, showing Soft. Web: no, and the
        whole row is disabled because Web has no player at all (§V.1).
        """
        spec = mode_registry.find(self._active_mode)
        return bool(spec is not None and spec.uses_player and spec.turbo_allowed)

    @Property(bool, notify=activeModeChanged)
    def videoModeAvailable(self) -> bool:  # noqa: N802 - QML-facing
        """Does Video mode mean anything at all here? False in Web (§V.1)."""
        spec = mode_registry.find(self._active_mode)
        return bool(spec is not None and spec.uses_player)

    @Property(str, notify=videoModeChanged)
    def videoModeBadge(self) -> str:  # noqa: N802 - QML-facing
        """Title-bar badge text: "AT", "AS", "T" or "S" (§V.7).

        Always the route actually in use, so a Turbo selection that fell back
        still reads "S".
        """
        return video_policy.badge(
            self._video_mode,
            self.effectiveVideoMode,
            turbo_allowed=self.videoModeEnabled,
        )

    @Property(str, notify=videoModeChanged)
    def videoModeTooltip(self) -> str:  # noqa: N802 - QML-facing
        """The badge's hover text — the route plus the reason for it (§V.7)."""
        engine = self._engine
        available = True
        probe = getattr(engine, "turbo_available", None)
        if callable(probe):
            try:
                available = bool(probe())
            except Exception:  # pragma: no cover - defensive, never blocks UI
                log.debug("turbo_available() failed", exc_info=True)
        last = getattr(self, "_last_applied_selection", self._video_mode)
        pending = self._video_mode != last
        return video_policy.describe(
            self._video_mode,
            self.effectiveVideoMode,
            turbo_allowed=self.videoModeEnabled,
            # The cached answer, not a fresh probe: the tooltip must explain
            # the route that is actually running, and that route was resolved
            # from this value.
            has_video=getattr(self, "_video_mode_has_video", None),
            mini_mode=bool(getattr(self, "_mini_mode", False)),
            turbo_available=available,
            pending=pending,
        )

    @Slot(str)
    def setVideoMode(self, mode: str) -> None:  # noqa: N802 - QML-facing
        """The dropdown's one entry point. Persists only.

        Soft, Auto and Turbo are a *preference* for the next media start,
        not a live switch. Applying here would tear Soft down and build a
        native HWND while Settings is still open — which buries the modal
        dialog and kills the title bar. Mini Mode and a mode change still
        re-resolve immediately; a new file does too, via mediaChanged.
        """
        value = video_policy.normalise(mode)
        if value != self._video_mode:
            self._video_mode = value
            self._settings.set("playback.videoMode", value)
            log.info("video mode -> %s (applies when the next video starts)", value)
        self.videoModeChanged.emit()

    @Slot(result="QVariant")
    def turboWindow(self):  # noqa: N802 - QML-facing
        """The native child ``QWindow`` for QML's ``WindowContainer``, or None.

        A slot returning ``QVariant`` rather than a typed Property: shiboken
        cannot build a ``QWindow*`` property (``Invalid property type``), and
        the value is not a binding source anyway — the stage fetches it once
        when ``effectiveVideoMode`` becomes "turbo" and clears it on the way
        back to Soft.
        """
        return getattr(self._engine, "turbo_window", None)

    @Slot()
    def noteTurboEmbedded(self) -> None:  # noqa: N802 - QML-facing
        """The shell adopted the native child. Seal the HWND and start play.

        WindowContainer reparents the child *after* the engine pointed
        libVLC at it. That reparent is what punches a desktop hole under
        the title bar and what leaves D3D11 silent until a second play().
        """
        handler = getattr(self._engine, "note_turbo_embedded", None)
        if callable(handler):
            try:
                handler()
            except Exception:
                log.debug("note_turbo_embedded failed", exc_info=True)

    @Slot("QVariant")
    def sealTurboHost(self, qwindow) -> None:  # noqa: N802 - QML-facing
        """Make the Halcyon shell opaque for the life of windowed Turbo."""
        from engine.turbo_surface import seal_host_window

        try:
            seal_host_window(qwindow)
        except Exception:
            log.debug("sealTurboHost failed", exc_info=True)

    @Slot("QVariant")
    def unsealTurboHost(self, qwindow) -> None:  # noqa: N802 - QML-facing
        """Restore the glass/layered shell after Turbo ends."""
        from engine.turbo_surface import unseal_host_window

        try:
            unseal_host_window(qwindow)
        except Exception:
            log.debug("unsealTurboHost failed", exc_info=True)

    @Slot(str)
    def reportTurboFailure(self, reason: str = "") -> None:  # noqa: N802 - QML-facing
        """QML's channel for a *late* Turbo failure — §V.4.

        The container could not adopt the child window, or the embedded surface
        stopped drawing. The engine tears the native route down and continues
        the same media on Soft; nothing here decides anything.
        """
        handler = getattr(self._engine, "turbo_failed", None)
        if callable(handler):
            try:
                handler(str(reason or "reported by the shell"))
            except Exception:
                log.debug("Turbo failure handling failed", exc_info=True)
        self.videoModeChanged.emit()

    @Slot(bool)
    def setMiniMode(self, active: bool) -> None:  # noqa: N802 - QML-facing
        """Mini Mode forces Soft while it is on, and re-resolves on the way out.

        The compact bar has no stage to embed a native child window in, so a
        Turbo child would be either orphaned or invisible — both are the thing
        §V.4 forbids. On return the *selected* mode (including Auto resolving
        to Turbo) is applied again, with the usual Soft fallback.
        """
        active = bool(active)
        if active == self._mini_mode:
            return
        self._mini_mode = active
        self._video_mode_media = ""
        self._schedule_video_mode()
        self.videoModeChanged.emit()

    def _resolve_video_mode(self) -> str:
        """Selection + active mode + video track + geometry -> "soft"/"turbo"."""
        if self._mini_mode:
            return video_policy.SOFT
        spec = mode_registry.find(self._active_mode)
        allowed = bool(spec is not None and spec.uses_player and spec.turbo_allowed)
        width, height, fps = self._media_geometry()
        return video_policy.resolve(
            self._video_mode,
            turbo_allowed=allowed,
            has_video=self._current_has_video(),
            width=width,
            height=height,
            fps=fps,
        )

    def _current_has_video(self) -> bool | None:
        """Does the playing media have a video track? True / False / unknown.

        Three sources, cheapest first, and they answer at different times:

        1. ``self._video_tracks`` — the controller's own track list, the same
           one behind the public :attr:`hasVideo` property. Authoritative once
           libVLC has selected tracks, which is a moment *after* the open.
        2. ``Metadata.hasVideo`` — the container parse. Often lands first on a
           local file and is what makes an audio file resolve to Soft on the
           very first pass.
        3. The file extension. Not a track list, but a ``.flac`` has no video
           track and never will, and knowing that before either async source
           reports means an audio file is never briefly routed to Turbo.

        Only a *positive* "no video" from (2) or (3) is reported as False; when
        nothing knows anything the answer is ``None`` ("not yet"), which
        :func:`core.video_mode.resolve` deliberately does not treat as Soft.
        """
        if self._video_tracks:
            return True
        metadata = getattr(self, "_metadata", None)
        meta_has_video = getattr(metadata, "hasVideo", None)
        meta_has_audio = getattr(metadata, "hasAudio", None)
        if meta_has_video is True:
            return True
        # Metadata reports False both for "parsed: audio only" and for "nothing
        # read yet", so it only counts as a real answer once the parse has
        # found *something* — an audio track, or any video rows.
        if meta_has_video is False and meta_has_audio is True:
            return False
        try:
            path = self._current_path()
        except Exception:
            return None
        if path and Path(path).suffix.lower() in AUDIO_EXTENSIONS:
            return False
        return None

    def _media_geometry(self) -> tuple[float, float, float]:
        """Width, height and frame rate of the current media, or zeros.

        Parsed out of the same rows the Info panel shows, so there is one
        metadata reader rather than a second libVLC probe: "3840×2160" and
        "59.9 fps". When the container parse has not produced a size yet
        (the normal first second of a file), fall back to the live player
        (``video_get_size`` / ``get_fps``) so Auto can still promote a 4K
        file once the decoder is up. Anything unreadable returns zeros,
        which :func:`core.video_mode.resolve` treats as "not demanding" —
        the safe direction (§V.2).
        """
        width = height = fps = 0.0
        rows = []
        try:
            rows = list(getattr(self._metadata, "videoDetails", []) or [])
        except Exception:
            log.debug("could not read video details for the video-mode decision",
                      exc_info=True)
            rows = []
        for row in rows:
            try:
                label = str(row.get("label", "")).strip().lower()
                value = str(row.get("value", "")).strip()
            except AttributeError:
                continue
            if label == "resolution":
                parsed_w, parsed_h = _parse_resolution(value)
                if parsed_w and parsed_h:
                    width, height = parsed_w, parsed_h
            elif label == "frame rate":
                fps = _as_float(value.split()[0] if value else "")
        if not (width and height):
            width, height = self._engine_video_size()
        if not fps:
            fps = self._engine_video_fps()
        return (width, height, fps)

    def _engine_video_size(self) -> tuple[float, float]:
        probe = getattr(self._engine, "video_size", None)
        if not callable(probe):
            return (0.0, 0.0)
        try:
            size = probe()
        except Exception:
            return (0.0, 0.0)
        if not size:
            return (0.0, 0.0)
        try:
            return (_as_float(size[0]), _as_float(size[1]))
        except (TypeError, ValueError, IndexError):
            return (0.0, 0.0)

    def _engine_video_fps(self) -> float:
        probe = getattr(self._engine, "video_fps", None)
        if not callable(probe):
            return 0.0
        try:
            return _as_float(probe())
        except Exception:
            return 0.0

    def _maybe_resolve_auto_from_geometry(self) -> None:
        """Auto's second/third chance, once width×height is actually known.

        Called from the metadata parse *and* from the first Playing tick:
        libVLC often has no container geometry on open, and
        ``video_get_size`` only answers after the decoder starts. Without
        this, Auto stayed on Soft for every demanding file whose Info rows
        landed late — which is most of them.
        """
        if not hasattr(self, "_video_mode"):
            return
        if self._video_mode != video_policy.AUTO:
            return
        mrl = getattr(self._engine, "currentMedia", "") or ""
        width, height, _fps = self._media_geometry()
        if not (width and height):
            return
        if mrl and mrl == self._video_mode_media:
            return
        self._video_mode_media = mrl
        self._schedule_video_mode()
        self.videoModeChanged.emit()

    def _schedule_video_mode(self) -> None:
        """Apply the route on the next event-loop turn.

        **Load-bearing.** Switching route re-opens the current media inside the
        engine, and the two places that want a re-resolution — ``mediaChanged``
        and the metadata ``changed`` signal — are themselves emitted from
        inside ``engine.open()`` / ``metadata.load()``. Applying synchronously
        there would re-enter ``open()`` while the outer call is still running,
        and the outer call would then finish against the inner call's player
        state. Deferring by one turn makes the switch a clean, separate
        operation, which is also what keeps the resume seek attached to the
        right open.
        """
        if self._video_mode_pending:
            return
        self._video_mode_pending = True
        QTimer.singleShot(0, self._apply_video_mode_deferred)

    def _apply_video_mode_deferred(self) -> None:
        self._video_mode_pending = False
        self._apply_video_mode()
        # The badge reports the achieved route, and an engine without a
        # videoRouteChanged signal would otherwise leave it showing the
        # previous media's answer.
        self.videoModeChanged.emit()

    def _apply_video_mode(self) -> None:
        """Tell the engine which route to use. Failures are the engine's job.

        ``set_video_route`` returns the route it actually achieved: a Turbo
        attempt that failed has already cleaned up and continued the same media
        on Soft (§V.4), so there is nothing to retry here.
        """
        if self._video_mode_applying:
            return
        target = self._resolve_video_mode()
        setter = getattr(self._engine, "set_video_route", None)
        if not callable(setter):
            return
        self._video_mode_applying = True
        try:
            achieved = setter(target)
        except Exception:
            log.debug("could not apply the video route", exc_info=True)
            return
        finally:
            self._video_mode_applying = False
        self._last_applied_selection = self._video_mode
        if achieved != target:
            log.info("video route %s unavailable — running on %s", target, achieved)

    def _note_video_presence(self) -> None:
        """Re-resolve if the answer to "has this media video?" just changed.

        Called from both places that can change it — the track list and the
        metadata parse — because an audio-only file must land on Soft under
        *every* selection, not only Auto (§V.2). Comparing against the cached
        tri-state is what keeps this to one route change per media: a single
        open emits ``tracksChanged`` and ``changed`` several times each.

        ``_video_mode`` is the flag for "this controller has video-mode state".
        One of the callers is ``_refresh_tracks``, which several existing test
        suites drive on a deliberately partial controller built with
        ``__new__`` — seeding track lists only, since that is all track
        refreshing needs. Such a controller has no route to re-resolve, so
        this is a no-op for it rather than an AttributeError.
        """
        if not hasattr(self, "_video_mode"):
            return
        current = self._current_has_video()
        if current == self._video_mode_has_video:
            return
        self._video_mode_has_video = current
        self._schedule_video_mode()
        self.videoModeChanged.emit()

    def _on_metadata_changed(self) -> None:
        """Auto's second chance, once libVLC has actually parsed the stream."""
        # Audio-only is not an Auto-specific question — check it first, before
        # the Auto guard below returns.
        self._note_video_presence()
        self._maybe_resolve_auto_from_geometry()

    # -------------------------------------------------------------- playlist ---
    @Slot(list)
    @Slot("QVariant")
    def addPaths(self, incoming) -> None:  # noqa: N802 - QML-facing
        """The one append path — Add Files, Add Folder, Ctrl+O and drag-and-drop
        all arrive here (§4.1).

        The parameter is deliberately **not** called ``paths``: this module
        imports a module of that name, and shadowing it inside the one method
        that does path handling is how you get an ``AttributeError`` at the
        worst possible moment.

        Overloaded on ``QVariant`` as well as ``list`` so a JS array from QML
        binds whichever way PySide marshals it.
        """
        target = self.playlist
        if target is None or not hasattr(target, "add_paths"):
            log.warning("addPaths: active mode %r has no queue", self._active_mode)
            return

        if isinstance(incoming, (str, bytes)):
            incoming = [incoming]
        cleaned = [_normalise(p) for p in incoming or []]
        cleaned = [p for p in cleaned if p]
        if not cleaned:
            return

        # Dropping a .srt on the window means "subtitle what is playing", not
        # "queue this file". Split them out before the queue ever sees them: a
        # subtitle added as a track opens as media with no audio and no video,
        # which tears down the video pipeline mid-playback.
        #
        # Non-media files (Excel sheets, Markdown notes, Word documents) are
        # not queueable either. Folders stay allowed because the playlist model
        # scans them for media, but plain files must be recognised audio/video
        # before they are offered to the queue.
        subtitles: list[str] = []
        queueable: list[str] = []
        for path in cleaned:
            if is_subtitle_path(path):
                subtitles.append(path)
                continue
            candidate = Path(path).expanduser()
            if candidate.is_dir() or is_media_path(path):
                queueable.append(path)
                continue
            log.info("ignoring non-media file: %s", candidate.name or path)

        if subtitles and not queueable:
            self._attach_subtitles(subtitles)
            return
        if subtitles:
            # Mixed drop (a video and its sidecar): queue the media, and let
            # the sidecar be picked up by the normal auto-load on open.
            log.info("ignoring %d subtitle file(s) alongside media", len(subtitles))

        cleaned = queueable
        if not cleaned:
            return

        was_empty = target.current_index() < 0
        added = target.add_paths(cleaned)
        log.info("addPaths: %d path(s) in, %d track(s) queued", len(cleaned), added)
        if added and was_empty:
            target.play_index(0)

    @Slot(list)
    def clearSelected(self, rows: list) -> None:  # noqa: N802 - QML-facing
        """Remove the selected rows. If the currently playing track was removed,
        auto-start the next available track or stop if queue is empty.
        """
        target = self.playlist
        if target is None or not hasattr(target, "remove_rows"):
            return
        wanted = [int(r) for r in rows if isinstance(r, (int, float, str))]
        if not wanted:
            return

        cur = getattr(target, "current_index", lambda: -1)()
        playing_removed = (cur in wanted)
        removed_before = len([r for r in wanted if r < cur]) if playing_removed else 0

        target.remove_rows(wanted)

        new_count = getattr(target, "count", 0)

        if playing_removed:
            if new_count == 0:
                self._engine.stop()
                self._metadata.load("")
                self._lyrics.load("")
                self._reset_track_state()
                # stop() does not emit engine.mediaChanged: there is no new
                # media to announce.  Publish the missing lifecycle edge so a
                # Resume / Start Over toast cannot outlive the removed item.
                self.playlistPlaybackCleared.emit()
            else:
                target_idx = cur - removed_before
                if target_idx < new_count:
                    next_idx = target_idx
                else:
                    rep = getattr(target, "repeat_mode", lambda: 0)()
                    next_idx = 0 if rep == 2 else new_count - 1

                target.play_index(next_idx)

    @Slot()
    def clearPlaylist(self) -> None:  # noqa: N802 - QML-facing
        """Empty the queue *and* stop the player.

        An empty playlist with audio still coming out of the speakers is the
        clearest possible contradiction between what the UI says and what the
        app is doing.
        """
        target = self.playlist
        if target is not None and hasattr(target, "clear"):
            target.clear()
        self._engine.stop()
        self._metadata.load("")
        self._lyrics.load("")
        self._reset_track_state()
        # As above, an empty player has no following mediaChanged event.  Keep
        # this on the controller action (rather than the Local panel) so the
        # toolbar, Delete key and mobile remote all retire shared playback UI.
        self.playlistPlaybackCleared.emit()

    def _current_path(self) -> str:
        """Filesystem path of whatever the engine currently has open."""
        return _from_uri(self._engine.currentMedia or "")

    def current_media_path(self) -> str:
        """Public for the subtitle downloader, which saves beside this file.

        QML never sees it — the UI gets :attr:`currentFileStem` instead."""
        return self._current_path()

    def _stop_if_orphaned(self, playing_path: str) -> None:
        """Stop playback if ``playing_path`` is no longer in the queue."""
        if not playing_path:
            return
        target = self.playlist
        if target is None:
            return
        still_queued = False
        path_at = getattr(target, "path_at", None)
        count = getattr(target, "count", 0)
        if callable(path_at):
            for row in range(int(count)):
                if path_at(row) == playing_path:
                    still_queued = True
                    break
        if not still_queued:
            self._engine.stop()
            self._metadata.load("")
            self._lyrics.load("")
            self._reset_track_state()

    @Slot(int)
    def playIndex(self, row: int) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "play_index"):
            target.play_index(row)

    @Slot(int, int)
    def moveItem(self, source: int, target_row: int) -> None:  # noqa: N802
        target = self.playlist
        if target is not None and hasattr(target, "move_row"):
            target.move_row(source, target_row)

    @Slot(result=bool)
    def next(self) -> bool:
        """Play the next item and report whether the active context accepted it.

        The boolean lets the QML action host show a channel toast only after a
        real M3U next action, rather than claiming success at the end of a list.
        The controller remains mode-neutral: every context is asked through the
        same small ``play_next`` protocol.
        """
        target = self.playlist
        play_next = getattr(target, "play_next", None)
        if callable(play_next):
            return bool(play_next())
        return False

    @Slot(result=bool)
    def previous(self) -> bool:
        """Play the previous item; see :meth:`next` for the shared protocol."""
        target = self.playlist
        play_previous = getattr(target, "play_previous", None)
        if callable(play_previous):
            return bool(play_previous())
        return False

    @Slot(result=str)
    def currentPlaybackLabel(self) -> str:  # noqa: N802 - QML-facing
        """A friendly label supplied by the active playlist, when it has one.

        Local media already has a filename-based now-playing label. M3U needs
        the parsed channel name instead of exposing a raw stream URL, so its
        context implements ``current_playback_label``. Keeping this duck-typed
        preserves the controller's mode neutrality for future modes.
        """
        target = self.playlist
        label = getattr(target, "current_playback_label", None)
        if not callable(label):
            return ""
        try:
            return str(label() or "")
        except Exception:  # noqa: BLE001 - a cosmetic label must never block playback
            log.debug("active playlist could not provide a playback label", exc_info=True)
            return ""

    @Slot()
    def cycleRepeat(self) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "cycle_repeat"):
            target.cycle_repeat()

    @Slot()
    def toggleShuffle(self) -> None:  # noqa: N802 - QML-facing
        target = self.playlist
        if target is not None and hasattr(target, "toggle_shuffle"):
            target.toggle_shuffle()

    # -------------------------------------------------------------- playback ---
    @Slot(result=bool)
    def playPause(self) -> bool:  # noqa: N802 - QML-facing
        """Toggle play/pause, or start playing from a playlist if stopped.

        ``True`` means an action was sent to the engine or active playlist. It
        gives the UI an honest basis for its Play/Pause toast: an empty playlist
        should not announce that it has started playing.
        """
        from engine.vlc_engine import State

        state = self._engine.state
        if state in (State.Playing, State.Paused):
            self._engine.toggle()
            return True

        target = self.playlist
        if target is not None:
            # M3U fast O(1) resume for 15k lists - avoids scanning view.
            # Duck-typed: if the mode offers play_current, use it.
            fast = getattr(target, "play_current", None)
            if callable(fast):
                try:
                    if fast():
                        return True
                except Exception:
                    log.debug("play_current fast path failed", exc_info=True)
            count = getattr(target, "count", 0)
            if count > 0:
                cur = getattr(target, "current_index", lambda: -1)()
                if 0 <= cur < count:
                    target.play_index(cur)
                else:
                    target.play_index(0)
                return True
            return False

        if self._engine.currentMedia:
            self._engine.play()
            return True
        return False

    @Slot()
    def play(self) -> None:  # noqa: N802 - QML-facing
        from engine.vlc_engine import State

        state = self._engine.state
        if state == State.Paused:
            self._engine.play()
            return

        target = self.playlist
        if target is not None:
            fast = getattr(target, "play_current", None)
            if callable(fast):
                try:
                    if fast():
                        return
                except Exception:
                    log.debug("play_current fast path failed in play()", exc_info=True)
            count = getattr(target, "count", 0)
            if count > 0:
                cur = getattr(target, "current_index", lambda: -1)()
                if 0 <= cur < count:
                    target.play_index(cur)
                else:
                    target.play_index(0)
            return

        if self._engine.currentMedia:
            self._engine.play()

    @Slot()
    def pause(self) -> None:  # noqa: N802 - QML-facing
        self._engine.pause()

    @Slot()
    def stop(self) -> None:  # noqa: N802 - QML-facing
        self._engine.stop()
        self._metadata.load("")
        self._lyrics.load("")
        self._reset_track_state()

    @Slot(str)
    def openPath(self, path: str) -> None:  # noqa: N802 - QML-facing
        resume_ms = 0
        if self._settings.get("playback.resumeEnabled", True):
            resume_ms = self._library.resume_position(path)
        # Suppress Now Playing when resume exists. mediaChanged fires
        # synchronously inside engine.open(), before resumePrompted, so the
        # QML guard `resumeShowing` (opacity>0) cannot have fired yet. Set the
        # flag before open() so _on_media_changed can skip mediaNameChanged.
        # _on_media_changed clears the flag when it actually suppresses; this
        # final assignment is a safety net if open() fails to emit mediaChanged.
        self._suppress_next_media_name = bool(resume_ms)
        try:
            self._engine.open(path, resume_ms)
        except Exception:
            log.debug("engine.open raised during openPath", exc_info=True)
            self._suppress_next_media_name = False
        if resume_ms:
            log.info("resuming %s at %d ms", path, resume_ms)
            self.resumePrompted.emit(path, resume_ms)
        self._suppress_next_media_name = False

    @Slot(str)
    def startOver(self, path: str) -> None:  # noqa: N802 - QML-facing
        """Abandon a resume: forget the saved position and play from the top.

        Three steps, and the order is load-bearing. Cancelling the engine's
        pending resume seek has to come first: that seek is applied when the
        media reaches Playing, which may be *after* this call, so seeking to 0
        while one is still queued is undone a moment later and playback jumps
        back to exactly where the user asked to leave.

        The two bookkeeping steps are individually guarded so a failure in
        either still leaves the picture rewound — that is the part the user can
        see, and a stale entry in recent.json is not worth losing it over.
        """
        cancel = getattr(self._engine, "cancel_pending_resume", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                log.debug("could not cancel the pending resume seek", exc_info=True)
        try:
            self._library.clear_position(path)
        except Exception:
            log.debug("could not clear the saved position", exc_info=True)
        self._engine.seek(0)
        log.info("start over: %s", path)

    def _on_media_changed(self, mrl: str) -> None:
        path = _from_uri(mrl)
        self._library.note_opened(path)
        self._metadata.load(path)
        self._lyrics.load(path)
        self._equalizer.reapply()
        if self._video_adjust is not None:
            try:
                self._video_adjust.reapply()
            except Exception:
                log.debug("video adjust reapply failed", exc_info=True)
        self._subtitle_delay = 0
        self.subtitleDelayChanged.emit()
        # External files belong to the media they were attached to; a new
        # media starts with a clean list before its sidecar is auto-loaded.
        self._external_sub_files = []
        self._local_subtitle_map = {}
        # A new media must start with subtitles off and let the user turn one
        # on. Armed here, enforced once the media reaches Playing.
        self._force_subs_off_pending = True
        # When this open carries a saved resume, suppress the Now Playing
        # toast — the resume toast owns this open. See openPath() for the
        # race (mediaChanged -> mediaNameChanged fires synchronously inside
        # engine.open(), before resumePrompted, so QML's resumeShowing guard
        # is still false).
        if self._suppress_next_media_name:
            self._suppress_next_media_name = False
            log.debug("suppressing mediaNameChanged for resume %s", path)
        else:
            self.mediaNameChanged.emit()
        if self._settings.get("subs.autoLoadSidecar", True):
            self._auto_load_subtitle(path)
        self._refresh_tracks()
        # Each media resolves its own route (§V.2). Auto sees no geometry yet
        # on the first pass — which resolves to Soft, the safe answer — and
        # _on_metadata_changed upgrades it once libVLC has parsed the stream.
        # A forced Soft/Turbo choice needs no metadata and applies right here.
        #
        # _refresh_tracks() above has already run for this media, so the
        # video-presence cache is current; re-seed it from scratch rather than
        # trusting the previous media's answer, since a video -> audio skip
        # must not carry a stale True into the new file's first resolution.
        self._video_mode_media = ""
        self._video_mode_has_video = self._current_has_video()
        self._schedule_video_mode()

    def _on_end_reached(self) -> None:
        """Advance the queue. Repeat/shuffle logic lives in the playlist model,
        in one place, so this is just a nudge."""
        target = self.playlist
        if target is not None and hasattr(target, "play_next"):
            played = target.play_next()
            if not played:
                self._engine.stop()
                self._metadata.load("")
                self._lyrics.load("")
                self._reset_track_state()

    def _on_state_changed(self, state: int) -> None:
        """Enforce "subtitles start off" on the first Playing of each media.

        libVLC auto-picks a default subtitle when a media opens; if we read the
        current spu too early we cache the wrong ("off") answer and the popover
        highlights Disable while a subtitle is actually rendering. Instead of
        reading that racy value, we force the state: on the first Playing tick
        of a new media we explicitly turn subtitles off and refresh, so the
        cached id, the popover highlight and the on-screen result all agree.

        The pending flag is consumed on the first Playing only, so a later
        pause/resume never resets the user's own subtitle selection.
        """
        from engine.vlc_engine import State

        # Auto's third chance: once the decoder is up, video_get_size knows
        # the real geometry even when the container parse did not.
        if state == State.Playing:
            self._maybe_resolve_auto_from_geometry()

        if state != State.Playing or not self._force_subs_off_pending:
            return
        self._force_subs_off_pending = False
        try:
            self._engine.set_subtitle_track(-1)
        except Exception:
            log.debug("could not force subtitles off", exc_info=True)
        self._refresh_tracks()

    def _reset_track_state(self) -> None:
        """Forget the previous media's tracks so the popover and the CC dot
        clear when the queue empties — the track-state mirror of the
        lyrics/metadata reset that already happens on clear."""
        self._audio_tracks = []
        self._video_tracks = []
        self._subtitle_tracks = []
        self._embedded_subtitle_tracks = []
        self._local_subtitle_tracks = []
        self._current_audio_id = -1
        self._current_subtitle_id = -1
        self._subtitles_available = False
        self._external_sub_files = []
        self._local_subtitle_map = {}
        self._force_subs_off_pending = False
        #: Nothing is playing, so nothing is known about it.
        self._video_mode_has_video = None
        self.tracksChanged.emit()

    def _attach_subtitles(self, paths: list[str]) -> None:
        """Load dropped subtitle files onto whatever is currently playing."""
        if not self._engine.currentMedia:
            log.info("subtitle dropped with nothing playing — ignored")
            return
        for path in paths:
            if self._load_external_subtitle(path):
                log.info("loaded subtitle %s", Path(path).name)
            else:
                log.warning("could not load subtitle %s", Path(path).name)
        self._refresh_tracks()

    def _auto_load_subtitle(self, path: str) -> None:
        """Load every matching sidecar so it appears under Local subtitles —
        WITHOUT activating any of them (the media starts with subtitles off).

        ``select=False`` attaches the slave so libVLC lists it as an available
        track but keeps the current spu at "off", which is what lets the start-
        off contract hold while the lists stay populated for the user to pick
        from.
        """
        media = Path(path)
        loaded = 0
        for suffix in (".srt", ".ass", ".ssa", ".sub", ".vtt"):
            sidecar = media.with_suffix(suffix)
            if sidecar.exists():
                if self._load_external_subtitle(str(sidecar), select=False):
                    loaded += 1
                    log.info("auto-loaded subtitle %s (inactive)", sidecar.name)
        if loaded:
            log.info("auto-loaded %d local subtitle(s) for %s", loaded, media.name)

    def _load_external_subtitle(self, path: str, select: bool = True) -> bool:
        """The one attach path for subtitle *files* — auto sidecar, user-picked,
        drag-and-drop and downloaded all arrive here (§4.1).

        ``select`` mirrors the engine's add_slave selection flag: True (manual
        pick, download) activates the subtitle; False (auto-load at media
        start) only makes it available in the Local subtitles list without
        showing it — the split that keeps "subtitles start off" true while the
        lists stay populated.

        After the slave is attached the SPU list is diffed before/after so the
        new spu id can be bound to *this* file — that mapping is what lets the
        Local subtitles section show the real file name (VLC's spu description
        for a slave is often just "Track N"). The diff is scheduled on a short
        timer because libVLC parses the file asynchronously; the new id shows
        up milliseconds after add_slave returns.
        """
        # Snapshot the SPU ids that already exist — anything new that appears
        # after add_slave is a strong candidate for being this file.
        # Always treat -1 (Disable) as already known, so a race where VLC
        # hasn't reported any spu yet never maps -1 to a file.
        try:
            before_ids = {tid for tid, _label in self._engine.subtitle_tracks()}
        except Exception:
            before_ids = set()
        before_ids.add(-1)

        ok = self._engine.add_subtitle_file(path, select=select)
        if not ok:
            return False

        name = Path(path).name
        if name not in self._external_sub_files:
            self._external_sub_files.append(name)

        # Poll a few times — libVLC may take a beat to register the slave, and
        # a single-shot at 150 ms is not always long enough on a busy machine.
        # Attempts are cheap (a getter call each) and stop the moment the id
        # is found. `path` is captured by value; the map is safe to mutate
        # from the GUI thread these callbacks land on.
        attempts = {"n": 0}

        def poll_for_slave_id() -> None:
            attempts["n"] += 1
            try:
                current = self._engine.subtitle_tracks()
            except Exception:
                current = []
            # Never consider -1 as a new local track — libVLC's Disable
            # pseudo-track. Without this, an empty before_ids (VLC not yet
            # parsed) would map -1 to the file.
            new_ids = [
                tid for tid, _label in current if tid != -1 and tid not in before_ids
            ]
            if new_ids:
                # If multiple ids appeared (rare — a second slave started at
                # the same time), take the lowest not already mapped.
                sub_map = getattr(self, "_local_subtitle_map", None)
                if sub_map is None:
                    sub_map = {}
                    self._local_subtitle_map = sub_map
                # Defensive: purge any stale -1 entry that may have been
                # created by the old race.
                sub_map.pop(-1, None)
                for tid in sorted(new_ids):
                    if tid != -1 and tid not in sub_map:
                        sub_map[tid] = path
                        break
                self._refresh_tracks()
                return
            if attempts["n"] < 8:  # up to ~1.2 s total
                QTimer.singleShot(150, poll_for_slave_id)
            else:
                # Give up: the name-based fallback in _refresh_tracks will
                # still place it under Local subtitles when the label carries
                # the file name; otherwise it stays under Subtitles rather
                # than misclassify the wrong track.
                self._refresh_tracks()

        QTimer.singleShot(150, poll_for_slave_id)
        return True

    # ---------------------------------------------------------------- tracks ---
    def _refresh_tracks(self) -> None:
        try:
            raw_audio = [
                {"id": tid, "label": label} for tid, label in self._engine.audio_tracks()
            ]
            raw_video = [
                {"id": tid, "label": label} for tid, label in self._engine.video_tracks()
            ]
            subs = [
                {"id": tid, "label": label} for tid, label in self._engine.subtitle_tracks()
            ]
            self._current_audio_id = self._engine.current_audio_track()
            self._current_subtitle_id = self._engine.current_subtitle_track()
        except Exception:
            raw_audio = []
            raw_video = []
            subs = []
            self._current_audio_id = -1
            self._current_subtitle_id = -1

        # Video tracks: filter out -1 Disable if present (though VLC typically
        # doesn't surface one for video)
        self._video_tracks = [t for t in raw_video if t["id"] != -1]

        # Audio: libVLC surfaces a synthetic (-1, "Disable") row at the top of
        # every audio_get_track_description(). Mute already covers turning
        # audio off (§P1.4), so exposing a second control for the same thing
        # is redundant — and, worse, its id (-1) is what the engine also
        # returns for "no selection yet", which is the reason the popover
        # highlighted Disable while a real track was playing.
        self._audio_tracks = [t for t in raw_audio if t["id"] != -1]

        # If the engine has not settled on a real selection yet, treat the
        # first real track as current so the popover paints its highlight on
        # what is actually coming out of the speakers.
        if self._current_audio_id == -1 and self._audio_tracks:
            self._current_audio_id = self._audio_tracks[0]["id"]

        self._subtitle_tracks = subs

        # Local vs embedded classification. The authoritative source is the
        # {spu_id -> file_path} map populated at add_slave time — id-matching
        # is race-proof against VLC labels being "Track N" instead of the
        # file name. Anything not in the map falls back to the file-name
        # matcher for tests and for old sessions without a map entry.
        local_map = getattr(self, "_local_subtitle_map", {}) or {}
        # Defensive: if an old race left -1 in the map, drop it now.
        if -1 in local_map:
            local_map = {k: v for k, v in local_map.items() if k != -1}
            self._local_subtitle_map = local_map
        embedded: list[dict] = []
        local: list[dict] = []
        for track in subs:
            if track["id"] in local_map:
                # Replace VLC's generic label with the real file name — that
                # is the whole point of the Local subtitles section.
                local.append({
                    "id": track["id"],
                    "label": Path(local_map[track["id"]]).name,
                })
            else:
                embedded.append(track)
        # Fallback: names in _external_sub_files that never got mapped to an
        # id (e.g. a sidecar added before the map existed) still route via the
        # cosmetic-key matcher.
        if getattr(self, "_external_sub_files", None):
            extra_embedded, extra_local = _split_subtitle_tracks(
                embedded, self._external_sub_files
            )
            embedded = extra_embedded
            local = local + extra_local
        self._embedded_subtitle_tracks = embedded
        self._local_subtitle_tracks = local

        # Availability hint for the CC button badge. The badge promises
        # "something here you could switch on", so it is true only when the
        # media is video, at least one real subtitle exists (embedded or
        # loaded from disk — VLC's -1 "Disable" pseudo-track never counts),
        # AND none is currently active. The moment the user turns subtitles
        # on, currentSubtitleId leaves -1 and the badge disappears.
        real_subs = [
            t for t in (embedded + local) if t["id"] != -1
        ]
        self._subtitles_available = (
            len(self._video_tracks) > 0
            and bool(real_subs)
            and self._current_subtitle_id == -1
        )

        self.tracksChanged.emit()

        # The track list is the authoritative answer to "is this audio-only",
        # and it usually arrives here first. A media that turns out to have no
        # video track goes to Soft whatever the dropdown says (§V.2).
        self._note_video_presence()

    @Property("QVariantList", notify=tracksChanged)
    def audioTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._audio_tracks

    @Property("QVariantList", notify=tracksChanged)
    def videoTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._video_tracks

    @Property("QVariantList", notify=tracksChanged)
    def subtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._subtitle_tracks

    @Property("QVariantList", notify=tracksChanged)
    def embeddedSubtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._embedded_subtitle_tracks

    @Property("QVariantList", notify=tracksChanged)
    def localSubtitleTracks(self) -> list:  # noqa: N802 - QML-facing
        return self._local_subtitle_tracks

    @Property(int, notify=tracksChanged)
    def currentAudioId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_audio_id

    @Property(int, notify=tracksChanged)
    def currentSubtitleId(self) -> int:  # noqa: N802 - QML-facing
        return self._current_subtitle_id

    @Property(bool, notify=tracksChanged)
    def hasVideo(self) -> bool:  # noqa: N802 - QML-facing
        """True if the current media has at least one video track."""
        return len(self._video_tracks) > 0

    @Property(bool, notify=tracksChanged)
    def subtitlesAvailable(self) -> bool:  # noqa: N802 - QML-facing
        """True when the current video has subtitles the user could switch on.

        Drives the CC button's availability badge. It re-evaluates on every
        ``tracksChanged`` — the same signal the popover reads — so the badge
        follows reality the instant tracks arrive asynchronously or the user
        toggles a subtitle on or off.
        """
        return self._subtitles_available

    @Property(str, notify=mediaNameChanged)
    def currentFileStem(self) -> str:  # noqa: N802 - QML-facing
        """File name of the playing media without extension — the subtitle
        download flyout's default search text and save-name base."""
        path = self._current_path()
        return Path(path).stem if path else ""

    @Slot(int)
    def setAudioTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_audio_track(track_id)
        # Refresh so the popover's "current" marker follows the click now,
        # not whenever the next external event happens to rebuild the lists.
        self._refresh_tracks()

    @Slot(int)
    def setSubtitleTrack(self, track_id: int) -> None:  # noqa: N802 - QML-facing
        self._engine.set_subtitle_track(track_id)
        self._refresh_tracks()

    @Slot()
    def cycleAudioTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(self._audio_tracks, self._engine.set_audio_track)

    @Slot()
    def cycleSubtitleTrack(self) -> None:  # noqa: N802 - QML-facing
        self._cycle(self._subtitle_tracks, self._engine.set_subtitle_track)

    @staticmethod
    def _cycle(tracks: list[dict], setter) -> None:
        if not tracks:
            return
        setter(tracks[0]["id"])

    @Slot(str)
    def loadSubtitle(self, url: str) -> None:  # noqa: N802 - QML-facing
        self._load_external_subtitle(_normalise(url))
        self._refresh_tracks()

    @Slot(int)
    def adjustSubtitleDelay(self, delta_ms: int) -> None:  # noqa: N802 - QML-facing
        self._subtitle_delay += int(delta_ms)
        self._engine.set_subtitle_delay(self._subtitle_delay)
        self.subtitleDelayChanged.emit()

    @Property(int, notify=subtitleDelayChanged)
    def subtitleDelayMs(self) -> int:  # noqa: N802 - QML-facing
        return self._subtitle_delay

    # -------------------------------------------------------------- shutdown ---
    def shutdown(self) -> None:
        # Modes first: stop background work (duration probes) before the objects
        # it reports into start disappearing. Each step is independent, so one
        # failure must not skip the settings flush that follows it.
        for mode_id, context in self._contexts.items():
            shutdown = getattr(context, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    log.exception("mode %r failed to shut down", mode_id)
        for step in (self._library.shutdown, self._equalizer.release, self._settings.flush):
            try:
                step()
            except Exception:
                log.exception("shutdown step %s failed", getattr(step, "__name__", step))


def _name_key(text: str) -> str:
    """Punctuation-insensitive comparison key for a track label or file name.

    ``"Movie.2024.1080p-[GRP].srt"`` and ``"movie 2024 1080p grp"`` must land
    on the same key whichever cosmetic form VLC picked for the spu description.
    """
    lowered = text.lower()
    for ch in "._-[](){},":
        lowered = lowered.replace(ch, " ")
    return " ".join(lowered.split())


def _split_subtitle_tracks(
    tracks: list[dict], external_files: list[str]
) -> tuple[list[dict], list[dict]]:
    """Partition *(embedded, local)* subtitle tracks by file name.

    libVLC exposes no "this spu came from ``add_slave``" flag; the only trace an
    external file leaves in the spu list is its file name in the description.
    Matching by name (instead of by add order) is immune to VLC reporting the
    tracks in several bursts while a media parses — a race an id-diff would
    lose. An empty external list means everything is embedded, which is the
    whole answer for media with no sidecar at all.
    """
    keys = set()
    for file_name in external_files:
        keys.add(_name_key(file_name))
        keys.add(_name_key(Path(file_name).stem))
    keys.discard("")

    embedded: list[dict] = []
    local: list[dict] = []
    for track in tracks:
        label_key = _name_key(track["label"])
        # id -1 is libVLC's "Disable" pseudo-track, not a spu — never let a
        # file literally named "disable.srt" drag it into the local list.
        is_local = (
            track["id"] != -1
            and bool(label_key)
            and any(key in label_key or label_key in key for key in keys)
        )
        (local if is_local else embedded).append(track)
    return embedded, local


def _as_float(text: object) -> float:
    """Best-effort number out of a metadata row ("3840", "59.9"). 0.0 if not."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_resolution(value: object) -> tuple[float, float]:
    """Accept ``3840×2160``, ``3840x2160`` and ``3840 x 2160``."""
    text = str(value or "").strip().replace("\u00d7", "x").replace("X", "x")
    if "x" not in text:
        return (0.0, 0.0)
    left, _, right = text.partition("x")
    height_token = right.strip().split()[0] if right.strip() else ""
    return (_as_float(left), _as_float(height_token))


def _normalise(raw) -> str:
    """One URL->path implementation, shared with the playlist model (§4.1)."""
    return paths.normalise_path(raw)


def _from_uri(mrl: str) -> str:
    return _normalise(mrl)
