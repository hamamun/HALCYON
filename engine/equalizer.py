"""10-band equalizer — Milestone 1.7.

Wraps ``libvlc_audio_equalizer_*``. Applies live, with no playback restart, and
persists the active equalizer values to ``eq.json``.

Because this hangs off libVLC rather than off any one mode, it works for *any*
Halcyon playback — including M3U streams in Phase 2 (§P2.4). Same component,
reached the same way from the right-hand panel. Not a copy per mode.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

FILENAME = "eq.json"

#: The ten ISO bands libVLC exposes, 31 Hz - 16 kHz.
BAND_LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
BAND_COUNT = 10
AMP_MIN = -20.0
AMP_MAX = 20.0


class Equalizer(QObject):
    """Live equalizer bound to one media player."""

    enabledChanged = Signal()
    preampChanged = Signal()
    bandsChanged = Signal()
    presetChanged = Signal()

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._vlc = None
        self._eq = None
        self._enabled = False
        self._preamp = 0.0
        self._amps = [0.0] * BAND_COUNT
        self._current_preset = 0
        self._builtin: list[str] = []
        self._path = paths.data_file(FILENAME)

        try:
            import vlc

            self._vlc = vlc
            self._builtin = self._load_builtin_presets()
        except Exception:
            log.warning("equalizer unavailable — libVLC not loaded")

        self.load()

    # -------------------------------------------------------------- presets ---
    def _load_builtin_presets(self) -> list[str]:
        names: list[str] = []
        try:
            count = self._vlc.libvlc_audio_equalizer_get_preset_count()
            for i in range(count):
                raw = self._vlc.libvlc_audio_equalizer_get_preset_name(i)
                names.append(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
        except Exception:
            log.debug("could not enumerate VLC EQ presets", exc_info=True)
        return names

    def _is_flat(self) -> bool:
        if abs(self._preamp) >= 1e-6:
            return False
        return all(abs(a) < 1e-6 for a in self._amps)

    def _builtin_preset_indexes(self) -> list[int]:
        """Return every VLC preset except its duplicate Flat entry."""
        return [i for i, name in enumerate(self._builtin) if name.casefold() != "flat"]

    def _custom_preset_index(self) -> int:
        return len(self.presetNames) - 1

    @Property("QVariantList", notify=presetChanged)
    def presetNames(self) -> list:  # noqa: N802 - QML-facing
        # Flat is supplied by Halcyon, VLC's other presets follow, and Custom
        # is the final state used after a manual adjustment. VLC commonly
        # exposes its own Flat preset, so omit that duplicate by name.
        return ["Flat", *[self._builtin[i] for i in self._builtin_preset_indexes()], "Custom"]

    @Property("QVariantList", constant=True)
    def bandLabels(self) -> list:  # noqa: N802 - QML-facing
        return list(BAND_LABELS)

    @Property(int, notify=presetChanged)
    def currentPreset(self) -> int:  # noqa: N802 - QML-facing
        return self._current_preset

    @Slot(int)
    def apply_preset(self, index: int) -> None:
        names = self.presetNames
        if not (0 <= index < len(names)):
            return
        self._current_preset = index

        if index == 0:
            self._preamp = 0.0
            self._amps = [0.0] * BAND_COUNT
        elif index == self._custom_preset_index():
            # Custom represents the current manual values; it does not alter them.
            pass
        else:
            builtin_index = self._builtin_preset_indexes()[index - 1]
            name = self._builtin[builtin_index]
            try:
                eq = self._vlc.libvlc_audio_equalizer_new_from_preset(builtin_index)
                if eq:
                    self._preamp = float(self._vlc.libvlc_audio_equalizer_get_preamp(eq))
                    self._amps = [
                        float(self._vlc.libvlc_audio_equalizer_get_amp_at_index(eq, b))
                        for b in range(BAND_COUNT)
                    ]
                    self._vlc.libvlc_audio_equalizer_release(eq)
            except Exception:
                log.exception("could not load preset %s", name)

        self._enabled = not self._is_flat()
        self._apply()
        self.preampChanged.emit()
        self.bandsChanged.emit()
        self.presetChanged.emit()
        self.save()

    # ---------------------------------------------------------------- bands ---
    @Slot(int, result=float)
    def amp_at(self, band: int) -> float:
        return self._amps[band] if 0 <= band < BAND_COUNT else 0.0

    @Slot(int, float)
    def set_amp(self, band: int, value: float) -> None:
        if not (0 <= band < BAND_COUNT):
            return
        value = max(AMP_MIN, min(AMP_MAX, float(value)))
        if abs(self._amps[band] - value) < 1e-6:
            return
        self._amps[band] = value
        self._enabled = True
        self._current_preset = 0 if self._is_flat() else self._custom_preset_index()
        self._apply()
        self.bandsChanged.emit()
        self.presetChanged.emit()
        self.save()

    @Property(float, notify=preampChanged)
    def preamp(self) -> float:
        return self._preamp

    @Slot(float)
    def set_preamp(self, value: float) -> None:
        value = max(AMP_MIN, min(AMP_MAX, float(value)))
        if abs(self._preamp - value) < 1e-6:
            return
        self._preamp = value
        self._enabled = True
        self._current_preset = 0 if self._is_flat() else self._custom_preset_index()
        self._apply()
        self.preampChanged.emit()
        self.presetChanged.emit()
        self.save()

    @Slot()
    def reset(self) -> None:
        self._preamp = 0.0
        self._amps = [0.0] * BAND_COUNT
        self._current_preset = 0
        self._enabled = False
        self._apply()
        self.preampChanged.emit()
        self.bandsChanged.emit()
        self.presetChanged.emit()
        self.save()

    # ---------------------------------------------------------------- apply ---
    def _apply(self) -> None:
        """Push the current curve into libVLC. Live — no restart."""
        player = getattr(self._engine, "raw_player", None)
        if player is None or self._vlc is None:
            return
        setter = getattr(player, "set_equalizer", None)
        if setter is None:
            # Older/cut-down libVLC builds omit the equalizer API entirely.
            # Not having an EQ must never stop the audio.
            log.debug("libVLC build has no equalizer support — skipping")
            return
        try:
            if self._eq is not None:
                self._vlc.libvlc_audio_equalizer_release(self._eq)
                self._eq = None
            if not self._enabled:
                setter(None)
                return
            self._eq = self._vlc.libvlc_audio_equalizer_new()
            if not self._eq:
                return
            self._vlc.libvlc_audio_equalizer_set_preamp(self._eq, self._preamp)
            for band, amp in enumerate(self._amps):
                self._vlc.libvlc_audio_equalizer_set_amp_at_index(self._eq, amp, band)
            setter(self._eq)
        except Exception:
            log.exception("could not apply equalizer")

    def reapply(self) -> None:
        """Called after a new media starts, so the curve survives track changes."""
        self._apply()

    # ------------------------------------------------------------ persistence ---
    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        self._enabled = bool(data.get("enabled", False))
        self._preamp = float(data.get("preamp", 0.0))
        amps = data.get("bands", [])
        if isinstance(amps, list) and len(amps) == BAND_COUNT:
            self._amps = [float(a) for a in amps]
        # Old files may contain user presets and index-based selections. User
        # presets are intentionally no longer supported. The persisted values
        # remain valid; non-flat legacy values are shown as Custom.
        self._current_preset = 0 if self._is_flat() else self._custom_preset_index()

    def save(self) -> None:
        payload = {
            "enabled": self._enabled,
            "preamp": self._preamp,
            "bands": self._amps,
            "preset": self._current_preset,
        }
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("could not save eq.json")

    def release(self) -> None:
        if self._eq is not None and self._vlc is not None:
            try:
                self._vlc.libvlc_audio_equalizer_release(self._eq)
            except Exception:
                pass
            self._eq = None
