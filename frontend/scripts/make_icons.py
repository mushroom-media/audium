"""Renders the PWA icons (PNG) from the same shape as favicon.svg. Run in the dev container:
   docker compose -f docker-compose.dev.yml run --rm -v ./frontend:/frontend dev python /frontend/scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "public"
BG = (17, 18, 20)
FG = (233, 184, 114)
# Bars in a 64x64 grid: (x, y, w, h), like favicon.svg
BARS = [(14, 26, 6, 12), (24, 18, 6, 28), (34, 12, 6, 40), (44, 22, 6, 20)]


def render(size: int, maskable: bool) -> Image.Image:
    scale = 4  # draw large, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGB", (s, s), BG) if maskable else Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not maskable:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BG)
    # Maskable icons must keep their content inside the central 80 % "safe zone".
    content = 0.62 if maskable else 0.86
    unit = s * content / 64
    off = (s - 64 * unit) / 2
    for x, y, w, h in BARS:
        d.rounded_rectangle(
            (off + x * unit, off + y * unit, off + (x + w) * unit, off + (y + h) * unit),
            radius=w * unit / 2,
            fill=FG,
        )
    return img.resize((size, size), Image.Resampling.LANCZOS)


for name, size, maskable in [
    ("icon-192.png", 192, False),
    ("icon-512.png", 512, False),
    ("icon-maskable-512.png", 512, True),
    ("apple-touch-icon.png", 180, True),
]:
    render(size, maskable).save(OUT / name, optimize=True)
    print("wrote", name)
