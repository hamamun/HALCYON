from core.taskbar_pixels import preview_bgra
from engine.taskbar_frame import TaskbarFrame


def test_rv32_conversion_uses_soft_rgbx_byte_order_and_letterboxes():
    # Two pixels: red then blue; padded to an 8-byte row already.
    frame = TaskbarFrame(
        pixels=bytes((255, 0, 0, 0, 0, 0, 255, 0)), chroma="RV32",
        width=2, height=1, y_pitch=8, y_lines=1,
    )
    pixels, width, height = preview_bgra(frame, 4, 4)
    assert (width, height) == (4, 4)
    # 2:1 source is drawn in the central two rows. BGRA red then blue.
    row = 1 * width * 4
    assert pixels[row:row + 4] == bytes((0, 0, 255, 255))
    assert pixels[row + 4:row + 8] == bytes((0, 0, 255, 255))
    assert pixels[row + 8:row + 12] == bytes((255, 0, 0, 255))
    assert pixels[:4] == bytes((0, 0, 0, 255))


def test_i420_conversion_respects_plane_pitches():
    # Neutral chroma and limited-range white luma; y_pitch has two padding bytes.
    frame = TaskbarFrame(
        pixels=bytes((235, 235, 99, 99, 128, 128)), chroma="I420",
        width=2, height=1, y_pitch=4, y_lines=1, uv_pitch=1, uv_lines=1,
    )
    pixels, width, height = preview_bgra(frame, 2, 1)
    assert (width, height) == (2, 1)
    assert pixels == bytes((255, 255, 255, 255)) * 2
