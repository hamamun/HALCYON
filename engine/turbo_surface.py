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


def _harden_hwnd(window) -> None:
    """Strip layered / click-through styles from *this* HWND only.

    A child that inherited ``WS_EX_LAYERED`` from Halcyon's transparent
    shell is see-through even after ``QWindow.setColor(black)``. Class-long
    background-brush changes are deliberately avoided: Qt QWindows share a
    window class, and painting every Qt window black would be worse than
    the hole we are closing.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_transparent = 0x00000020
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
        else:
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
        style = int(get_long(hwnd, gwl_exstyle) or 0)
        set_long(hwnd, gwl_exstyle, style & ~ws_ex_layered & ~ws_ex_transparent)
    except Exception:
        log.debug("Turbo: could not harden the native child HWND", exc_info=True)


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

    def _create_child_window(self):
        """A hidden, frameless ``QWindow`` with a real platform handle.

        ``create()`` materialises the handle without mapping the window, so
        libVLC has something to render into while nothing appears on screen.
        ``WindowContainer`` reparents and shows it from QML.
        """
        from PySide6.QtGui import QWindow  # local: keeps QtGui out of import time
        from PySide6.QtCore import Qt

        window = QWindow()
        window.setFlags(Qt.FramelessWindowHint)
        # Opaque black, not the default clear/transparent colour. Halcyon's
        # shell is itself a transparent (layered) window for rounded corners.
        # A transparent native child inside that window punches a hole
        # straight through to the desktop in every pixel VLC does not paint
        # — the letterbox between the title bar and the picture. VLC only
        # presents the video rectangle; this colour fills the rest of the
        # HWND so the gap is black, not File Explorer.
        from PySide6.QtGui import QColor

        window.setColor(QColor(0, 0, 0))
        window.setOpacity(1.0)
        # Never call show(). See the module docstring: an unparented visible
        # QWindow is exactly the "outside video window" §V.3 forbids.
        window.create()
        _harden_hwnd(window)
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
        from PySide6.QtGui import QWindow

        if not handle:
            return None
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
