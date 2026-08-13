import ctypes

from engine.taskbar_frame import LatestTaskbarFrameCache
from engine.video_out import Chroma, FrameFormat


def test_cache_makes_an_owned_copy_with_metadata():
    cache = LatestTaskbarFrameCache(interval_ns=0)
    cache.set_enabled(True)
    source = (ctypes.c_ubyte * 8)(*range(8))
    fmt = FrameFormat(Chroma.RV32, 2, 1, 8, 1)
    cache.capture(ctypes.addressof(source), fmt, 41)
    source[0] = 99
    frame = cache.latest()
    assert frame is not None
    assert frame.pixels == bytes(range(8))
    assert frame.chroma == Chroma.RV32
    assert (frame.width, frame.height, frame.y_pitch, frame.frame_id) == (2, 1, 8, 41)


def test_cache_does_not_publish_while_disabled():
    cache = LatestTaskbarFrameCache(interval_ns=0)
    source = (ctypes.c_ubyte * 4)(1, 2, 3, 4)
    fmt = FrameFormat(Chroma.RV32, 1, 1, 4, 1)
    cache.capture(ctypes.addressof(source), fmt, 1)
    assert cache.latest() is None
