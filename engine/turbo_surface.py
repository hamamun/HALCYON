"""The Turbo native child window — §V.3.

Turbo is *not* a second player. It is the same single :class:`~engine.vlc_engine.VlcEngine`
player told to render into a native child window instead of into the vmem
callbacks, so libVLC can keep the decoded frame on the GPU (``--avcodec-hw=d3d11va``)
instead of copying it back to system memory for the Soft I420 path.

What this module owns, and nothing else:

* creating one native child ``QWindow`` and handing its handle to libVLC
  (``libvlc_media_player_set_hwnd``);
* handing the *same* ``QWindow`` to QML so ``WindowContainer`` can embed it in
  the Stage rectangle of the single Halcyon window (§V.3 — never an outside
  video window);
* tearing all of that down again, completely, on request or on any failure.

**The window is never shown by this module.** It is created (so the platform
handle exists and libVLC can draw into it) but stays hidden until
``WindowContainer`` adopts it into the main window. That ordering is what keeps
a Turbo attempt from flashing a stray top-level video window on screen, and it
is why :meth:`stop` is safe to call at any point of a half-finished setup.

**Platform reality.** ``set_hwnd`` is a Win32 entry point. On every other
platform :meth:`is_supported` returns ``False`` and the engine stays on Soft —
which is the documented failure behaviour (§V.4), not a special case. The
Windows path in this file has been written against the libVLC and Qt APIs but
**cannot be executed on a non-Windows machine**; see ``docs`` and the notes in
``HALCYON_PLAN.md`` §V.
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

#: Test/diagnostic escape hatch. ``1`` pretends the platform can embed a native
#: child so the *lifecycle* (create → attach → tear down → fall back) can be
#: exercised off Windows with a fake player. It never makes ``set_hwnd`` work.
_FORCE_ENV = "HALCYON_TURBO_FORCE"


def is_supported() -> bool:
    """Can this platform host the native Turbo child at all?"""
    if os.environ.get(_FORCE_ENV, "").strip() == "1":
        return True
    return sys.platform == "win32"


# Win32 constants used only by the native-child helpers below.
_GWL_EXSTYLE = -20
_GWLP_WNDPROC = -4
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WM_ERASEBKGND = 0x0014
_BLACK_BRUSH = 4


def _win32_long_funcs():
    """Return ``(get_long, set_long)`` typed for this process's pointer width.

    ``ctypes.windll`` defaults every argument to ``c_int`` and every return
    value to ``c_int``. A WndProc address is a 64-bit pointer on Win64, so the
    default ``c_int`` third argument raises ``OverflowError: int too long to
    convert`` on ``SetWindowLongPtrW`` (the exact failure in
    ``_keep_hwnd_black``), and reading a 64-bit pointer back through a
    ``c_int`` restype silently truncates it — which also broke the
    "did WindowContainer replace our WndProc?" check and ``_restore_wndproc``.
    Declare the real ``LONG_PTR`` signatures once so every helper here gets
    untruncated values on both process widths.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
    else:
        get_long = user32.GetWindowLongW
        set_long = user32.SetWindowLongW

    # LONG_PTR: pointer-width signed integer. On Win64 this is 64 bits — the
    # only type that can carry a WndProc address in either position.
    long_ptr = ctypes.c_ssize_t
    get_long.restype = long_ptr
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    set_long.restype = long_ptr
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
    return get_long, set_long


_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_GW_CHILD = 5
_GW_HWNDNEXT = 2


