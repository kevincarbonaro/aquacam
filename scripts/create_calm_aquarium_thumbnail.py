#!/usr/bin/env python3
"""Generate the YouTube thumbnail/banner for The Calm Aquarium."""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "the-calm-aquarium-thumbnail.png"
W, H = 1280, 720


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def centered_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt, fill, stroke_fill=None, stroke_width=0):
    x, y = xy
    box = draw.textbbox((0, 0), text, font=fnt, stroke_width=stroke_width)
    tw = box[2] - box[0]
    th = box[3] - box[1]
    draw.text((x - tw / 2, y - th / 2), text, font=fnt, fill=fill, stroke_fill=stroke_fill, stroke_width=stroke_width)


def rounded_rect_shadow(base, box, radius, fill, shadow=(0, 0, 0, 90), offset=(0, 12), blur=16):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    shifted = (box[0] + offset[0], box[1] + offset[1], box[2] + offset[0], box[3] + offset[1])
    d.rounded_rectangle(shifted, radius, fill=shadow)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(layer)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius, fill=fill)


def fish_logo(base: Image.Image, cx: int, cy: int):
    d = ImageDraw.Draw(base)
    # keychain outer tab / rounded 3D printable silhouette
    rounded_rect_shadow(base, (cx - 210, cy - 170, cx + 210, cy + 170), 70, (240, 250, 247, 255), (0, 43, 58, 80), (0, 16), 18)
    d.rounded_rectangle((cx - 210, cy - 170, cx + 210, cy + 170), 70, outline=(60, 173, 188, 255), width=10)
    d.ellipse((cx - 30, cy - 154, cx + 30, cy - 94), fill=(23, 91, 108, 255))
    d.ellipse((cx - 14, cy - 138, cx + 14, cy - 110), fill=(240, 250, 247, 255))

    # meditation ripple / lotus base
    for i, color in enumerate([(89, 194, 207, 210), (125, 211, 216, 180), (184, 234, 228, 150)]):
        y = cy + 100 + i * 16
        d.arc((cx - 150 + i * 25, y - 28, cx + 150 - i * 25, y + 28), 0, 180, fill=color, width=8)

    # fish tail
    d.polygon([(cx + 118, cy - 5), (cx + 190, cy - 72), (cx + 176, cy + 10), (cx + 190, cy + 92)], fill=(255, 171, 71, 255))
    d.line([(cx + 150, cy - 18), (cx + 188, cy - 70)], fill=(223, 112, 44, 255), width=5)
    d.line([(cx + 150, cy + 18), (cx + 188, cy + 88)], fill=(223, 112, 44, 255), width=5)

    # fish body
    d.ellipse((cx - 145, cy - 86, cx + 145, cy + 86), fill=(255, 191, 88, 255), outline=(223, 112, 44, 255), width=7)
    d.pieslice((cx - 132, cy - 80, cx + 86, cy + 80), 80, 280, fill=(255, 215, 123, 255))
    d.arc((cx - 84, cy - 28, cx - 28, cy + 56), 250, 70, fill=(245, 142, 57, 255), width=5)

    # closed peaceful eye and smile
    d.arc((cx - 82, cy - 32, cx - 42, cy + 8), 205, 335, fill=(23, 91, 108, 255), width=5)
    d.arc((cx - 108, cy + 10, cx - 48, cy + 58), 15, 72, fill=(23, 91, 108, 255), width=4)

    # meditating fins
    d.ellipse((cx - 18, cy + 40, cx + 92, cy + 105), fill=(255, 149, 68, 255), outline=(223, 112, 44, 255), width=5)
    d.ellipse((cx - 42, cy + 20, cx + 24, cy + 88), fill=(255, 166, 74, 255), outline=(223, 112, 44, 255), width=5)

    # bubbles
    for bx, by, r in [(cx - 160, cy - 110, 14), (cx - 125, cy - 146, 9), (cx + 126, cy - 118, 12), (cx + 158, cy - 146, 7)]:
        d.ellipse((bx - r, by - r, bx + r, by + r), outline=(125, 211, 216, 230), width=4)


def main() -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    pix = img.load()
    top = (9, 82, 111)
    bottom = (122, 211, 202)
    for y in range(H):
        t = y / (H - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(W):
            pix[x, y] = (r, g, b, 255)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in [115, 175, 545, 610]:
        od.arc((-80, y - 70, W + 80, y + 70), 0, 180, fill=(255, 255, 255, 28), width=5)
    for x, y, r in [(105, 100, 22), (190, 610, 14), (1110, 130, 18), (1180, 560, 28), (1010, 625, 11)]:
        od.ellipse((x - r, y - r, x + r, y + r), outline=(230, 255, 250, 70), width=4)
    img.alpha_composite(overlay)

    fish_logo(img, 640, 326)
    d = ImageDraw.Draw(img)
    centered_text(d, (640, 575), "THE CALM AQUARIUM", font(66, True), (244, 255, 251, 255), (5, 62, 81, 180), 3)
    centered_text(d, (640, 644), "Live Aquarium Cam", font(34, False), (218, 252, 245, 255), (5, 62, 81, 130), 2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    rgb.save(OUT, optimize=True)
    print(OUT)


if __name__ == "__main__":
    main()
