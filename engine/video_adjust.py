"""Video adjust — contrast, brightness, hue, saturation, gamma.

Wraps ``libvlc_video_set_adjust_*``. No presets by design — VLC itself has
no built-in video presets, only manual sliders. User asked for VLC-only
presets, so this stays preset-free.

Applies live, enabled only when video exists, persists via Settings
(video.contrast etc). Reapplied on media change like Equalizer.
"""

from __future__ import annotations

import logging
from PySide6.QtCore import Property, QObject, Signal, Slot

log = logging.getLogger(__name__)

DEFAULTS = {
    "contrast": 1.0,
    "brightness": 1.0,
    "hue": 0.0,
    "saturation": 1.0,
    "gamma": 1.0,
}

# Ranges — match VLC's own UI
RANGES = {
    "contrast": (0.0, 2.0),
    "brightness": (0.0, 2.0),
    "hue": (0.0, 360.0),
    "saturation": (0.0, 3.0),
    "gamma": (0.01, 10.0),
}


class VideoAdjust(QObject):
    contrastChanged = Signal()
    brightnessChanged = Signal()
    hueChanged = Signal()
    saturationChanged = Signal()
    gammaChanged = Signal()
    enabledChanged = Signal()

    def __init__(self, engine, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._settings = settings

        self._contrast = float(settings.get("video.contrast", DEFAULTS["contrast"]))
        self._brightness = float(settings.get("video.brightness", DEFAULTS["brightness"]))
        self._hue = float(settings.get("video.hue", DEFAULTS["hue"]))
        self._saturation = float(settings.get("video.saturation", DEFAULTS["saturation"]))
        self._gamma = float(settings.get("video.gamma", DEFAULTS["gamma"]))
        self._enabled = bool(settings.get("video.adjustEnabled", False))

        # Clamp loaded values into range, so a corrupt file cannot send VLC a NaN
        self._contrast = self._clamp("contrast", self._contrast)
        self._brightness = self._clamp("brightness", self._brightness)
        self._hue = self._clamp("hue", self._hue)
        self._saturation = self._clamp("saturation", self._saturation)
        self._gamma = self._clamp("gamma", self._gamma)

        # Apply current state once — engine may not yet have a media, but
        # set_adjust_enabled is safe to call early.
        self._apply_all()

    def _clamp(self, key: str, value: float) -> float:
        lo, hi = RANGES[key]
        return max(lo, min(hi, float(value)))

    # ------------------------------------------------------------- props ---
    @Property(float, notify=contrastChanged)
    def contrast(self) -> float:
        return self._contrast

    @Property(float, notify=brightnessChanged)
    def brightness(self) -> float:
        return self._brightness

    @Property(float, notify=hueChanged)
    def hue(self) -> float:
        return self._hue

    @Property(float, notify=saturationChanged)
    def saturation(self) -> float:
        return self._saturation

    @Property(float, notify=gammaChanged)
    def gamma(self) -> float:
        return self._gamma

    @Property(bool, notify=enabledChanged)
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------- setters --
    @Slot(float)
    def set_contrast(self, v: float) -> None:
        v = self._clamp("contrast", v)
        if abs(self._contrast - v) < 1e-4:
            return
        self._contrast = v
        self._enabled = True
        self._settings.set("video.contrast", v)
        self._settings.set("video.adjustEnabled", True)
        self._apply_all()
        self.contrastChanged.emit()
        self.enabledChanged.emit()

    @Slot(float)
    def set_brightness(self, v: float) -> None:
        v = self._clamp("brightness", v)
        if abs(self._brightness - v) < 1e-4:
            return
        self._brightness = v
        self._enabled = True
        self._settings.set("video.brightness", v)
        self._settings.set("video.adjustEnabled", True)
        self._apply_all()
        self.brightnessChanged.emit()
        self.enabledChanged.emit()

    @Slot(float)
    def set_hue(self, v: float) -> None:
        v = self._clamp("hue", v)
        if abs(self._hue - v) < 1e-4:
            return
        self._hue = v
        self._enabled = True
        self._settings.set("video.hue", v)
        self._settings.set("video.adjustEnabled", True)
        self._apply_all()
        self.hueChanged.emit()
        self.enabledChanged.emit()

    @Slot(float)
    def set_saturation(self, v: float) -> None:
        v = self._clamp("saturation", v)
        if abs(self._saturation - v) < 1e-4:
            return
        self._saturation = v
        self._enabled = True
        self._settings.set("video.saturation", v)
        self._settings.set("video.adjustEnabled", True)
        self._apply_all()
        self.saturationChanged.emit()
        self.enabledChanged.emit()

    @Slot(float)
    def set_gamma(self, v: float) -> None:
        v = self._clamp("gamma", v)
        if abs(self._gamma - v) < 1e-4:
            return
        self._gamma = v
        self._enabled = True
        self._settings.set("video.gamma", v)
        self._settings.set("video.adjustEnabled", True)
        self._apply_all()
        self.gammaChanged.emit()
        self.enabledChanged.emit()

    @Slot()
    def reset(self) -> None:
        self._contrast = DEFAULTS["contrast"]
        self._brightness = DEFAULTS["brightness"]
        self._hue = DEFAULTS["hue"]
        self._saturation = DEFAULTS["saturation"]
        self._gamma = DEFAULTS["gamma"]
        self._enabled = False
        self._settings.set("video.contrast", self._contrast)
        self._settings.set("video.brightness", self._brightness)
        self._settings.set("video.hue", self._hue)
        self._settings.set("video.saturation", self._saturation)
        self._settings.set("video.gamma", self._gamma)
        self._settings.set("video.adjustEnabled", False)
        self._apply_all()
        self.contrastChanged.emit()
        self.brightnessChanged.emit()
        self.hueChanged.emit()
        self.saturationChanged.emit()
        self.gammaChanged.emit()
        self.enabledChanged.emit()

    # ---------------------------------------------------------------- apply --
    def _apply_all(self) -> None:
        eng = self._engine
        if eng is None:
            return
        try:
            eng.set_adjust_enabled(self._enabled)
            if not self._enabled:
                return
            eng.set_adjust("contrast", self._contrast)
            eng.set_adjust("brightness", self._brightness)
            eng.set_adjust("hue", self._hue)
            eng.set_adjust("saturation", self._saturation)
            eng.set_adjust("gamma", self._gamma)
        except Exception:
            log.exception("video adjust apply failed")

    def reapply(self) -> None:
        # Called on every new media, like Equalizer.reapply()
        self._apply_all()