def _harden_hwnd_value(hwnd: int) -> None:
    """Strip layered / click-through styles from one HWND and restyle it."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        get_long, set_long = _win32_long_funcs()
        style = int(get_long(hwnd, _GWL_EXSTYLE) or 0)
        set_long(hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED & ~_WS_EX_TRANSPARENT)
        user32 = ctypes.windll.user32
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    except Exception:
        log.debug("Turbo: could not harden HWND %s", hwnd, exc_info=True)


def _harden_hwnd_tree(hwnd: int) -> None:
    """Harden this HWND and every VLC child it created."""
    if sys.platform != "win32" or not hwnd:
        return
    _harden_hwnd_value(hwnd)
    _fill_hwnd_black(hwnd)
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        child = user32.GetWindow(hwnd, _GW_CHILD)
        while child:
            _harden_hwnd_value(int(child))
            _fill_hwnd_black(int(child))
            child = user32.GetWindow(child, _GW_HWNDNEXT)
    except Exception:
        log.debug("Turbo: could not walk child HWNDs", exc_info=True)


def _harden_hwnd(window) -> None:
    """Strip layered / click-through styles from *this* HWND only.

    A child that inherited ``WS_EX_LAYERED`` from Halcyon's transparent
    shell is see-through even after we fill it black. Class-long
    background-brush changes are deliberately avoided: Qt QWindows share a
    window class, and painting every Qt window black would be worse than
    the hole we are closing.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        if not hwnd:
            return
        _harden_hwnd_tree(hwnd)
    except Exception:
        log.debug("Turbo: could not harden the native child HWND", exc_info=True)


def _gdi_fill_signatures() -> None:
    """Type the GDI calls that paint an HWND black.

    Same bug class as the WndProc hook: ``ctypes.windll`` defaults every
    argument to ``c_int``, and HDC/HBRUSH are pointer-sized HANDLEs on Win64.
    ``GetDC`` read back through a ``c_int`` restype truncates the device
    context, and ``FillRect`` with a truncated HDC either fails silently or
    paints nothing — the letterbox stays the default erase colour instead of
    black. Idempotent: call from every helper that paints.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetClientRect.restype = ctypes.c_int
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.FillRect.restype = ctypes.c_int
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    gdi32.GetStockObject.restype = ctypes.c_void_p
    gdi32.GetStockObject.argtypes = [ctypes.c_int]


def _fill_hwnd_black(hwnd: int) -> None:
    """Paint this HWND's client area black once. Best-effort."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        _gdi_fill_signatures()
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(hwnd)
        if not hdc:
            return
        try:
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            user32.FillRect(hdc, ctypes.byref(rect), gdi32.GetStockObject(_BLACK_BRUSH))
        finally:
            user32.ReleaseDC(hwnd, hdc)
    except Exception:
        log.debug("Turbo: could not fill the native child black", exc_info=True)


