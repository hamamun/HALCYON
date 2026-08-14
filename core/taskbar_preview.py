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

Bitmap sizing follows the DWM contract exactly:

* WM_DWMSENDICONICTHUMBNAIL carries the maximum accepted size as HIWORD =
  max width, LOWORD = max height (the opposite of the usual x/y order).
  Anything larger is rejected with E_INVALIDARG and DWM falls back to its
  white pending-spinner, so the thumbnail is rendered at exactly the
  requested size — never a fixed substitute.
* The live-preview (Peek) bitmap is drawn at the window's *restored* size
  (GetWindowPlacement), because DWM displays the Peek window at the
  bitmap's own size: a fixed small bitmap floats as a stray mini window,
  a window-sized one sits where the window itself lives. The expensive
  pure-Python conversion runs once on a small aspect-matched render and GDI
  stretches it to full size at C speed.

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


# ----------------------------------------------------------------------
# Bitmap sizing (pure helpers — unit-testable on every platform)
# ----------------------------------------------------------------------

# DWM's absolute ceiling for an iconic thumbnail bitmap.
_DWM_THUMBNAIL_MAX = 1024

# The live-preview source render never exceeds this many pixels on its long
# edge. The window-sized Peek bitmap is produced by a C-speed GDI stretch of
# this render, so this cap — not the window size — bounds the pure-Python
# YUV conversion cost on the GUI thread.
_LIVE_SOURCE_EDGE = 320


def fit_thumbnail_size(max_w: int, max_h: int) -> tuple[int, int]:
    """Target bitmap size for a WM_DWMSENDICONICTHUMBNAIL request.

    Per the WM_DWMSENDICONICTHUMBNAIL docs, HIWORD(lParam) is the maximum
    x-coordinate (width) and LOWORD(lParam) the maximum y-coordinate
    (height); a bitmap exceeding either is rejected with E_INVALIDARG. The only
    safe answer is a bitmap no larger than requested, so this clamps DOWN —
    never substituting a bigger default. (0, 0) means "no sane request; do
    not reply" and lets DWM fall back to its own representation.
    """
    max_w = int(max_w or 0)
    max_h = int(max_h or 0)
    if max_w <= 0 or max_h <= 0:
        return (0, 0)
    return (min(max_w, _DWM_THUMBNAIL_MAX), min(max_h, _DWM_THUMBNAIL_MAX))


def fit_live_source_size(win_w: int, win_h: int) -> tuple[int, int]:
    """Aspect-preserving render size for the live-preview source bitmap.

    The Peek bitmap must look like the window, so the source keeps the
    window's aspect and is only downscaled (never upscaled) to keep the
    pure-Python conversion cheap. Windows at or below the cap render 1:1.
    """
    win_w = int(win_w or 0)
    win_h = int(win_h or 0)
    if win_w <= 0 or win_h <= 0:
        return (0, 0)
    scale = min(1.0, _LIVE_SOURCE_EDGE / max(win_w, win_h))
    return (max(1, round(win_w * scale)), max(1, round(win_h * scale)))


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
        def _create_thumbnail(self, *a, **kw):
            return 0
        def _create_live_preview(self):
            return 0
