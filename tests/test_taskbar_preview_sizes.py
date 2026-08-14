"""Bitmap-size contracts for the Windows DWM iconic preview path.

The sizing helpers are the platform-independent core of the fix: a thumbnail
larger than the size DWM requested is rejected with E_INVALIDARG (leaving the
taskbar flyout on the white busy-spinner), and the live-preview source must
keep the window's aspect so the stretched Peek bitmap looks like the window.
"""

from core.taskbar_preview import fit_live_source_size, fit_thumbnail_size


def test_thumbnail_size_never_exceeds_the_dwm_maximum():
    # Typical taskbar flyout request at 100% scaling: use it as-is.
    assert fit_thumbnail_size(230, 130) == (230, 130)
    # Any axis order must come back inside the request, never enlarged —
    # a bigger bitmap is exactly what DWM rejects with E_INVALIDARG.
    assert fit_thumbnail_size(130, 230) == (130, 230)
    assert fit_thumbnail_size(64, 64) == (64, 64)
    # DWM's documented absolute ceiling for iconic thumbnails.
    assert fit_thumbnail_size(4096, 4096) == (1024, 1024)


def test_thumbnail_size_rejects_degenerate_requests():
    assert fit_thumbnail_size(0, 0) == (0, 0)
    assert fit_thumbnail_size(0, 130) == (0, 0)
    assert fit_thumbnail_size(-5, 130) == (0, 0)


def test_live_source_size_keeps_window_aspect_within_budget():
    # A 1280x760 window renders at a 320px long edge...
    assert fit_live_source_size(1280, 760) == (320, 190)
    # ...a wide window keeps its own aspect...
    assert fit_live_source_size(1920, 1040) == (320, 173)
    # ...small windows render 1:1 (no upscale)...
    assert fit_live_source_size(200, 100) == (200, 100)
    # ...and a mini-mode bar stays bar-shaped.
    assert fit_live_source_size(460, 44) == (320, 31)


def test_live_source_size_rejects_unknown_windows():
    assert fit_live_source_size(0, 0) == (0, 0)
    assert fit_live_source_size(0, 760) == (0, 0)
    assert fit_live_source_size(-1, 760) == (0, 0)
