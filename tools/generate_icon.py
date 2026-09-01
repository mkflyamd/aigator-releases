"""Generate the AI Gator app icon at high resolution from the SVG design.

The SVG at web/static/favicon.svg is the canonical design (32x32 viewBox,
gator head top-down). electron-builder on macOS requires an icon of at least
512x512 pixels; tray/aigator_icon.png is only 256x256, so the macOS release
build fails with "Icon must be at least 512x512 pixels, provided: 256x256".

cairosvg is a runtime dependency but cannot render on machines without the
native cairo library installed (notably the Windows dev box and any CI runner
without libcairo). This script reproduces the SVG geometry natively with PIL
at any scale, so the high-res icon can be regenerated without cairo.

Outputs:
  build/aigator_icon_1024.png  - 1024x1024 RGBA PNG (macOS/Linux app icon)

This script does NOT touch build/aigator_icon.ico. That is the canonical
Windows ICO (hand-tuned, tracked in git) used by the Windows taskbar thumbnail
and the NSIS installer. Replacing it with a PIL approximation caused the
taskbar thumbnail to fall back to a different icon. Only the PNG is generated.

Usage:
  uv run python tools/generate_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

# The SVG viewBox is 32x32; we render at 32x scale => 1024px output. All
# coordinates below are in SVG units and multiplied by SCALE at draw time.
SCALE = 32
SIZE = 32 * SCALE  # 1024
OUT_PNG = ROOT / "build" / "aigator_icon_1024.png"


def _s(v: float) -> float:
    return v * SCALE


def _ellipse(draw, cx, cy, rx, ry, **kw):
    draw.ellipse([_s(cx - rx), _s(cy - ry), _s(cx + rx), _s(cy + ry)], **kw)


def _circle(draw, cx, cy, r, **kw):
    _ellipse(draw, cx, cy, r, r, **kw)


def render(size: int = SIZE) -> Image.Image:
    """Render the favicon.svg design at the given pixel size (square, RGBA)."""
    scale = size / 32.0

    def s(v: float) -> float:
        return v * scale

    def ellipse(cx, cy, rx, ry, **kw):
        ImageDraw.Draw(img).ellipse(
            [s(cx - rx), s(cy - ry), s(cx + rx), s(cy + ry)], **kw
        )

    def circle(cx, cy, r, **kw):
        ellipse(cx, cy, r, r, **kw)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark app-toned background (rounded rect, rx=7 in SVG units).
    d.rounded_rectangle(
        [0, 0, s(32), s(32)], radius=round(s(7)), fill="#0c1a0f"
    )

    # Gator head (top-down view).
    ellipse(16, 19, 11, 8.5, fill="#166534")

    # Snout pointing upward. SVG path: M10 13 Q16 5 22 13 L21 16 Q16 13.5 11 16 Z
    # Approximated as a filled polygon with quadratic-curve control points
    # sampled at t=0,0.25,0.5,0.75,1.
    def quad(p0, p1, p2, n=24):
        pts = []
        for i in range(n + 1):
            t = i / n
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
            pts.append((s(x), s(y)))
        return pts

    top = quad((10, 13), (16, 5), (22, 13))
    right = [(s(22), s(13)), (s(21), s(16))]
    bottom = list(reversed(quad((11, 16), (16, 13.5), (21, 16))))
    left = [(s(11), s(16)), (s(10), s(13))]
    d.polygon(top + right + bottom + left, fill="#22c55e")

    # Nostrils.
    circle(13.5, 9.5, 1.3, fill="#14532d")
    circle(18.5, 9.5, 1.3, fill="#14532d")

    # Left eye.
    circle(7, 15, 3.5, fill="#eab308")
    ellipse(7, 15, 1.2, 2.2, fill="#0c0c0c")
    circle(6.4, 13.8, 0.8, fill=(255, 255, 255, 89))  # 0.35 opacity

    # Right eye.
    circle(25, 15, 3.5, fill="#eab308")
    ellipse(25, 15, 1.2, 2.2, fill="#0c0c0c")
    circle(24.4, 13.8, 0.8, fill=(255, 255, 255, 89))

    # Mouth line: M7 22 Q16 28.5 25 22 (stroke width 1.5).
    mouth = quad((7, 22), (16, 28.5), (25, 22), n=48)
    for i in range(len(mouth) - 1):
        d.line([mouth[i], mouth[i + 1]], fill="#14532d", width=max(1, round(s(1.5))))

    # Teeth.
    def rect(x, y, w, h, **kw):
        d.rounded_rectangle(
            [s(x), s(y), s(x + w), s(y + h)], radius=max(0.4, round(s(0.8))), **kw
        )

    rect(12, 21, 2, 3, fill=(255, 255, 255, 230))    # opacity 0.9
    rect(15.5, 21.5, 1.5, 2.5, fill=(255, 255, 255, 230))
    rect(18.5, 21, 2, 3, fill=(255, 255, 255, 230))

    return img


def main() -> None:
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

    big = render(SIZE)
    big.save(OUT_PNG, "PNG")
    print(f"Wrote {OUT_PNG.relative_to(ROOT)} ({big.size[0]}x{big.size[1]})")


if __name__ == "__main__":
    main()
