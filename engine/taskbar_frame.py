"""Thread-safe latest decoded frame cache for Windows taskbar previews.

The cache owns its pixels.  It never exposes a libVLC/FrameRing address after
its callback returns, because libVLC is free to reuse that address for a later
decode.  It is intentionally usable without Qt or Windows for unit tests.
"""
from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.video_out import FrameFormat


@dataclass(frozen=True, slots=True)
class TaskbarFrame:
    """A complete owned decoded frame and the negotiated vmem metadata."""
    pixels: bytes
    chroma: str
    width: int
    height: int
    y_pitch: int
    y_lines: int
    uv_pitch: int = 0
    uv_lines: int = 0
    frame_id: int = 0
    timestamp_ns: int = 0

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0


class LatestTaskbarFrameCache:
    """One-frame, rate-limited cache fed only by the Soft display callback.

    Copying a full decoded 4K image every decode callback would be needless
    work for a thumbnail.  The caller enables capture only while minimized;
    while enabled copies are limited to ``interval_ns`` (default 7.5 FPS).
    The lock protects reference publication only, never a pixel copy.
    """
    def __init__(self, interval_ns: int = 133_000_000) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._latest: TaskbarFrame | None = None
        self._last_capture_ns = 0
        self._frame_id = 0
        self._interval_ns = interval_ns

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            # A newly minimized window should receive the next decoded frame,
            # rather than waiting a whole cadence interval.
            if enabled:
                self._last_capture_ns = 0

    def latest(self) -> TaskbarFrame | None:
        # TaskbarFrame is immutable and owns bytes, so returning the reference
        # is safe and does not retain any FrameRing/VLC memory.
        with self._lock:
            return self._latest

    def clear(self) -> None:
        with self._lock:
            self._latest = None
            self._last_capture_ns = 0

    def capture(self, address: int, fmt: "FrameFormat", serial: int) -> None:
        """Copy a fully displayed Soft frame; called on VLC's callback thread."""
        if not address or fmt is None:
            return
        now = time.monotonic_ns()
        with self._lock:
            if not self._enabled or now - self._last_capture_ns < self._interval_ns:
                return
        try:
            # string_at makes an independent immutable copy before this method
            # publishes it; no caller can ever see a reusable libVLC buffer.
            pixels = ctypes.string_at(address, fmt.frame_size)
        except Exception:
            return
        frame = TaskbarFrame(
            pixels=pixels, chroma=fmt.chroma, width=fmt.width, height=fmt.height,
            y_pitch=fmt.y_pitch, y_lines=fmt.y_lines, uv_pitch=fmt.uv_pitch,
            uv_lines=fmt.uv_lines, frame_id=int(serial), timestamp_ns=now,
        )
        with self._lock:
            # Disable can race this callback during restore.  Keeping the last
            # owned frame is harmless, but do not publish a new one afterwards.
            if not self._enabled:
                return
            self._latest = frame
            self._last_capture_ns = now