else:
    from ctypes import wintypes

    # Windows messages
    WM_DWMSENDICONICTHUMBNAIL = 0x0323
    WM_DWMSENDICONICLIVE = 0x0326

    # DWM attributes
    DWMWA_FORCE_ICONIC_REPRESENTATION = 7
    DWMWA_HAS_ICONIC_BITMAP = 10

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.UINT),
            ("flags", wintypes.UINT),
            ("showCmd", wintypes.UINT),
            ("ptMinPosition", POINT),
            ("ptMaxPosition", POINT),
            ("rcNormalPosition", RECT),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    # A window minimised from maximised restores to the monitor work area,
    # not to rcNormalPosition (Win32 WINDOWPLACEMENT semantics).
    WPF_RESTORETOMAXIMIZED = 0x0002
    MONITOR_DEFAULTTONULL = 0
    HALFTONE = 4
    SRCCOPY = 0x00CC0020

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

        # Window placement + monitor geometry (live-preview sizing).
        user32.GetWindowPlacement.argtypes = [
            wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)
        ]
        user32.GetWindowPlacement.restype = wintypes.BOOL
        user32.MonitorFromRect.argtypes = [ctypes.POINTER(RECT), wintypes.DWORD]
        user32.MonitorFromRect.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        # GDI stretch used to grow the cheap small render into a full-size
        # window bitmap at C speed (Python never touches those pixels).
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.SetStretchBltMode.restype = ctypes.c_int
        gdi32.SetBrushOrgEx.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.POINTER(POINT)
        ]
        gdi32.SetBrushOrgEx.restype = wintypes.BOOL
        gdi32.StretchBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD,
        ]
        gdi32.StretchBlt.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

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

    def _create_dib(width: int, height: int) -> tuple[int, int]:
        """Create a top-down 32-bit DIB section; return (hbitmap, bits_ptr).

        The storage is owned by the caller. Negative height means top-down:
        exactly the row order generated by preview_bgra, avoiding an extra
        flip/copy. Both source and stretch-target DIBs use the same
        orientation, so StretchBlt never flips anything.
        """
        if not _WIN32_OK or width <= 0 or height <= 0:
            return (0, 0)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = width * height * 4
        bits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(None, ctypes.byref(info), DIB_RGB_COLORS,
                                     ctypes.byref(bits), None, 0)
        if not hbm or not bits.value:
            try:
                if hbm:
                    gdi32.DeleteObject(hbm)
            except Exception:
                pass
            return (0, 0)
        return (int(hbm), int(bits.value))

    def _bgra_to_hbitmap(pixels: bytes, width: int, height: int) -> int:
        """Create a top-down 32-bit DIB whose storage receives owned BGRA."""
        if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
            return 0
        hbm, bits = _create_dib(width, height)
        if not hbm:
            return 0
        try:
            ctypes.memmove(bits, pixels, len(pixels))
            return hbm
        except Exception:
            gdi32.DeleteObject(hbm)
            return 0

    def _stretch_hbitmap(src: int, src_w: int, src_h: int,
                         dst_w: int, dst_h: int) -> int:
        """Grow a small BGRA DIB into a window-sized one with GDI (C speed).

        The pure-Python frame conversion is the expensive part, so it runs
        once on a small render; StretchBlt (HALFTONE mode) then scales it to
        the Peek bitmap size without touching Python per pixel.
        """
        if not src or dst_w <= 0 or dst_h <= 0:
            return 0
        dst, _ = _create_dib(dst_w, dst_h)
        if not dst:
            return 0
        dc_src = dc_dst = 0
        old_src = old_dst = None
        try:
            dc_src = gdi32.CreateCompatibleDC(None)
            dc_dst = gdi32.CreateCompatibleDC(None)
            if not dc_src or not dc_dst:
                raise OSError("CreateCompatibleDC failed")
            old_src = gdi32.SelectObject(dc_src, src)
            old_dst = gdi32.SelectObject(dc_dst, dst)
            if not old_src or not old_dst:
                raise OSError("SelectObject failed")
            gdi32.SetStretchBltMode(dc_dst, HALFTONE)
            # MSDN pairs HALFTONE mode with a brush-origin reset.
            gdi32.SetBrushOrgEx(dc_dst, 0, 0, None)
            if not gdi32.StretchBlt(dc_dst, 0, 0, dst_w, dst_h,
                                    dc_src, 0, 0, src_w, src_h, SRCCOPY):
                raise OSError("StretchBlt failed")
            return dst
        except Exception:
            log.debug("taskbar preview stretch failed", exc_info=True)
            try:
                gdi32.DeleteObject(dst)
            except Exception:
                pass
            return 0
        finally:
            try:
                if dc_src and old_src:
                    gdi32.SelectObject(dc_src, old_src)
                if dc_dst and old_dst:
                    gdi32.SelectObject(dc_dst, old_dst)
                if dc_src:
                    gdi32.DeleteDC(dc_src)
                if dc_dst:
                    gdi32.DeleteDC(dc_dst)
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
                hwnd = int(msg.hwnd or 0) & 0xFFFFFFFFFFFFFFFF
                if hwnd == 0:
                    return False, 0
                owner_hwnd = self._owner.hwnd & 0xFFFFFFFFFFFFFFFF
                if hwnd != owner_hwnd and (hwnd & 0xFFFFFFFF) != (owner_hwnd & 0xFFFFFFFF):
                    return False, 0

                if msg.message == WM_DWMSENDICONICTHUMBNAIL:
                    # lParam carries the maximum bitmap size DWM will accept.
                    # Per MSDN the axes are the opposite of the usual POINT
                    # convention: HIWORD is the maximum x (width), LOWORD the
                    # maximum y (height). A bitmap exceeding either is
                    # rejected with E_INVALIDARG — which is exactly what
                    # leaves the flyout on the white pending-spinner.
                    lparam = int(msg.lParam or 0)
                    max_w = (lparam >> 16) & 0xFFFF
                    max_h = lparam & 0xFFFF
                    hbm = self._owner._create_thumbnail(max_w, max_h)
                    if not hbm:
                        return False, 0
                    try:
                        # DWM copies the bitmap during this call. Always reply
                        # while iconic mode is enabled; otherwise it displays
                        # the white pending-thumbnail spinner.
                        hr = dwmapi.DwmSetIconicThumbnail(msg.hwnd, hbm, 0)
                        log.debug(
                            "DwmSetIconicThumbnail -> hr=%s (max %dx%d)",
                            hr, max_w, max_h
                        )
                    except Exception:
                        log.debug("DwmSetIconicThumbnail failed", exc_info=True)
                    finally:
                        try:
                            gdi32.DeleteObject(hbm)
                        except Exception:
                            pass
                    return True, 0

                if msg.message == WM_DWMSENDICONICLIVE:
                    hbm = self._owner._create_live_preview()
                    if not hbm:
                        return False, 0
                    try:
                        # No client offset (the whole bitmap is the window)
                        # and no DWM_SIT_DISPLAYFRAME: the shell is frameless,
                        # and a fake drawn frame around a small bitmap is what
                        # made the Peek window read as a stray mini window.
                        hr = dwmapi.DwmSetIconicLivePreviewBitmap(
                            msg.hwnd, hbm, None, 0
                        )
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
            # Last iconic state actually applied via DwmSetWindowAttribute
            # (None = never applied). Dedups the double visibility signals.
            self._applied_iconic = None
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

            Both ``visibilityChanged`` and ``windowStateChanged`` drive this
            for a single minimize/restore, so the attributes are only set on
            a real state change — a successful application is remembered and
            repeat requests become no-ops (one log line per transition).
            """
            if self._hwnd == 0:
                return
            if self._applied_iconic == enabled:
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
                ok = (hr_force == 0 and hr_has == 0)
                self._enabled = (ok and enabled)
                if ok:
                    # A failed set leaves _applied_iconic stale on purpose:
                    # the next visibility signal retries instead of skipping.
                    self._applied_iconic = enabled
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

        def _render_frame_bitmap(self, w: int, h: int) -> int:
            """Latest decoded frame (or opaque black) as a w×h BGRA DIB."""
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

        def _create_thumbnail(self, max_w: int, max_h: int) -> int:
            """Iconic thumbnail for the taskbar flyout / Alt-Tab.

            DWM rejects anything larger than the size it requested
            (E_INVALIDARG), so the bitmap is built at exactly the requested
            size — never a fixed substitute that could exceed it.
            """
            w, h = fit_thumbnail_size(max_w, max_h)
            if w <= 0 or h <= 0:
                return 0
            return self._render_frame_bitmap(w, h)

        def _normal_window_size(self) -> tuple[int, int]:
            """The window's restored frame size while it is minimised.

            ``GetWindowPlacement().rcNormalPosition`` is where the window
            returns to on restore — the size (and position) DWM's Peek
            preview occupies. A window minimised from maximised restores to
            the monitor work area instead. (0, 0) when unknown.
            """
            try:
                wp = WINDOWPLACEMENT()
                wp.length = ctypes.sizeof(WINDOWPLACEMENT)
                if not user32.GetWindowPlacement(
                        wintypes.HWND(self._hwnd), ctypes.byref(wp)):
                    return (0, 0)
                rect = wp.rcNormalPosition
                if wp.flags & WPF_RESTORETOMAXIMIZED:
                    probe = RECT(rect.left, rect.top, rect.right, rect.bottom)
                    mon = user32.MonitorFromRect(
                        ctypes.byref(probe), MONITOR_DEFAULTTONULL
                    )
                    if mon:
                        info = MONITORINFO()
                        info.cbSize = ctypes.sizeof(MONITORINFO)
                        if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                            rect = info.rcWork
                w = max(0, rect.right - rect.left)
                h = max(0, rect.bottom - rect.top)
                # A pathological placement must never force a huge DIB.
                return (min(w, 3840), min(h, 2160))
            except Exception:
                log.debug("GetWindowPlacement failed", exc_info=True)
                return (0, 0)

        def _create_live_preview(self) -> int:
            """Iconic live-preview (Peek) bitmap.

            DWM does not scale this bitmap: the Peek window is drawn at the
            bitmap's own size. A fixed small bitmap therefore floats as a
            stray mini window, which is exactly the artefact this replaces —
            the bitmap is built at the window's restored size so the Peek
            preview sits and looks like the window itself.

            The expensive pure-Python frame conversion still runs only once
            on a small aspect-matched render; GDI stretches it to full size.
            """
            win_w, win_h = self._normal_window_size()
            src_w, src_h = fit_live_source_size(win_w, win_h)
            if src_w <= 0 or src_h <= 0:
                # Placement unknown: keep the preview alive with a modest
                # fixed bitmap rather than leaving DWM on the spinner.
                return self._render_frame_bitmap(320, 180)
            src = self._render_frame_bitmap(src_w, src_h)
            if not src:
                return 0
            if (src_w, src_h) == (win_w, win_h):
                return src
            full = _stretch_hbitmap(src, src_w, src_h, win_w, win_h)
            if not full:
                # Stretch failed: the small render is still a valid preview.
                return src
            try:
                # The stretch copied the pixels, so the small source is spent.
                gdi32.DeleteObject(src)
            except Exception:
                pass
            return full

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
