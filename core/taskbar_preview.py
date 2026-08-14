"""Taskbar live preview when minimized — Windows only.

When the window is visible, DWM shows live video automatically (Qt keeps
rendering). When minimized Qt pauses its render loop to save GPU, so the
taskbar thumbnail becomes a still image — the last cached bitmap.

This module enables DWM's iconic bitmap mode and supplies a fresh frame on
demand:

* Enable DWMWA_FORCE_ICONIC_REPRESENTATION and DWMWA_HAS_ICONIC_BITMAP only
  while the window is minimized, returning to normal DWM composition on restore.
* Native event filter for WM_DWMSENDICONICTHUMBNAIL / WM_DWMSENDICONICLIVE
* On each request: convert the latest owned Soft/vmem decoded frame directly
  to a DIB-section HBITMAP. If no frame has arrived, return a valid neutral
  bitmap rather than leaving DWM waiting.
  -> DwmSetIconicThumbnail / DwmSetIconicLivePreviewBitmap

No second player, no window capture, and no snapshot files. Soft copying is
enabled only while minimized and is rate-limited; DWM invalidation is ~8 FPS.

Safe by design:
* Off Windows: is_supported() == False, module does nothing.
* A valid fallback bitmap is returned for every DWM request while iconic mode
  is active, so DWM never displays a blank, pending thumbnail.
* All Win32 calls guarded, never raises to Qt.
* Filter installed on QApplication, removed on shutdown.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from core.taskbar_pixels import preview_bgra

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
    DWMWA_FORCE_ICONIC_REPRESENTATION = 7
    DWMWA_HAS_ICONIC_BITMAP = 10

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

        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.CreateBitmap.argtypes = [wintypes.INT, wintypes.INT, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        gdi32.CreateBitmap.restype = wintypes.HBITMAP

        _WIN32_OK = True
    except Exception:
        log.debug("taskbar preview: win32 API setup failed", exc_info=True)
        _WIN32_OK = False

    # ------------------------------------------------------------------
    # Helper: owned decoded pixels -> HBITMAP
    # ------------------------------------------------------------------

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]

    BI_RGB = 0
    DIB_RGB_COLORS = 0

    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP

    def _bgra_to_hbitmap(pixels: bytes, width: int, height: int) -> int:
        """Create a top-down 32-bit DIB whose storage receives owned BGRA."""
        if not _WIN32_OK or width <= 0 or height <= 0 or len(pixels) != width * height * 4:
            return 0
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # Negative height is a top-down DIB: exactly the row order generated
        # by preview_bgra, avoiding an extra flip/copy.
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = len(pixels)
        bits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(None, ctypes.byref(info), DIB_RGB_COLORS,
                                     ctypes.byref(bits), None, 0)
        if not hbm or not bits.value:
            return 0
        try:
            ctypes.memmove(bits, pixels, len(pixels))
            return int(hbm)
        except Exception:
            gdi32.DeleteObject(hbm)
            return 0

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
                hwnd = int(msg.hwnd or 0) & 0xFFFFFFFFFFFFFFFF
                if hwnd == 0:
                    return False, 0
                owner_hwnd = self._owner.hwnd & 0xFFFFFFFFFFFFFFFF
                if hwnd != owner_hwnd and (hwnd & 0xFFFFFFFF) != (owner_hwnd & 0xFFFFFFFF):
                    return False, 0

                if msg.message == WM_DWMSENDICONICTHUMBNAIL:
                    # lParam holds max size: loword width, hiword height
                    lparam = int(msg.lParam or 0)
                    max_w = lparam & 0xFFFF
                    max_h = (lparam >> 16) & 0xFFFF
                    hbm = self._owner._create_hbitmap(max_w, max_h)
                    if not hbm:
                        return False, 0
                    try:
                        # DWM copies the bitmap during this call. Always reply
                        # while iconic mode is enabled; otherwise it displays
                        # the white pending-thumbnail spinner.
                        hr = dwmapi.DwmSetIconicThumbnail(msg.hwnd, hbm, 0)
                        log.debug("DwmSetIconicThumbnail -> hr=%s", hr)
                    except Exception:
                        log.debug("DwmSetIconicThumbnail failed", exc_info=True)
                    finally:
                        try:
                            gdi32.DeleteObject(hbm)
                        except Exception:
                            pass
                    return True, 0

                if msg.message == WM_DWMSENDICONICLIVE:
                    hbm = self._owner._create_hbitmap(0, 0)
                    if not hbm:
                        return False, 0
                    try:
                        pt = POINT(0, 0)
                        hr = dwmapi.DwmSetIconicLivePreviewBitmap(msg.hwnd, hbm, ctypes.byref(pt), DWM_SIT_DISPLAYFRAME)
                        log.debug("DwmSetIconicLivePreviewBitmap -> hr=%s", hr)
                    except Exception:
                        log.debug("DwmSetIconicLivePreviewBitmap failed", exc_info=True)
                    finally:
                        try:
                            gdi32.DeleteObject(hbm)
                        except Exception:
                            pass
                    return True, 0

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
            if self._hwnd != 0:
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
                self._hwnd = wid & 0xFFFFFFFFFFFFFFFF
                self._install_filter()
                try:
                    self._window.visibilityChanged.connect(self._on_visibility_changed)
                except Exception:
                    pass
                try:
                    if hasattr(self._window, "windowStateChanged"):
                        self._window.windowStateChanged.connect(self._on_visibility_changed)
                except Exception:
                    pass
                # The timer itself is cheap; it only invalidates while the
                # window is minimized and playback is active.
                self._invalidate_timer.start()
                # Do not claim iconic ownership while the window is visible.
                # That is what previously replaced normal-mode live preview.
                self._on_visibility_changed()
            except Exception:
                log.debug("taskbar _try_enable failed", exc_info=True)

        def _set_iconic_mode(self, enabled: bool):
            """Enable custom DWM bitmaps only for the minimized window.

            The visible window must remain on DWM's default composition path;
            it is the only reliable live preview for both render backends.
            """
            if self._hwnd == 0:
                return
            try:
                value = ctypes.c_int(1 if enabled else 0)
                hr_force = dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(self._hwnd), DWMWA_FORCE_ICONIC_REPRESENTATION,
                    ctypes.byref(value), ctypes.sizeof(value),
                )
                hr_has = dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(self._hwnd), DWMWA_HAS_ICONIC_BITMAP,
                    ctypes.byref(value), ctypes.sizeof(value),
                )
                self._enabled = (hr_force == 0 and hr_has == 0 and enabled)
                log.info(
                    "DWM iconic mode set: enabled=%s (force_hr=%s, has_hr=%s)",
                    enabled, hr_force, hr_has
                )
            except Exception:
                self._enabled = False
                log.debug("taskbar _set_iconic_mode failed", exc_info=True)

        def _install_filter(self):
            if self._filter is not None:
                return
            try:
                from PySide6.QtGui import QGuiApplication
                app = QGuiApplication.instance()
                if app is not None:
                    self._filter = _TaskbarFilter(self)
                    app.installNativeEventFilter(self._filter)
            except Exception:
                log.debug("installing native filter failed", exc_info=True)

        def _on_visibility_changed(self, *args):
            try:
                minimized = self._is_minimized()
                # The engine only feeds this cache from its Soft/vmem callback
                # path. Turbo intentionally yields None; do not capture a
                # potentially stale native child HWND.
                setter = getattr(self._engine, "set_taskbar_frame_capture_enabled", None)
                if callable(setter):
                    setter(minimized)
                self._set_iconic_mode(minimized)
                if minimized:
                    self._invalidate_once()
            except Exception:
                log.debug("taskbar visibility change failed", exc_info=True)

        def _is_minimized(self) -> bool:
            try:
                win = self._window
                if win is None:
                    return False
                from PySide6.QtGui import QWindow
                from PySide6.QtCore import Qt
                vis = win.visibility() if hasattr(win, "visibility") else None
                state = win.windowState() if hasattr(win, "windowState") else None
                return (vis == QWindow.Visibility.Minimized or
                        state == Qt.WindowState.WindowMinimized)
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
            # Live preview requests carry dimensions; WM_DWMSENDICONICLIVE does
            # not, so use a modest fixed bitmap and let DWM scale it.
            w = max_w if 80 <= max_w <= 480 else 320
            h = max_h if 80 <= max_h <= 270 else 180
            try:
                getter = getattr(self._engine, "latest_taskbar_frame", None)
                frame = getter() if callable(getter) else None
                if frame is not None:
                    pixels, out_w, out_h = preview_bgra(frame, w, h)
                    hbm = _bgra_to_hbitmap(pixels, out_w, out_h)
                    if hbm:
                        return hbm
            except Exception:
                log.debug("creating taskbar DIB from decoded frame failed", exc_info=True)
            # Once HAS_ICONIC_BITMAP is advertised DWM must always receive a
            # real HBITMAP. Opaque neutral black prevents its white spinner
            # during the gap before the first Soft decoded frame (and Turbo,
            # whose native output deliberately has no unsafe capture path).
            return _bgra_to_hbitmap(bytes((0, 0, 0, 255)) * (w * h), w, h)

        def shutdown(self):
            try:
                setter = getattr(self._engine, "set_taskbar_frame_capture_enabled", None)
                if callable(setter):
                    setter(False)
            except Exception:
                pass
            try:
                self._invalidate_timer.stop()
            except Exception:
                pass
            # Remove iconic attributes to restore default behavior
            try:
                if self._hwnd and _WIN32_OK:
                    hwnd = wintypes.HWND(self._hwnd)
                    false_val = ctypes.c_int(0)
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_FORCE_ICONIC_REPRESENTATION,
                        ctypes.byref(false_val), ctypes.sizeof(false_val)
                    )
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_HAS_ICONIC_BITMAP,
                        ctypes.byref(false_val), ctypes.sizeof(false_val)
                    )
            except Exception:
                pass
            try:
                from PySide6.QtGui import QGuiApplication
                app = QGuiApplication.instance()
                if app is not None and self._filter is not None:
                    app.removeNativeEventFilter(self._filter)
            except Exception:
                pass
            self._filter = None
            log.info("taskbar preview shutdown")
