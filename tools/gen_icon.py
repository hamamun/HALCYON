#!/usr/bin/env python3
"""Generate the Halcyon app icon (the "Glass Pane" mark) and its exports.

Reproducible master → derived assets, so the icon can be regenerated exactly:

    python tools/gen_icon.py

Outputs (all committed, needed at runtime):

    assets/halcyon.ico                multi-size Windows icon 16→256 px
    assets/halcyon.png                full tile, 512 px
    assets/halcyon-glyph.png          transparent in-app mark, 512 px
    remote/static/icons/halcyon-*.png browser/PWA/Apple exports

Design (final, from concept "C · Glass Pane"):

    * a Windows-11 squircle tile on the app's aurora-glass base (#0B0E14) with
      a faint teal/violet aurora glow and a soft top sheen;
    * a rounded-rectangle "pane of glass" outline in the accent gradient
      (teal #5EEAD4 → violet #A78BFA) — the same tokens as ``Theme.accent`` /
      ``Theme.accentAlt``;
    * a bold play triangle filled with the same gradient;
    * a subtle reflection line across the lower third — the glass cue.

The geometry is authored in a 1024-unit space and rendered at 4× supersampling
for clean anti-aliased edges at every export size, especially the 16 px title
bar mark.

This needs Pillow only (``python -m pip install Pillow``) and never touches Qt,
so it also runs on the CI/headless box.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
REMOTE_ICONS = ROOT / "remote" / "static" / "icons"

# The app's own design tokens (keep in sync with ui/Theme.qml).
TEAL = (94, 234, 212)      # Theme.accent
VIOLET = (167, 139, 250)   # Theme.accentAlt
BASE = (11, 14, 20)        # Theme.base

# ICO sizes Windows actually requests (plus the uncommon-but-harmless 20/40).
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _hgrad(size: int, c1: tuple, c2: tuple) -> Image.Image:
    """A horizontal c1→c2 gradient, size × size, opaque."""
    g = Image.new("RGBA", (size, 1), (0, 0, 0, 0))
    px = g.load()
    for x in range(size):
        t = x / max(1, size - 1)
        px[x, 0] = (
            round(c1[0] + (c2[0] - c1[0]) * t),
            round(c1[1] + (c2[1] - c1[1]) * t),
            round(c1[2] + (c2[2] - c1[2]) * t),
            255,
        )
    return g.resize((size, size))


def _set_alpha(img: Image.Image, mask: Image.Image) -> Image.Image:
    """Replace an image's alpha with a mask (RGB from `img`, alpha from `mask`)."""
    r, g, b, _ = img.split()
    return Image.merge("RGBA", (r, g, b, mask))


