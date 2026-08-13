"""Taskbar live preview when minimized — Windows only.

When the window is visible, DWM shows live video automatically (Qt keeps
rendering). When minimized Qt pauses its render loop to save GPU, so the
taskbar thumbnail becomes a still image — the last cached bitmap.

This module enables DWM's iconic bitmap mode and supplies a fresh frame on
demand:

* DwmSetWindowAttribute(DWMWA_HAS_ICONIC_BITMAP, TRUE)
* DwmSetWindowAttribute(DWMWA_FORCE_ICONIC_REPRESENTATION, TRUE)
* Native event filter for WM_DWMSENDICONICTHUMBNAIL / WM_DWMSENDICONICLIVE
* On each request: snapshot current frame via libVLC video_take_snapshot
  (Soft and Turbo both go through the same main player) -> BMP -> HBITMAP
  -> DwmSetIconicThumbnail / DwmSetIconicLivePreviewBitmap

No second player, no continuous playback behind. Snapshot is taken only
when Windows asks (hover) and is throttled by a 120ms invalidate timer
while minimized + playing.

Safe by design:
* Off Windows: is_supported() == False, module does nothing.
* Any DWM call failure -> falls back to default Windows thumbnail.
* All Win32 calls guarded, never raises to Qt.
* Filter installed on QApplication, removed on shutdown.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Platform guard
# ----------------------------------------------------------------------

def is_supported() -> bool:
    return sys.platform == "win32"


if not is_supported():
    # Dummy API so main.py can import unconditionally on Linux/macOS
    class TaskbarLivePreview:  # type: ignore
        def __init__(self, *a, **kw):
            pass
        def shutdown(self):
            pass
        @property
        def hwnd(self):
            return 0
        def _create_hbitmap(self, *a, **kw):
            return 0
else:
    from ctypes import wintypes

    # Windows messages
    WM_DWMSENDICONICTHUMBNAIL = 0x0323
    WM_DWMSENDICONICLIVE = 0x0326

    # DWM attributes
    DWMWA_HAS_ICONIC_BITMAP = 10
    DWMWA_FORCE_ICONIC_REPRESENTATION = 7

    # LoadImage flags
    IMAGE_BITMAP = 0
    LR_LOADFROMFILE = 0x10
    LR_CREATEDIBSECTION = 0x2000

    DWM_SIT_DISPLAYFRAME = 0x00000001

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", POINT),
            ("lPrivate", wintypes.DWORD),
        ]

    # Load DLLs once
    try:
        dwmapi = ctypes.windll.dwmapi
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

        dwmapi.DwmSetIconicThumbnail.argtypes = [
            wintypes.HWND, wintypes.HBITMAP, wintypes.DWORD
        ]
        dwmapi.DwmSetIconicThumbnail.restype = ctypes.c_long

        dwmapi.DwmSetIconicLivePreviewBitmap.argtypes = [
            wintypes.HWND, wintypes.HBITMAP, ctypes.POINTER(POINT), wintypes.DWORD
        ]
        dwmapi.DwmSetIconicLivePreviewBitmap.restype = ctypes.c_long

        dwmapi.DwmInvalidateIconicBitmaps.argtypes = [wintypes.HWND]
        dwmapi.DwmInvalidateIconicBitmaps.restype = ctypes.c_long

        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            wintypes.INT, wintypes.INT, wintypes.UINT
        ]
        user32.LoadImageW.restype = wintypes.HANDLE

        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteObject.restype = wintypes.BOOL

        _WIN32_OK = True
    except Exception:
        log.debug("taskbar preview: win32 API setup failed", exc_info=True)
        _WIN32_OK = False

    # ------------------------------------------------------------------
    # Helper: snapshot -> HBITMAP
    # ------------------------------------------------------------------

    def _snapshot_to_hbitmap(player, width_hint: int = 0, height_hint: int = 0):
        """Use main libVLC player to take a BMP snapshot, load as HBITMAP.

        Returns HBITMAP handle or 0 on failure. Caller must DeleteObject().
        Snap is short-lived, no second player.
        """
        if not _WIN32_OK:
            return 0
        if player is None:
            return 0
        raw = getattr(player, "raw_player", None) or getattr(player, "_player", None)
        if raw is None:
            return 0
        # Only when media is loaded
        try:
            cur = getattr(player, "currentMedia", "")
            if not cur:
                return 0
        except Exception:
            pass

        # Clamp hint to reasonable live-preview size. 0 = original, but we
        # want small to keep it fast. Windows will scale anyway.
        w = int(width_hint) if width_hint > 0 else 320
        h = int(height_hint) if height_hint > 0 else 180
        # Don't ask for huge - cap
        w = min(w, 480)
        h = min(h, 270)
        if w < 32 or h < 32:
            w, h = 320, 180

        tmp_dir = Path(tempfile.gettempdir()) / "halcyon_taskbar"
        try:
            tmp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            tmp_dir = Path(tempfile.gettempdir())

        bmp_path = tmp_dir / f"live_{os.getpid()}.bmp"

        try:
            # video_take_snapshot returns 0 on success
            # Signature: video_take_snapshot(num, filepath, width, height)
            # Use 0 = first video track
            setter = getattr(raw, "video_take_snapshot", None)
            if not callable(setter):
                return 0
            # Remove old file first
            try:
                if bmp_path.exists():
                    bmp_path.unlink()
            except Exception:
                pass

            res = setter(0, str(bmp_path), w, h)
            if res != 0:
                return 0
            if not bmp_path.exists() or bmp_path.stat().st_size == 0:
                return 0

            # Load as DIB section HBITMAP
            hbm = user32.LoadImageW(
                None,
                str(bmp_path),
                IMAGE_BITMAP,
                0, 0,
                LR_LOADFROMFILE | LR_CREATEDIBSECTION,
            )
            return int(hbm or 0)
        except Exception:
            log.debug("taskbar snapshot failed", exc_info=True)
            return 0
        finally:
            # Clean file after load attempt, DWM already has its own copy
            # after LoadImage, file not needed. Keep deletion best-effort.
            try:
                if bmp_path.exists():
                    bmp_path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Native event filter
    # ------------------------------------------------------------------

    from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer

    class _TaskbarFilter(QAbstractNativeEventFilter):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        def nativeEventFilter(self, eventType, message):
            # eventType is QByteArray, message is void* to MSG
            try:
                if not eventType:
                    return False, 0
                et = bytes(eventType).decode(errors="ignore") if hasattr(eventType, "data") else str(eventType)
                if "windows" not in et.lower():
                    return False, 0

                msg_ptr = ctypes.cast(int(message), ctypes.POINTER(MSG))
                msg = msg_ptr.contents
                hwnd = int(msg.hwnd or 0)
                if hwnd == 0:
                    return False, 0
                if hwnd != self._owner.hwnd:
                    return False, 0

                if msg.message == WM_DWMSENDICONICTHUMBNAIL:
                    # lParam holds max size: loword width, hiword height
                    lparam = int(msg.lParam or 0)
                    max_w = lparam & 0xFFFF
                    max_h = (lparam >> 16) & 0xFFFF
                    hbm = self._owner._create_hbitmap(max_w, max_h)
                    if hbm:
                        try:
                            dwmapi.DwmSetIconicThumbnail(msg.hwnd, hbm, 0)
                        except Exception:
                            log.debug("DwmSetIconicThumbnail failed", exc_info=True)
                        try:
                            gdi32.DeleteObject(hbm)
                        except Exception:
                            pass
                        return True, 0
                    return False, 0

                if msg.message == WM_DWMSENDICONICLIVE:
                    hbm = self._owner._create_hbitmap(0, 0)
                    if hbm:
                        try:
                            pt = POINT(0, 0)
                            dwmapi.DwmSetIconicLivePreviewBitmap(msg.hwnd, hbm, ctypes.byref(pt), DWM_SIT_DISPLAYFRAME)
                        except Exception:
                            log.debug("DwmSetIconicLivePreviewBitmap failed", exc_info=True)
                        try:
                            gdi32.DeleteObject(hbm)
                        except Exception:
                            pass
                        return True, 0
                    return False, 0

            except Exception:
                log.debug("taskbar filter exception", exc_info=True)
            return False, 0

    # ------------------------------------------------------------------
    # Main controller
    # ------------------------------------------------------------------

    class TaskbarLivePreview(QObject):
        """Enable live iconic preview when minimized."""

        def __init__(self, engine, window, parent=None):
            super().__init__(parent)
            self._engine = engine
            self._window = window
            self._hwnd = 0
            self._filter = None
            self._enabled = False
            self._invalidate_timer = QTimer(self)
            self._invalidate_timer.setInterval(120)  # ~8 fps live
            self._invalidate_timer.timeout.connect(self._on_invalidate_tick)

            if not _WIN32_OK:
                log.info("taskbar preview disabled: win32 API not available")
                return

            # Try to enable after window gets a handle
            QTimer.singleShot(300, self._try_enable)

        @property
        def hwnd(self) -> int:
            return self._hwnd

        def _try_enable(self):
            if self._enabled:
                return
            try:
                win = self._window
                if win is None:
                    return
                # winId may be 0 until window is exposed
                wid = int(win.winId() or 0)
                if wid == 0:
                    QTimer.singleShot(250, self._try_enable)
                    return
                self._hwnd = wid
                self._enable_iconic()
            except Exception:
                log.debug("taskbar _try_enable failed", exc_info=True)

        def _enable_iconic(self):
            if self._hwnd == 0 or self._enabled:
                return
            try:
                hwnd = wintypes.HWND(self._hwnd)
                true_val = ctypes.c_int(1)
                # HAS_ICONIC_BITMAP
                hr1 = dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_HAS_ICONIC_BITMAP,
                    ctypes.byref(true_val),
                    ctypes.sizeof(true_val),
                )
                # FORCE_ICONIC_REPRESENTATION
                hr2 = dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_FORCE_ICONIC_REPRESENTATION,
                    ctypes.byref(true_val),
                    ctypes.sizeof(true_val),
                )
                if hr1 == 0 and hr2 == 0:
                    self._enabled = True
                    log.info("taskbar live preview enabled (hwnd=%s)", self._hwnd)
                    # Install filter
                    try:
                        from PySide6.QtGui import QGuiApplication
                        app = QGuiApplication.instance()
                        if app is not None:
                            self._filter = _TaskbarFilter(self)
                            app.installNativeEventFilter(self._filter)
                            # Keep ref alive via _filter
                    except Exception:
                        log.debug("installing native filter failed", exc_info=True)

                    # Start invalidation when playing+minimized
                    self._invalidate_timer.start()

                    # Watch visibility to know minimized state
                    try:
                        self._window.visibilityChanged.connect(self._on_visibility_changed)
                    except Exception:
                        pass
                else:
                    log.info("DwmSetWindowAttribute failed hr1=%s hr2=%s", hr1, hr2)
            except Exception:
                log.debug("taskbar _enable_iconic failed", exc_info=True)

        def _on_visibility_changed(self, vis):
            # Optional: invalidate immediately when minimizing to refresh
            try:
                from PySide6.QtGui import QWindow
                if vis == QWindow.Visibility.Minimized:
                    self._invalidate_once()
            except Exception:
                pass

        def _is_minimized(self) -> bool:
            try:
                win = self._window
                if win is None:
                    return False
                from PySide6.QtGui import QWindow
                return win.visibility() == QWindow.Visibility.Minimized
            except Exception:
                return False

        def _is_playing(self) -> bool:
            try:
                eng = self._engine
                if eng is None:
                    return False
                return bool(getattr(eng, "isPlaying", False))
            except Exception:
                return False

        def _on_invalidate_tick(self):
            # Only invalidate when minimized and playing video
            try:
                if not self._enabled or self._hwnd == 0:
                    return
                if not self._is_minimized():
                    return
                if not self._is_playing():
                    return
                # Tell DWM preview is dirty -> it will send WM_DWMSEND... messages
                dwmapi.DwmInvalidateIconicBitmaps(wintypes.HWND(self._hwnd))
            except Exception:
                pass

        def _invalidate_once(self):
            try:
                if self._enabled and self._hwnd:
                    dwmapi.DwmInvalidateIconicBitmaps(wintypes.HWND(self._hwnd))
            except Exception:
                pass

        def _create_hbitmap(self, max_w: int, max_h: int):
            # Use snapshot from main player - works for Soft and Turbo
            # Soft: vmem snapshot, Turbo: HWND snapshot
            try:
                if not self._is_playing():
                    return 0
                # ignore max_w/h for live bitmap, use small fixed
                w = max_w if 80 <= max_w <= 480 else 320
                h = max_h if 80 <= max_h <= 270 else 180
                return _snapshot_to_hbitmap(self._engine, w, h)
            except Exception:
                log.debug("create_hbitmap failed", exc_info=True)
                return 0

        def shutdown(self):
            try:
                self._invalidate_timer.stop()
            except Exception:
                pass
            # Remove iconic attribute to restore default behavior
            try:
                if self._hwnd and _WIN32_OK:
                    hwnd = wintypes.HWND(self._hwnd)
                    false_val = ctypes.c_int(0)
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_HAS_ICONIC_BITMAP,
                        ctypes.byref(false_val), ctypes.sizeof(false_val)
                    )
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_FORCE_ICONIC_REPRESENTATION,
                        ctypes.byref(false_val), ctypes.sizeof(false_val)
                    )
            except Exception:
                pass
            # Filter removal - Qt has no uninstall, but dropping ref is enough
            # as app is quitting
            self._filter = None
            log.info("taskbar preview shutdown")
