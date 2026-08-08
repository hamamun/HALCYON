"""QR code generation for pairing — PC Settings → Mobile Remote (§R.1#3).

The QR encodes ``http://<lan-ip>:<port>``; scanning it with the phone camera
opens the remote page. ``qrcode`` is an optional dependency like aiohttp:
when it is missing the API returns a clear 503 instead of failing loudly.
"""

from __future__ import annotations

import io

try:
    import qrcode  # type: ignore

    _QR = True
except ImportError:  # pragma: no cover — depends on the environment
    _QR = False


def available() -> bool:
    return _QR


def qr_png_bytes(url: str, box_size: int = 8, border: int = 2) -> bytes | None:
    """Render ``url`` as a PNG byte string, or None when qrcode is absent."""
    if not _QR:
        return None
    qr = qrcode.QRCode(border=border, box_size=box_size)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="white", back_color="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
