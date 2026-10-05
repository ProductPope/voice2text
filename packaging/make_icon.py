"""Draws packaging/dictaitor.ico: a microphone-dot in the app's colours.

Run once after changing the design: python packaging/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8 * s, 8 * s, 248 * s, 248 * s], radius=56 * s, fill=(32, 33, 36, 255))
    # microphone capsule
    d.rounded_rectangle([96 * s, 40 * s, 160 * s, 156 * s], radius=32 * s, fill=(232, 234, 237, 255))
    # holder and stand
    w = max(1, round(12 * s))
    d.arc([68 * s, 92 * s, 188 * s, 196 * s], start=0, end=180, fill=(232, 234, 237, 255), width=w)
    d.line([128 * s, 196 * s, 128 * s, 220 * s], fill=(232, 234, 237, 255), width=w)
    # red "waiting for your word" dot
    d.ellipse([170 * s, 160 * s, 236 * s, 226 * s], fill=(217, 48, 37, 255))
    return img


if __name__ == "__main__":
    out = Path(__file__).with_name("dictaitor.ico")
    draw(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw(256).save(out.with_suffix(".png"))
    print(f"wrote {out}")
