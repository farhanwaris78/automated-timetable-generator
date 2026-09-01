"""Generate the application icons (no design tools needed).

    python packaging/make_icons.py

Writes packaging/icon.png (512x512), packaging/icon.ico (multi-size) and,
on macOS, packaging/icon.icns.  Requires Pillow (`pip install pillow`).
The generated files are committed, so you normally never need to run this.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
BRAND = (76, 92, 175, 255)
BRAND2 = (107, 91, 181, 255)
WHITE = (255, 255, 255, 255)


def draw(size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 64.0

    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(14 * u), fill=BRAND)
    d.rounded_rectangle([12 * u, 16 * u, 52 * u, 50 * u], radius=int(4 * u), fill=WHITE)
    d.rounded_rectangle([12 * u, 16 * u, 52 * u, 26 * u], radius=int(4 * u), fill=BRAND2)

    cells = [
        (17, 29, 26, 36, 255), (29, 29, 38, 36, 255), (41, 29, 47, 36, 255),
        (17, 39, 26, 46, 140), (29, 39, 47, 46, 205),
    ]
    for x0, y0, x1, y1, alpha in cells:
        d.rounded_rectangle(
            [x0 * u, y0 * u, x1 * u, y1 * u],
            radius=max(1, int(2 * u)),
            fill=(BRAND[0], BRAND[1], BRAND[2], alpha),
        )
    return img


def main() -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Pillow is required:  pip install pillow", file=sys.stderr)
        return 1

    master = draw(512)
    master.save(OUT / "icon.png")
    print("wrote", OUT / "icon.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    print("wrote", OUT / "icon.ico")

    if sys.platform == "darwin":
        iconset = OUT / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 64, 128, 256, 512):
            draw(s).save(iconset / f"icon_{s}x{s}.png")
            draw(s * 2).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
        print("wrote", OUT / "icon.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
