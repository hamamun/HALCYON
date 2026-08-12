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
        get_long, set_long = _win32_long_funcs()
        style = int(get_long(hwnd, _GWL_EXSTYLE) or 0)
        set_long(hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED & ~_WS_EX_TRANSPARENT)
    except Exception:
        log.debug("Turbo: could not harden the native child HWND", exc_info=True)


def _fill_hwnd_black(hwnd: int) -> None:
    """Paint this HWND's client area black once. Best-effort."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

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
        # WindowContainer reparents this HWND on the next tick and can put
        # WS_EX_LAYERED back. Re-strip it after the embed, not only at create.
        QTimer.singleShot(0, self._reharden)
        log.info("Turbo: native child window ready (handle=%s)", handle)
        self.windowChanged.emit()
        return True

    def _reharden(self) -> None:
        if self._window is not None:
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
        try:
            fmt = window.format()
            fmt.setAlphaBufferSize(0)
            window.setFormat(fmt)
        except Exception:
            log.debug("Turbo: could not force an opaque surface format", exc_info=True)
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
        return True

    # ------------------------------------------------------------ destroy ---
    def stop(self, player=None) -> None:
        """Unbind libVLC and destroy the child. Safe to call twice, or never
        having started, or halfway through a failed :meth:`start`."""
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
