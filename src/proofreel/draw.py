"""What the video draws: the pointer, the click rings, and the frame around the screen. Text is the page's.

Shapes are drawn at 4x and scaled down, because Pillow draws polygons and rounded boxes without antialiasing.
"""

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ACCENT = (10, 132, 255)
FONTS = [
    os.environ.get("PROOFREEL_FONT", ""),
    str(Path.home() / "Library/Fonts/Inter-Regular.ttf"),
    "/Library/Fonts/Inter-Regular.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
SS = 4
ARROW = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.4), (9.6, 18.3), (6.9, 12.2), (12.3, 12.2)]


@lru_cache(maxsize=32)
def font(size):
    for path in FONTS:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def fade(image, alpha):
    if alpha >= 0.999:
        return image
    out = image.copy()
    out.putalpha(image.getchannel("A").point(lambda v: int(v * max(alpha, 0.0))))
    return out


def paste(canvas, sprite, x, y, alpha=1.0):
    if alpha <= 0.01:
        return
    canvas.alpha_composite(fade(sprite, alpha), (int(round(x)), int(round(y))))


@lru_cache(maxsize=64)
def pointer(scale, pressed):
    """The arrow pointer with a soft shadow. Returns the sprite and its tip offset."""
    k = scale * SS * (0.86 if pressed else 1.0)
    pad = int(8 * scale * SS)
    size = (int(14 * k) + 2 * pad, int(22 * k) + 2 * pad)
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).polygon([(pad + x * k + 1.5 * k, pad + y * k + 2.5 * k) for x, y in ARROW], fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(2.2 * k))
    sprite = Image.new("RGBA", size, (0, 0, 0, 0))
    sprite.putalpha(shadow)
    draw = ImageDraw.Draw(sprite)
    draw.polygon([(pad + x * k, pad + y * k) for x, y in ARROW], fill="white")
    inner = _shrink(ARROW, 1.35)
    draw.polygon([(pad + x * k, pad + y * k) for x, y in inner], fill=(0, 0, 0))
    out = sprite.resize((size[0] // SS, size[1] // SS), Image.LANCZOS)
    return out, pad // SS


def _shrink(points, width):
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    return [(x + (cx - x) * width / 9, y + (cy - y) * width / 13) for x, y in points]


def ring(radius, alpha, scale):
    """One frame of the ring that grows out of a click."""
    r = radius * SS
    width = max(2, int(3 * scale * SS))
    size = int(2 * r + 4 * width)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    c = size / 2
    draw.ellipse((c - r, c - r, c + r, c + r), fill=ACCENT + (int(50 * alpha),),
                 outline=ACCENT + (int(230 * alpha),), width=width)
    out = image.resize((max(1, size // SS),) * 2, Image.LANCZOS)
    return out, size / SS / 2


@lru_cache(maxsize=256)
def backdrop(size, screen_box, radius):
    """The frame around the screen: a soft gradient, and a shadow under the screen."""
    w, h = size
    top, bottom = (238, 240, 245), (214, 219, 230)
    column = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        column.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    image = column.resize((w, h)).convert("RGBA")
    left, top_, right, bottom_ = screen_box
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((left, top_ + h * 0.012, right, bottom_ + h * 0.012), radius, fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(h * 0.02))
    dark = Image.new("RGBA", size, (20, 24, 36, 0))
    dark.putalpha(shadow)
    image.alpha_composite(dark)
    return image


def rounded_mask(size, radius):
    big = Image.new("L", (size[0] * 2, size[1] * 2), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size[0] * 2 - 1, size[1] * 2 - 1), radius * 2, fill=255)
    return big.resize(size, Image.LANCZOS)