def _keep_hwnd_black(window) -> None:
    """Keep the letterbox black after Windows erases the background.

    ``QWindow`` has no ``setColor`` (that API lives on ``QQuickWindow``).
    Calling it crashed every Turbo start and forced Soft. We subclass *this*
    HWND's WndProc only, fill on ``WM_ERASEBKGND``, and leave Qt's shared
    window class alone.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        if not hwnd:
            return

        _gdi_fill_signatures()
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        get_long, set_long = _win32_long_funcs()

        # WindowContainer reparenting can replace the WndProc. If ours is
        # still installed, just refill; otherwise hook again on top of
        # whatever Qt put back.
        ours = getattr(window, "_turbo_wndproc", None)
        if ours is not None:
            try:
                ours_addr = int(ctypes.cast(ours, ctypes.c_void_p).value or 0)
                current = int(get_long(hwnd, _GWLP_WNDPROC) or 0)
            except Exception:
                ours_addr = current = 0
            if ours_addr and current == ours_addr:
                _fill_hwnd_black(hwnd)
                return
            window._turbo_wndproc = None

        if ctypes.sizeof(ctypes.c_void_p) == 8:
            lresult = ctypes.c_longlong
        else:
            lresult = ctypes.c_long
        wndproc_type = ctypes.WINFUNCTYPE(
            lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        prev = get_long(hwnd, _GWLP_WNDPROC)
        user32.CallWindowProcW.restype = lresult
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = lresult
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        @wndproc_type
        def wndproc(hwnd_msg, msg, wparam, lparam):
            if msg == _WM_ERASEBKGND and wparam:
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd_msg, ctypes.byref(rect))
                user32.FillRect(wparam, ctypes.byref(rect), gdi32.GetStockObject(_BLACK_BRUSH))
                return 1
            if prev:
                return user32.CallWindowProcW(ctypes.c_void_p(int(prev)), hwnd_msg, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd_msg, msg, wparam, lparam)

        # Hard ref: a collected trampoline would crash the next WM_ERASEBKGND.
        window._turbo_wndproc = wndproc
        window._turbo_prev_wndproc = prev
        set_long(hwnd, _GWLP_WNDPROC, ctypes.cast(wndproc, ctypes.c_void_p).value)
        _fill_hwnd_black(hwnd)
    except Exception:
        log.debug("Turbo: could not keep the native child black", exc_info=True)
        try:
            _fill_hwnd_black(int(window.winId()))
        except Exception:
            pass


def _restore_wndproc(window) -> None:
    """Put the original WndProc back before the HWND is destroyed."""
    prev = getattr(window, "_turbo_prev_wndproc", None)
    if prev is None or sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        if hwnd:
            _get_long, set_long = _win32_long_funcs()
            set_long(hwnd, _GWLP_WNDPROC, prev)
    except Exception:
        log.debug("Turbo: could not restore the native WndProc", exc_info=True)
    window._turbo_prev_wndproc = None
    window._turbo_wndproc = None


#: Saved ``GWL_EXSTYLE`` of the Halcyon shell, keyed by HWND. Stored here
#: instead of as an attribute on the QML ``QQuickWindow`` — shiboken
#: wrappers often reject arbitrary Python attributes.
_HOST_EXSTYLES: dict[int, int] = {}


def seal_host_window(qwindow) -> None:
    """Make the Halcyon shell HWND opaque for the life of Turbo.

    Soft needs a layered (alpha) shell for the rounded glass corners. A
    layered parent plus a native child whose swapchain has alpha is the
    desktop hole under the title bar: every pixel VLC does not paint
    shows Outlook. Stripping ``WS_EX_LAYERED`` here means leftover
    transparent pixels composite onto this window, not the desktop.
    :func:`unseal_host_window` puts the original style back. Off Windows
    this is a no-op.
    """
    if qwindow is None or sys.platform != "win32":
        return
    try:
        hwnd = int(qwindow.winId())
    except Exception:
        log.debug("Turbo: host window has no HWND to seal", exc_info=True)
        return
    if not hwnd:
        return
    try:
        get_long, set_long = _win32_long_funcs()
        style = int(get_long(hwnd, _GWL_EXSTYLE) or 0)
        _HOST_EXSTYLES.setdefault(hwnd, style)
        set_long(hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED & ~_WS_EX_TRANSPARENT)
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
        _fill_hwnd_black(hwnd)
    except Exception:
        log.debug("Turbo: could not seal the host window", exc_info=True)


def unseal_host_window(qwindow) -> None:
    """Restore the shell's pre-Turbo extended style (layered glass)."""
    if qwindow is None or sys.platform != "win32":
        return
    try:
        hwnd = int(qwindow.winId())
    except Exception:
        return
    prev = _HOST_EXSTYLES.pop(hwnd, None) if hwnd else None
    if prev is None:
        return
    try:
        _get_long, set_long = _win32_long_funcs()
        set_long(hwnd, _GWL_EXSTYLE, int(prev))
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.restype = ctypes.c_int
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    except Exception:
        log.debug("Turbo: could not unseal the host window", exc_info=True)


def fit_picture_rect(
    stage_w: float, stage_h: float, video_w: float, video_h: float
) -> tuple[float, float, float, float]:
    """PreserveAspectFit rectangle inside the stage. Returns ``(x, y, w, h)``.

    Same rule as Soft's ``VideoSurface`` (``fillMode: PreserveAspectFit``).
    Unknown video size fills the stage — the host seal covers that brief
    moment — so a missing decoder size never leaves a zero-size HWND.
    """
    stage_w = float(stage_w or 0.0)
    stage_h = float(stage_h or 0.0)
    video_w = float(video_w or 0.0)
    video_h = float(video_h or 0.0)
    if stage_w <= 0.0 or stage_h <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    if video_w <= 0.0 or video_h <= 0.0:
        return (0.0, 0.0, stage_w, stage_h)
    item_aspect = stage_w / stage_h
    video_aspect = video_w / video_h
    if video_aspect > item_aspect:
        height = stage_w / video_aspect
        return (0.0, (stage_h - height) / 2.0, stage_w, height)
    width = stage_h * video_aspect
    return ((stage_w - width) / 2.0, 0.0, width, stage_h)


