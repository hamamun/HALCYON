"""Hidden second decoder — seek-bar still-frame preview · §S.

``ScrubPreview`` answers one question: *"what does this video look like at
the position under the pointer?"* It is the "second decoder instance" that
§8 of the plan always knew the seek-bar thumbnails needed — a headless
libVLC player that decodes quietly beside the main player and hands still
frames to the UI.

Why a second player instead of snapshotting the main one
--------------------------------------------------------
The main player's position is *playing time*, not pointer time. Snapshotting
it would yank the picture the user is watching (and, worse, seek the audio
pipeline) just to answer a hover. A second player is free to park at any
timestamp without anyone noticing.

How it works
------------
* A separate ``vlc.Instance`` with ``--vout=dummy``: frames are decoded and
  rendered into a no-op video output — no window, no vmem ring, no surface —
  yet ``libvlc_video_take_snapshot`` still captures the current picture.
* ``--no-audio`` drops the audio pipeline entirely (thumbnails are silent).
* ``--avcodec-hw=none`` for the same reason as the main engine: hardware
  decode output is opaque and cannot be read back reliably (§0.5).
* On ``set_source(mrl)`` the media is played just long enough to reach
  Playing (the dummy vout now exists), then **paused** so decoding idles at
  near-zero cost until a request arrives.
* ``request(ms)`` seeks to ``ms``, waits a short settle for the decoder to
  produce the target frame, then calls ``video_take_snapshot``. Requests
  are **coalesced**: only the newest pending position is served, so a fast
  pointer sweep cannot queue up behind itself.

Robustness contract (§S.3)
--------------------------
* No module-level ``import vlc`` — like every engine module, this stays
  importable without libVLC present.
* The libVLC instance is created **lazily** on the first local file; every
  step is wrapped, so any failure marks the decoder unavailable and the
  popup simply never appears. The main player is never touched.
* Teardown mirrors ``VlcEngine.shutdown`` (§9 order): stop → settle →
  detach events → release, and the event callbacks are hard-referenced on
  ``self`` (a collected ctypes trampoline crashes the process).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

log = logging.getLogger(__name__)

#: Snapshot width in pixels; height 0 = keep the source aspect ratio.
#: 320 px is comfortably sharp for the 160×90 popup and cheap to write.
SNAPSHOT_WIDTH = 320

#: How long to let the dummy vout decode after a seek before snapshotting.
DECODE_SETTLE_MS = 70

#: Retry delay if the first snapshot arrived before the frame was ready.
SNAPSHOT_RETRY_MS = 90

#: Watchdog for a snapshot that libVLC accepted but whose SnapshotTaken event
#: never arrives. Without it the chain would hang with no timer running.
SNAPSHOT_EVENT_TIMEOUT_MS = 600

#: Chain phases, tracked in ``self._step``.
_STEP_SETTLE = "settle"     # seeked; waiting for the decoder to produce the frame
_STEP_RETRY = "retry"       # snapshot failed; one retry is armed
_STEP_WAIT = "wait-event"   # snapshot accepted; waiting for SnapshotTaken (or watchdog)

#: The hidden player's libVLC options. Mirrors the main engine's BASE_VLC_ARGS
#: (same decode policy), minus the vmem callbacks, plus a dummy vout and no
#: audio. `--vout=dummy` is what makes `video_take_snapshot` work headless.
SCRUB_VLC_ARGS = [
    "--no-xlib",
    "--quiet",
    "--intf=dummy",
    "--no-video-title-show",
    "--avcodec-threads=0",
    "--no-snapshot-preview",
    "--no-stats",
    "--no-osd",
    "--avcodec-hw=none",
    "--vout=dummy",
    "--no-audio",
]

#: Snapshot PNGs rotate between these two names so QML's image cache always
#: sees a fresh URL (it would otherwise serve the stale cached frame).
_TMP_DIR_NAME = "halcyon-scrub"


class ScrubPreview(QObject):
    """Hidden headless decoder that snapshots one video frame on request."""

    #: Emitted when a snapshot is written: ``file://`` URL of the PNG, or
    #: ``""`` when the preview was cleared (media stopped/changed).
    snapshotReady = Signal(str)

    #: False while the decoder cannot serve frames (libVLC failure, non-file
    #: MRL, audio-only media). The popup hides on this.
    availableChanged = Signal(bool)

    #: True once the current media is loaded and the dummy vout is up.
    readyChanged = Signal(bool)

    # Internal, VLC-thread → GUI-thread hops. Qt queues delivery to the GUI
    # thread automatically because the emitting thread is not the receiver's.
    _playing = Signal()
    _failed = Signal()
    _shot_taken = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vlc = None
        self._instance = None
        self._player = None
        self._media = None
        self._event_manager = None
        #: Hard references to event callbacks — §9, High. A ctypes trampoline
        #: that is garbage collected while libVLC still holds its address
        #: crashes the process with no traceback.
        self._event_callbacks: list = []
        self._event_wiring: list = []

        self._mrl = ""
        self._available = False
        self._ready = False
        self._position_ms = 0
        self._pending_ms: int | None = None
        self._chain_active = False
        self._step = _STEP_SETTLE
        #: Retries left for the current seek's snapshot attempt. Capped so a
        #: file whose frames cannot be snapshotted cannot spin the chain
        #: forever (see ``_on_step``).
        self._retries_left = 0
        self._snapshot_index = 0
        self._snapshot_path: Path | None = None

        self._tmp_dir = Path(tempfile.gettempdir()) / _TMP_DIR_NAME

        #: Single driver for the seek→settle→snapshot chain.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_step)

        self._playing.connect(self._on_playing_gui)
        self._failed.connect(self._on_failed_gui)
        self._shot_taken.connect(self._on_shot_taken_gui)

    # ------------------------------------------------------------ public ---
    @Slot(str)
    def set_source(self, mrl: str) -> None:
        """Point the hidden decoder at ``mrl`` (``file://`` only).

        Called by the engine whenever media changes. An empty string, a
        network URL, or a media without a video track all leave the decoder
        unavailable; the popup stays hidden for those.
        """
        mrl = mrl or ""
        if mrl == self._mrl:
            return
        had_media = bool(self._mrl)
        self._mrl = mrl

        # Cancel any in-flight chain; nothing it produces is wanted any more.
        self._pending_ms = None
        self._chain_active = False
        self._retries_left = 0
        self._step = _STEP_SETTLE
        self._snapshot_path = None
        self._timer.stop()
        # Drop the stale frame immediately — the popup must never show the
        # previous file's picture while the new one loads. Only when there
        # WAS a previous media: the very first load has nothing to clear.
        if had_media:
            self.snapshotReady.emit("")

        if not mrl or urlparse(mrl).scheme != "file":
            self._release_media()
            self._set_ready(False)
            return

        self._release_media()
        self._set_ready(False)
        if not self._ensure_instance():
            return

        try:
            media = self._instance.media_new(mrl)
            if media is None:
                log.debug("scrub preview: media_new failed for %s", mrl)
                return
            # The player owns the media once set; release our local refcount
            # (same contract as VlcEngine.open: set_media then release).
            self._player.set_media(media)
            try:
                media.release()
            except Exception:
                log.debug("scrub preview: media.release failed", exc_info=True)
            self._player.play()
        except Exception:
            log.debug("scrub preview: could not load %s", mrl, exc_info=True)
            self._set_ready(False)

    @Slot(int)
    def request(self, ms: int) -> None:
        """Request a frame at ``ms`` (milliseconds). Coalesced — see module doc.

        Safe to call at pointer-move rate; a chain already in flight simply
        adopts the newest position when it next steps.
        """
        if not self._mrl:
            return
        try:
            ms = max(0, int(ms))
        except (TypeError, ValueError):
            return
        self._pending_ms = ms
        if not self._ready or self._chain_active:
            return  # served by _on_playing_gui / by the active chain's next step
        self._start_chain()

    @Slot()
    def reset(self) -> None:
        """Drop the current media and clear the preview (engine stop path)."""
        self.set_source("")

    def shutdown(self) -> None:
        """Release the hidden decoder in §9 order. Never raises."""
        self._timer.stop()
        self._pending_ms = None
        self._chain_active = False
        self._retries_left = 0
        self._step = _STEP_SETTLE
        self._snapshot_path = None
        self._mrl = ""
        self._set_ready(False)
        self._set_available(False)

        player = self._player
        if player is not None:
            try:
                player.stop()
                import time

                deadline = 1500
                waited = 0
                while waited < deadline:
                    try:
                        state = getattr(player.get_state(), "value", None)
                        if state in (0, 5, 6, 7):  # _SETTLED_STATES
                            break
                    except Exception:
                        break
                    time.sleep(0.02)
                    waited += 20
            except Exception:
                log.debug("scrub preview: stop during shutdown failed", exc_info=True)
            self._detach_events()
            try:
                player.release()
            except Exception:
                log.debug("scrub preview: player.release failed", exc_info=True)
            self._player = None
        self._release_media()
        if self._instance is not None:
            try:
                self._instance.release()
            except Exception:
                log.debug("scrub preview: instance.release failed", exc_info=True)
            self._instance = None

        # Best-effort temp cleanup. Rotating names make a stale file harmless,
        # but there is no reason to litter %TEMP%.
        try:
            for png in self._tmp_dir.glob("scrub_*.png"):
                png.unlink(missing_ok=True)
            self._tmp_dir.rmdir()
        except OSError:
            pass

    # ----------------------------------------------------- availability ---
    # Qt properties (not plain ``@property``): QML reads these through the
    # meta-object, and the notify signals are what re-evaluate the popup's
    # bindings when the decoder's state flips.
    @Property(bool, notify=availableChanged)
    def available(self) -> bool:
        """The decoder can serve frames at all (libVLC up, instance created)."""
        return self._available

    @Property(bool, notify=readyChanged)
    def ready(self) -> bool:
        """The current media is loaded and its dummy vout is running."""
        return self._ready

    # ---------------------------------------------------------- internal ---
    def _set_available(self, value: bool) -> None:
        if value == self._available:
            return
        self._available = value
        self.availableChanged.emit(value)

    def _set_ready(self, value: bool) -> None:
        if value == self._ready:
            return
        self._ready = value
        self.readyChanged.emit(value)

    def _ensure_instance(self) -> bool:
        """Create the hidden libVLC instance on first use. Never raises."""
        if self._instance is not None:
            return True
        try:
            import vlc  # noqa: PLC0415 - lazy: engine modules stay importable without libVLC

            self._vlc = vlc
            instance = vlc.Instance(SCRUB_VLC_ARGS)
            if instance is None:
                log.debug("scrub preview: libVLC instance failed")
                self._set_available(False)
                return False
            self._instance = instance
            self._player = instance.media_player_new()
            self._attach_events()
            self._set_available(True)
            return True
        except Exception:
            log.debug("scrub preview: init failed", exc_info=True)
            self._set_available(False)
            return False

    # ------------------------------------------------------------- events ---
    def _attach_events(self) -> None:
        vlc = self._vlc
        try:
            em = self._player.event_manager()
        except Exception:
            log.debug("scrub preview: no event manager", exc_info=True)
            return
        self._event_manager = em
        wiring = [
            (vlc.EventType.MediaPlayerPlaying, self._on_state_event),
            (vlc.EventType.MediaPlayerEncounteredError, self._on_error),
            (vlc.EventType.MediaPlayerSnapshotTaken, self._on_snapshot_taken),
        ]
        for event_type, handler in wiring:
            try:
                em.event_attach(event_type, handler)
            except Exception:
                log.debug(
                    "scrub preview: event_attach %s failed", event_type, exc_info=True
                )
                continue
            self._event_callbacks.append(handler)
            self._event_wiring.append((event_type, handler))

    def _detach_events(self) -> None:
        em = self._event_manager
        if em is None:
            return
        for event_type, _handler in self._event_wiring:
            try:
                # python-vlc detaches by type only (see VlcEngine._detach_events).
                em.event_detach(event_type)
            except Exception:
                log.debug(
                    "scrub preview: event_detach %s failed", event_type, exc_info=True
                )
        self._event_wiring = []
        self._event_manager = None

    # Every one of these runs on a *VLC* thread: emit and get out (the
    # engine's own docstring rule — Qt queues delivery to the GUI thread).
    def _on_state_event(self, _event) -> None:
        self._playing.emit()

    def _on_error(self, _event) -> None:
        self._failed.emit()

    def _on_snapshot_taken(self, event) -> None:
        try:
            filename = event.u.snapshot_taken.filename or b""
            if isinstance(filename, bytes):
                filename = filename.decode("utf-8", errors="replace")
        except Exception:
            filename = ""
        self._shot_taken.emit(filename)

    def _release_media(self) -> None:
        """Detach the previous media in the libVLC-safe order (engine §9)."""
        media = self._media
        self._media = None
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                log.debug("scrub preview: stop failed", exc_info=True)
            try:
                self._player.set_media(None)
            except Exception:
                log.debug("scrub preview: set_media(None) failed", exc_info=True)
        if media is not None:
            try:
                media.release()
            except Exception:
                log.debug("scrub preview: media.release failed", exc_info=True)

    # ---------------------------------------------------------- the chain ---
    def _start_chain(self) -> None:
        """Begin seek→settle→snapshot at the newest pending position."""
        self._chain_active = True
        self._step = _STEP_SETTLE
        self._seek_to_pending()
        self._timer.start(DECODE_SETTLE_MS)

    def _seek_to_pending(self) -> None:
        if self._pending_ms is None or self._player is None:
            return
        try:
            self._player.set_time(self._pending_ms)
            self._position_ms = self._pending_ms
            # A fresh seek deserves a fresh pair of snapshot attempts.
            self._retries_left = 1
        except Exception:
            log.debug("scrub preview: seek failed", exc_info=True)

    def _take_snapshot(self) -> bool:
        """Write the next rotating PNG. True if libVLC accepted the request."""
        if self._player is None:
            return False
        self._snapshot_index = 1 - self._snapshot_index
        path = self._tmp_dir / f"scrub_{self._snapshot_index}.png"
        try:
            self._tmp_dir.mkdir(parents=True, exist_ok=True)
            rc = self._player.video_take_snapshot(0, str(path), SNAPSHOT_WIDTH, 0)
            if rc == 0:
                self._snapshot_path = path
                return True
        except Exception:
            log.debug("scrub preview: snapshot failed", exc_info=True)
        return False

    def _on_step(self) -> None:
        """Timer step: settle elapsed → snapshot; or watchdog for the event."""
        if not self._chain_active or not self._ready or self._player is None:
            self._chain_active = False
            self._timer.stop()
            return

        if self._step in (_STEP_SETTLE, _STEP_RETRY):
            if not self._take_snapshot():
                # The frame may not have been decoded yet — one retry, then
                # give up this round rather than spin. A fresh request()
                # restarts the chain with a fresh retry budget.
                if self._retries_left > 0:
                    self._retries_left -= 1
                    self._step = _STEP_RETRY
                    self._timer.start(SNAPSHOT_RETRY_MS)
                else:
                    self._pending_ms = None
                    self._chain_active = False
                    self._timer.stop()
                return
            # Accepted. The SnapshotTaken event normally finishes the chain;
            # the timer is re-armed as a watchdog in case that event never
            # arrives (a broken libVLC must not hang the chain forever).
            self._step = _STEP_WAIT
            self._timer.start(SNAPSHOT_EVENT_TIMEOUT_MS)
            return

        # _STEP_WAIT and the watchdog fired: the event never arrived. Publish
        # the file if libVLC did write it anyway, then rest the chain.
        self._timer.stop()
        if self._snapshot_path is not None and self._snapshot_path.exists():
            self.snapshotReady.emit(
                QUrl.fromLocalFile(str(self._snapshot_path)).toString()
            )
        self._pending_ms = None
        self._chain_active = False

    # --------------------------------------------------- GUI-thread sinks ---
    def _on_shot_taken_gui(self, path: str) -> None:
        """SnapshotTaken delivered on the GUI thread — finish the chain.

        ``path`` must match the snapshot we last requested. Events from a
        *previous* request (or the previous media) are stale — their file may
        not even exist any more (rotating names), so publishing them would
        show the wrong frame or a broken image. Ignore them entirely; the
        event for the current request is still coming.
        """
        if self._snapshot_path is None:
            return  # nothing requested since the last clear — stale event
        if os.path.normcase(str(self._snapshot_path)) != os.path.normcase(path):
            return  # belongs to an older request (rotated file) — stale
        self._timer.stop()  # the watchdog is not needed — the event arrived
        self.snapshotReady.emit(QUrl.fromLocalFile(str(self._snapshot_path)).toString())

        if self._pending_ms is not None and self._pending_ms != self._position_ms:
            # A newer request arrived while this snapshot was in flight.
            self._seek_to_pending()
            self._step = _STEP_SETTLE
            self._timer.start(DECODE_SETTLE_MS)
            return
        self._pending_ms = None
        self._chain_active = False

    def _on_playing_gui(self) -> None:
        """Playing delivered on the GUI thread — pause and serve requests."""
        if not self._mrl:
            return
        try:
            if self._player is None or self._player.has_vout() <= 0:
                # Audio-only media (or a file whose video track failed to
                # open): nothing to preview.
                self._set_ready(False)
                return
        except Exception:
            log.debug("scrub preview: has_vout failed", exc_info=True)
            self._set_ready(False)
            return
        self._set_ready(True)
        try:
            self._player.pause()  # hold the first frame; decoding idles
        except Exception:
            log.debug("scrub preview: pause failed", exc_info=True)
        if self._pending_ms is not None:
            self._start_chain()

    def _on_failed_gui(self) -> None:
        self._set_ready(False)
