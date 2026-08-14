"""Pure decoded-frame conversion used by the Windows DWM preview path."""
from __future__ import annotations

from engine.taskbar_frame import TaskbarFrame


def preview_bgra(frame: TaskbarFrame, max_width: int, max_height: int) -> tuple[bytes, int, int]:
    """Scale a decoded Soft frame into a black-letterboxed top-down BGRA image.

    Nearest-neighbour is deliberate: DWM thumbnails are small, and this keeps
    conversion bounded and predictable on the Qt/native-event thread.

    The conversion runs on the GUI thread for every DWM request, so every
    per-pixel cost matters: the letterbox canvas is built with a C-speed bytes
    repeat (a per-pixel alpha loop here used to cost as much as the YUV math),
    and all row/column-invariant source offsets are computed once.
    """
    max_width = max(1, int(max_width or 320))
    max_height = max(1, int(max_height or 180))
    if frame.width <= 0 or frame.height <= 0:
        raise ValueError("invalid frame dimensions")
    scale = min(max_width / frame.width, max_height / frame.height)
    draw_w = max(1, min(max_width, int(frame.width * scale)))
    draw_h = max(1, min(max_height, int(frame.height * scale)))
    x0, y0 = (max_width - draw_w) // 2, (max_height - draw_h) // 2
    # Opaque black letterbox, built at C speed.
    out = bytearray(b"\x00\x00\x00\xff" * (max_width * max_height))
    planar = frame.chroma == "I420"
    if not planar and frame.chroma != "RV32":
        raise ValueError(f"unsupported taskbar chroma {frame.chroma!r}")
    src = frame.pixels
    fw, fh = frame.width, frame.height
    # Source column for every output column — the same for every row.
    cols = [min(fw - 1, dx * fw // draw_w) for dx in range(draw_w)]
    if planar:
        y_pitch, uv_pitch = frame.y_pitch, frame.uv_pitch
        u_base = y_pitch * frame.y_lines
        v_base = u_base + uv_pitch * frame.uv_lines
        for dy in range(draw_h):
            sy = min(fh - 1, dy * fh // draw_h)
            y_row = sy * y_pitch
            uv_row = (sy // 2) * uv_pitch
            dst = ((y0 + dy) * max_width + x0) * 4
            for sx in cols:
                yy = src[y_row + sx]
                uu = src[u_base + uv_row + (sx >> 1)]
                vv = src[v_base + uv_row + (sx >> 1)]
                # ITU-R BT.601 limited-range Y'CbCr -> RGB, clamped.
                c, d, e = max(0, yy - 16), uu - 128, vv - 128
                r = max(0, min(255, (298 * c + 409 * e + 128) >> 8))
                g = max(0, min(255, (298 * c - 100 * d - 208 * e + 128) >> 8))
                b = max(0, min(255, (298 * c + 516 * d + 128) >> 8))
                out[dst:dst + 4] = bytes((b, g, r, 255))
                dst += 4
    else:
        # Soft RV32 is QImage.Format_RGBX8888: bytes R,G,B,X.
        y_pitch = frame.y_pitch
        for dy in range(draw_h):
            sy = min(fh - 1, dy * fh // draw_h)
            row = sy * y_pitch
            dst = ((y0 + dy) * max_width + x0) * 4
            for sx in cols:
                pos = row + sx * 4
                out[dst:dst + 4] = bytes((src[pos + 2], src[pos + 1], src[pos], 255))
                dst += 4
    return bytes(out), max_width, max_height