class TurboSurface(QObject):
    """One native child window, or none. Never two.

    Lifecycle::

        surface = TurboSurface()
        if surface.start(player):        # creates the child, calls set_hwnd
            container.window = surface.window     # QML WindowContainer
        ...
        surface.stop(player)             # always safe, even after a failure
    """

    #: Emitted when :attr:`window` becomes available or goes away.
    windowChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = None
        self._handle = 0
        self._player = None
        self._reharden_attempts = 0

    # ------------------------------------------------------------- state ---
    @property
    def window(self):
        """The ``QWindow`` for ``WindowContainer``, or ``None``."""
        return self._window

    @property
    def handle(self) -> int:
        """The native handle given to libVLC, or ``0``."""
        return int(self._handle or 0)

    @property
    def active(self) -> bool:
        return self._window is not None and self._handle != 0

    # ------------------------------------------------------------ create ---
    def start(self, player) -> bool:
        """Create the child window and point ``player`` at it.

        Returns ``False`` — having cleaned up whatever it managed to create —
        for every reason it could not finish. The caller's job on ``False`` is
        simply to stay on (or return to) Soft.
        """
        if self.active:
            return True
        if not is_supported():
            log.info("Turbo unavailable on this platform — staying on Soft")
            return False
        if player is None:
            return False

        try:
            window = self._create_child_window()
        except Exception:
            log.warning("Turbo: could not create the native child window", exc_info=True)
            self._destroy_window()
            return False
        if window is None:
            self._destroy_window()
            return False

        try:
            handle = int(window.winId())
        except Exception:
            log.warning("Turbo: the child window has no native handle", exc_info=True)
            self._destroy_window()
            return False
        if not handle:
            log.warning("Turbo: native handle is 0")
            self._destroy_window()
            return False

        if not self._bind_player(player, handle):
            self._destroy_window()
            return False

        self._window = window
        self._handle = handle
        self._player = player
        # WindowContainer reparents this HWND on its next render tick and can
        # put WS_EX_LAYERED back (and replace our WndProc) at that point, so a
        # single strip now would run before the embed and be undone by it.
        # Re-strip on a short schedule: the first attempt usually catches the
        # pre-embed state, one of the later ones lands after the reparent.
        self._reharden_attempts = 0
        # Context-object overload: if this surface is destroyed mid-schedule,
        # Qt drops the pending timers instead of calling into a dead QObject.
        # WindowContainer reparents after the first frame; later ticks catch
        # VLC's own D3D child, which is what punches the desktop hole.
        QTimer.singleShot(16, self, self._reharden)
        QTimer.singleShot(48, self, self._reharden)
        QTimer.singleShot(120, self, self._reharden)
        QTimer.singleShot(250, self, self._reharden)
        QTimer.singleShot(500, self, self._reharden)
        log.info("Turbo: native child window ready (handle=%s)", handle)
        self.windowChanged.emit()
        return True

    def reharden_now(self) -> None:
        """Re-strip layered styles after WindowContainer reparents the child.

        The engine calls this from ``note_turbo_embedded`` — that reparent is
        what puts ``WS_EX_LAYERED`` back and what used to punch the desktop
        hole under the title bar.
        """
        self._reharden()

    def _reharden(self) -> None:
        if self._window is None:
            return
        self._reharden_attempts += 1
        _harden_hwnd(self._window)
        _keep_hwnd_black(self._window)

    def _create_child_window(self):
        """A hidden, frameless ``QWindow`` with a real platform handle.

        ``create()`` materialises the handle without mapping the window, so
        libVLC has something to render into while nothing appears on screen.
        ``WindowContainer`` reparents and shows it from QML.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QWindow

        # ``QWindow.setColor`` does not exist (it is a ``QQuickWindow`` API).
        # The previous call raised AttributeError on every Turbo start and
        # the engine fell back to Soft. Colour lives on this subclass; the
        # native fill / WndProc is what actually paints the HWND.
        class TurboChildWindow(QWindow):
            def __init__(self) -> None:
                super().__init__()
                self._turbo_color = QColor(0, 0, 0)

            def setColor(self, color) -> None:  # noqa: N802 - QQuickWindow's name
                self._turbo_color = (
                    QColor(color) if color is not None else QColor(0, 0, 0)
                )

            def color(self):
                return QColor(self._turbo_color)

        window = TurboChildWindow()
        window.setFlags(Qt.FramelessWindowHint)
        # Opaque black, not the default clear/transparent colour. Halcyon's
        # shell is itself a transparent (layered) window for rounded corners.
        # A transparent native child inside that window punches a hole
        # straight through to the desktop in every pixel VLC does not paint
        # — the letterbox between the title bar and the picture. VLC only
        # presents the video rectangle; this colour fills the rest of the
        # HWND so the gap is black, not File Explorer.
        window.setColor(QColor(0, 0, 0))
        window.setOpacity(1.0)
        # Match the process-wide alpha buffer (main.py sets it to 8).
        # Requesting 0 produced "Swapchain says surface has alpha but the
        # window has no alphaBufferSize set". The hole is closed by sizing
        # the HWND to the picture and sealing the host, not by this bit.
        try:
            fmt = window.format()
            fmt.setAlphaBufferSize(8)
            window.setFormat(fmt)
        except Exception:
            log.debug("Turbo: could not set the child surface format", exc_info=True)
        # Never call show(). See the module docstring: an unparented visible
        # QWindow is exactly the "outside video window" §V.3 forbids.
        window.create()
        _harden_hwnd(window)
        _keep_hwnd_black(window)
        return window

    @staticmethod
    def adopt(handle: int):
        """Wrap a *foreign* native handle as a ``QWindow`` (``QWindow.fromWinId``).

        Not used by the default route — Halcyon creates the child itself and
        gives libVLC the handle, which keeps ownership unambiguous. It exists
        because §V.3's contract is "wrap the native child with
        ``QWindow.fromWinId()`` and embed it with ``WindowContainer``", and a
        future libVLC path that creates its own window plugs in here without
        touching the rest of the engine.
        """
        if not handle:
            return None
        from PySide6.QtGui import QWindow
        try:
            return QWindow.fromWinId(int(handle))
        except Exception:
            log.warning("Turbo: could not adopt handle %s", handle, exc_info=True)
            return None

    @staticmethod
    def _bind_player(player, handle: int) -> bool:
        """``libvlc_media_player_set_hwnd``. Windows only, by definition."""
        setter = getattr(player, "set_hwnd", None)
        if not callable(setter):
            log.warning("Turbo: this libVLC build exposes no set_hwnd")
            return False
        try:
            setter(handle)
        except Exception:
            log.warning("Turbo: set_hwnd failed", exc_info=True)
            return False
        # Let clicks fall through to Halcyon's overlay, not VLC's HWND.
        for name in ("video_set_mouse_input", "video_set_key_input"):
            extra = getattr(player, name, None)
            if callable(extra):
                try:
                    extra(False)
                except Exception:
                    log.debug("Turbo: %s failed", name, exc_info=True)
        return True

    # ------------------------------------------------------------ destroy ---
    def stop(self, player=None) -> None:
        """Unbind libVLC and destroy the child. Safe to call twice, or never
        having started, or halfway through a failed :meth:`start`."""
        self._reharden_attempts = 0
        target = player if player is not None else self._player
        if target is not None:
            setter = getattr(target, "set_hwnd", None)
            if callable(setter):
                try:
                    setter(0)
                except Exception:
                    log.debug("Turbo: clearing the HWND failed", exc_info=True)
        self._player = None
        self._destroy_window()

    def _destroy_window(self) -> None:
        window = self._window
        self._window = None
        self._handle = 0
        if window is not None:
            _restore_wndproc(window)
            try:
                window.setParent(None)
            except Exception:
                log.debug("Turbo: could not unparent the child window", exc_info=True)
            try:
                window.destroy()
            except Exception:
                log.debug("Turbo: child window destroy failed", exc_info=True)
            try:
                window.deleteLater()
            except Exception:
                log.debug("Turbo: child window deleteLater failed", exc_info=True)
            self.windowChanged.emit()