def _ring_mask(size: int, box: list, radius: float, stroke: float) -> Image.Image:
    """L-mode mask: a rounded-rect outline of `stroke` width."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle(box, radius=radius, fill=255)
    d.rounded_rectangle(
        [box[0] + stroke, box[1] + stroke, box[2] - stroke, box[3] - stroke],
        radius=max(1.0, radius - stroke),
        fill=0,
    )
    return m


def _poly_mask(size: int, pts: list) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


def _render_glyph(ss: int = 4) -> Image.Image:
    """The transparent "glass pane" mark at 512 px (from 1024-unit geometry)."""
    S = 512
    R = S * ss
    k = R / 1024.0

    def s(v: float) -> float:
        return v * k

    canvas = Image.new("RGBA", (R, R), (0, 0, 0, 0))

    # ---- pane ring (rounded-rect outline) in the accent gradient ----
    box = [s(234), s(206), s(790), s(818)]
    ring_radius = s(124)
    stroke = s(44)
    ring_mask = _ring_mask(R, box, ring_radius, stroke)
    ring = _set_alpha(_hgrad(R, TEAL, VIOLET), ring_mask)

    # Soft colored halo behind the ring so it glows over dark tiles.
    halo = ring.filter(ImageFilter.GaussianBlur(s(46)))
    r, g, b, a = halo.split()
    a = a.point(lambda v: round(v * 0.30))
    halo = Image.merge("RGBA", (r, g, b, a))
    canvas = Image.alpha_composite(canvas, halo)
    canvas = Image.alpha_composite(canvas, ring)

    # ---- play triangle, filled with the same gradient ----
    cx, cy = s(512), s(486)
    hw, hh = s(104), s(122)
    tri = _poly_mask(R, [(cx + hw, cy), (cx - hw, cy - hh), (cx - hw, cy + hh)])
    canvas = Image.alpha_composite(canvas, _set_alpha(_hgrad(R, TEAL, VIOLET), tri))

    # ---- reflection line (the glass cue) ----
    ref = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ref)
    rw, rh = s(224), s(16)
    rx, ry = cx - rw / 2, s(706) - rh / 2
    rd.rounded_rectangle([rx, ry, rx + rw, ry + rh], radius=rh / 2,
                         fill=(255, 255, 255, 130))
    canvas = Image.alpha_composite(canvas, ref)

    return canvas.resize((S, S), Image.LANCZOS)


def _render_tile(ss: int = 2, glyph: Image.Image | None = None) -> Image.Image:
    """The full squircle tile at 1024 px with the glyph composited on top."""
    S = 1024
    R = S * ss
    k = R / 1024.0

    def s(v: float) -> float:
        return v * k

    tile = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle([0, 0, R, R], radius=s(230), fill=BASE + (255,))
    shape = tile.split()[3]

    # Aurora glow — teal top-left, violet bottom-right, clipped to the tile.
    glows = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glows)
    gd.ellipse([s(-140), s(-180), s(-140) + s(860), s(-180) + s(860)],
               fill=TEAL + (72,))
    gd.ellipse([s(250), s(330), s(250) + s(860), s(330) + s(860)],
               fill=VIOLET + (72,))
    glows = glows.filter(ImageFilter.GaussianBlur(s(180)))
    glows = _set_alpha(glows, ImageChops.multiply(glows.split()[3], shape))
    tile = Image.alpha_composite(tile, glows)

    # Top sheen — a soft white falloff over the upper third.
    sheen = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rectangle([0, 0, R, s(320)], fill=(255, 255, 255, 22))
    sheen = sheen.filter(ImageFilter.GaussianBlur(s(150)))
    sheen = _set_alpha(sheen, ImageChops.multiply(sheen.split()[3], shape))
    tile = Image.alpha_composite(tile, sheen)

    # Glyph, scaled to the full tile canvas.
    if glyph is not None:
        tile = Image.alpha_composite(tile, glyph.resize((R, R), Image.LANCZOS))

    return tile.resize((S, S), Image.LANCZOS)


def _export_remote_icons(tile: Image.Image) -> dict[str, Path]:
    """Write browser, Apple touch, and maskable PWA icon variants."""
    REMOTE_ICONS.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for size in (32, 192, 512):
        path = REMOTE_ICONS / f"halcyon-{size}.png"
        tile.resize((size, size), Image.LANCZOS).save(path, format="PNG", optimize=True)
        outputs[f"web-{size}"] = path

    # Apple recommends an opaque touch icon; otherwise iOS chooses the colour
    # behind the transparent squircle corners itself.
    apple = Image.new("RGBA", (180, 180), BASE + (255,))
    apple.alpha_composite(tile.resize((180, 180), Image.LANCZOS))
    apple_path = REMOTE_ICONS / "halcyon-180.png"
    apple.convert("RGB").save(apple_path, format="PNG", optimize=True)
    outputs["apple-180"] = apple_path

    # Maskable icons may be cropped into circles/squircles by the OS. Keep the
    # complete tile inside the standard 80% safe zone on an opaque app-colour
    # canvas, rather than allowing Android to cut through the Halcyon mark.
    maskable = Image.new("RGBA", (512, 512), BASE + (255,))
    safe_tile = tile.resize((400, 400), Image.LANCZOS)
    maskable.alpha_composite(safe_tile, (56, 56))
    maskable_path = REMOTE_ICONS / "halcyon-maskable-512.png"
    maskable.save(maskable_path, format="PNG", optimize=True)
    outputs["maskable-512"] = maskable_path
    return outputs


def build() -> dict[str, Path]:
    glyph = _render_glyph(ss=4)
    tile = _render_tile(ss=2, glyph=glyph)

    ASSETS.mkdir(parents=True, exist_ok=True)

    ico_path = ASSETS / "halcyon.ico"
    # Pillow writes the ICO from the largest source and LANCZOS-downscales to
    # every requested size — so hand it the 1024 px master, not a small frame.
    tile.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )

    png_path = ASSETS / "halcyon.png"
    tile.resize((512, 512), Image.LANCZOS).save(png_path, format="PNG")

    glyph_path = ASSETS / "halcyon-glyph.png"
    glyph.save(glyph_path, format="PNG")

    outputs = {"ico": ico_path, "tile": png_path, "glyph": glyph_path}
    outputs.update(_export_remote_icons(tile))
    return outputs


def main() -> int:
    for name, path in build().items():
        print(f"{name:<6} {path}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
