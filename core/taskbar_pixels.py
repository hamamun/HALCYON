"""Pure decoded-frame conversion used by the Windows DWM preview path."""
from __future__ import annotations

from engine.taskbar_frame import TaskbarFrame


def preview_bgra(frame: TaskbarFrame, max_width: int, max_height: int) -> tuple[bytes, int, int]:
    """Scale a decoded Soft frame into a black-letterboxed top-down BGRA image.

    Nearest-neighbour is deliberate: DWM thumbnails are small, and this keeps
    conversion bounded and predictable on the Qt/native-event thread.
    """
    max_width = max(1, int(max_width or 320))
    max_height = max(1, int(max_height or 180))
    if frame.width <= 0 or frame.height <= 0:
        raise ValueError("invalid frame dimensions")
    scale = min(max_width / frame.width, max_height / frame.height)
    draw_w = max(1, min(max_width, int(frame.width * scale)))
    draw_h = max(1, min(max_height, int(frame.height * scale)))
    x0, y0 = (max_width - draw_w) // 2, (max_height - draw_h) // 2
    out = bytearray(max_width * max_height * 4)
    # Opaque black letterbox.
    for i in range(3, len(out), 4):
        out[i] = 255
    planar = frame.chroma == "I420"
    if not planar and frame.chroma != "RV32":
        raise ValueError(f"unsupported taskbar chroma {frame.chroma!r}")
    y_size = frame.y_pitch * frame.y_lines
    u_base = y_size
    v_base = y_size + frame.uv_pitch * frame.uv_lines
    src = frame.pixels
    for dy in range(draw_h):
        sy = min(frame.height - 1, dy * frame.height // draw_h)
        dst_row = ((y0 + dy) * max_width + x0) * 4
        for dx in range(draw_w):
            sx = min(frame.width - 1, dx * frame.width // draw_w)
            dst = dst_row + dx * 4
            if planar:
                yy = src[sy * frame.y_pitch + sx]
                uu = src[u_base + (sy // 2) * frame.uv_pitch + (sx // 2)]
                vv = src[v_base + (sy // 2) * frame.uv_pitch + (sx // 2)]
                # ITU-R BT.601 limited-range Y'CbCr -> RGB, clamped.
                c, d, e = max(0, yy - 16), uu - 128, vv - 128
                r = max(0, min(255, (298 * c + 409 * e + 128) >> 8))
                g = max(0, min(255, (298 * c - 100 * d - 208 * e + 128) >> 8))
                b = max(0, min(255, (298 * c + 516 * d + 128) >> 8))
            else:
                # Soft RV32 is QImage.Format_RGBX8888: bytes R,G,B,X.
                pos = sy * frame.y_pitch + sx * 4
                r, g, b = src[pos], src[pos + 1], src[pos + 2]
            out[dst:dst + 4] = bytes((b, g, r, 255))
    return bytes(out), max_width, max_height
