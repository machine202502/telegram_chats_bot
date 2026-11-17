"""HD-варианты иконки telegram_chats_bot: 8 концепций + контактный лист."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 1600
OUT = Path(__file__).resolve().parent / "assets" / "icon-hd"
FONT = "C:/Windows/Fonts/segoeuib.ttf"


def gradient(size: int, c1: tuple[int, int, int], c2: tuple[int, int, int],
             angle: float = 45.0) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    rad = math.radians(angle)
    proj = (x * math.cos(rad) + y * math.sin(rad))
    proj -= proj.min()
    proj /= max(1.0, proj.max())
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(3):
        arr[:, :, i] = (c1[i] + (c2[i] - c1[i]) * proj).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def radial_glow(size: int, center: tuple[float, float], radius: float,
                color: tuple[int, int, int, int], blur: float = 0.08) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center[0] * size, center[1] * size
    r = radius * size
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    return layer.filter(ImageFilter.GaussianBlur(size * blur))


def squircle(size: int, radius: float = 0.235) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius), fill=255
    )
    return mask


def plane_polygons(s: int, scale: float = 1.0, offset: tuple[float, float] = (0.5, 0.5)):
    cx, cy = s * offset[0], s * offset[1]

    def p(x: float, y: float):
        return (cx + (x - 0.5) * s * scale, cy + (y - 0.5) * s * scale)

    left = p(0.05, 0.47)
    nose = p(0.96, 0.10)
    fold = p(0.60, 0.68)
    tail = p(0.42, 0.92)
    notch = p(0.55, 0.61)
    return [left, nose, fold, tail], [fold, tail, notch], (left, fold)


def plane_shadow(s: int, scale: float, offset: tuple[float, float],
                 dy: float = 0.012, alpha: int = 85) -> Image.Image:
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    body, _, _ = plane_polygons(s, scale, (offset[0], offset[1] + dy))
    d.polygon(body, fill=(2, 28, 48, alpha))
    return layer.filter(ImageFilter.GaussianBlur(s * 0.012))


def draw_plane(base: Image.Image, scale: float = 0.92, offset: tuple[float, float] = (0.5, 0.5),
               body=(255, 255, 255, 255), fold=(196, 228, 246, 255),
               outline=None, shadow: bool = True) -> Image.Image:
    s = base.size[0]
    if shadow:
        base = Image.alpha_composite(base, plane_shadow(s, scale, offset))
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    body_poly, fold_poly, line = plane_polygons(s, scale, offset)
    if outline:
        d.polygon(body_poly, fill=outline)
        d.line(body_poly + [body_poly[0]], fill=outline, width=max(2, s // 200), joint="curve")
    d.polygon(body_poly, fill=body)
    d.polygon(fold_poly, fill=fold)
    d.line(line, fill=(255, 255, 255, 150), width=max(2, s // 300))
    return Image.alpha_composite(base, layer)


def bubble_shape(s: int, scale: float = 0.74, offset=(0.5, 0.44), color=(255, 255, 255, 255)):
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w = s * scale
    cx, cy = s * offset[0], s * offset[1]
    left, top = cx - w / 2, cy - w * 0.38
    right, bottom = cx + w / 2, cy + w * 0.38
    radius = int(w * 0.16)
    d.rounded_rectangle((left, top, right, bottom), radius=radius, fill=color)
    d.polygon(
        [(left + w * 0.22, bottom - 1), (left + w * 0.12, bottom + w * 0.24),
         (left + w * 0.40, bottom - 1)],
        fill=color,
    )
    return layer


def add_dots(base: Image.Image, count: int = 26, alpha: int = 45) -> Image.Image:
    s = base.size[0]
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = np.random.default_rng(7)
    for _ in range(count):
        x = float(rng.uniform(0.06, 0.94)) * s
        y = float(rng.uniform(0.06, 0.94)) * s
        r = float(rng.uniform(0.002, 0.006)) * s
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, alpha))
    return Image.alpha_composite(base, layer)


def v_aurora() -> Image.Image:
    s = SIZE
    base = gradient(s, (86, 212, 255), (82, 84, 220), 35)
    base = Image.alpha_composite(base, radial_glow(s, (0.2, 0.1), 0.7, (255, 255, 255, 55), 0.12))
    base = Image.alpha_composite(base, radial_glow(s, (0.9, 0.85), 0.6, (255, 110, 210, 45), 0.14))
    base = add_dots(base)
    base = draw_plane(base, 0.92)
    base.putalpha(squircle(s))
    return base


def v_bubble() -> Image.Image:
    s = SIZE
    base = gradient(s, (52, 172, 235), (10, 72, 118), 60)
    base = Image.alpha_composite(base, radial_glow(s, (0.3, 0.1), 0.6, (255, 255, 255, 55), 0.1))
    shadow = bubble_shape(s, 0.76, (0.5, 0.46), (2, 24, 44, 110)).filter(
        ImageFilter.GaussianBlur(s * 0.02))
    base = Image.alpha_composite(base, shadow)
    base = Image.alpha_composite(base, bubble_shape(s, 0.74, (0.5, 0.43)))
    plane = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    plane = draw_plane(plane, 0.48, (0.5, 0.38), body=(39, 143, 199, 255),
                       fold=(120, 194, 233, 255), outline=None, shadow=False)
    mask = bubble_shape(s, 0.74, (0.5, 0.43)).getchannel("A")
    plane.putalpha(Image.composite(plane.getchannel("A"), Image.new("L", (s, s), 0), mask))
    base = Image.alpha_composite(base, plane)
    base.putalpha(squircle(s))
    return base


def v_plane3d() -> Image.Image:
    s = SIZE
    base = gradient(s, (238, 249, 255), (176, 220, 246), 70)
    base = Image.alpha_composite(base, radial_glow(s, (0.25, 0.15), 0.55, (255, 255, 255, 160), 0.1))
    # тонкая сетка
    grid = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for i in range(1, 12):
        pos = s * i / 12
        gd.line([(pos, 0), (pos, s)], fill=(30, 110, 160, 18), width=2)
        gd.line([(0, pos), (s, pos)], fill=(30, 110, 160, 18), width=2)
    base = Image.alpha_composite(base, grid)
    base = draw_plane(base, 0.86, (0.5, 0.48), body=(255, 255, 255, 255),
                      fold=(190, 226, 246, 255))
    base.putalpha(squircle(s, 0.22))
    return base


def v_neon() -> Image.Image:
    s = SIZE
    base = Image.new("RGBA", (s, s), (5, 12, 24, 255))
    base = Image.alpha_composite(base, radial_glow(s, (0.5, 0.45), 0.55, (0, 140, 220, 90), 0.1))
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    body, fold, _ = plane_polygons(s, 0.84)
    ImageDraw.Draw(layer).polygon(body, fill=(90, 224, 255, 255))
    glow = layer.filter(ImageFilter.GaussianBlur(s * 0.025))
    base = Image.alpha_composite(base, glow)
    base = draw_plane(base, 0.84, body=(235, 252, 255, 255), fold=(90, 200, 240, 255),
                      shadow=False)
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((s * 0.08, s * 0.08, s * 0.92, s * 0.92),
                                 outline=(80, 210, 255, 130), width=max(2, s // 400))
    base = Image.alpha_composite(base, ring)
    base.putalpha(squircle(s))
    return base


def v_glass() -> Image.Image:
    s = SIZE
    base = gradient(s, (20, 120, 180), (70, 60, 160), 50)
    base = Image.alpha_composite(base, radial_glow(s, (0.85, 0.15), 0.5, (90, 230, 255, 110), 0.1))
    base = Image.alpha_composite(base, radial_glow(s, (0.15, 0.85), 0.55, (255, 120, 190, 90), 0.12))
    glass = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle((s * 0.08, s * 0.08, s * 0.92, s * 0.92), radius=int(s * 0.18),
                         fill=(255, 255, 255, 34), outline=(255, 255, 255, 90),
                         width=max(2, s // 400))
    base = Image.alpha_composite(base, glass)
    base = draw_plane(base, 0.80, body=(255, 255, 255, 245), fold=(220, 240, 255, 255),
                      shadow=False)
    base.putalpha(squircle(s))
    return base


def v_bot() -> Image.Image:
    s = SIZE
    base = gradient(s, (40, 150, 210), (9, 56, 96), 65)
    base = Image.alpha_composite(base, radial_glow(s, (0.5, 0.1), 0.5, (255, 255, 255, 50), 0.1))
    bubble = bubble_shape(s, 0.74, (0.5, 0.44), (255, 255, 255, 255))
    shadow = bubble_shape(s, 0.76, (0.5, 0.47), (2, 24, 44, 100)).filter(
        ImageFilter.GaussianBlur(s * 0.02))
    base = Image.alpha_composite(base, shadow)
    base = Image.alpha_composite(base, bubble)
    d = ImageDraw.Draw(base)
    # голова робота
    cx, cy = s * 0.5, s * 0.40
    w, h = s * 0.30, s * 0.22
    d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
                        radius=int(s * 0.05), fill=(41, 143, 199, 255))
    d.rounded_rectangle((cx - w / 2 + s * 0.03, cy - h / 2 + s * 0.03,
                         cx + w / 2 - s * 0.03, cy + h / 2 - s * 0.03),
                        radius=int(s * 0.035), fill=(235, 250, 255, 255))
    # глаза
    for dx in (-0.07, 0.07):
        d.ellipse((cx + s * dx - s * 0.022, cy - s * 0.018,
                   cx + s * dx + s * 0.022, cy + s * 0.026), fill=(32, 120, 170, 255))
    # антенна
    d.line((cx, cy - h / 2, cx, cy - h / 2 - s * 0.06), fill=(41, 143, 199, 255),
           width=max(3, s // 200))
    d.ellipse((cx - s * 0.018, cy - h / 2 - s * 0.08, cx + s * 0.018,
               cy - h / 2 - s * 0.044), fill=(41, 143, 199, 255))
    base.putalpha(squircle(s))
    return base


def v_minimal() -> Image.Image:
    s = SIZE
    base = Image.new("RGBA", (s, s), (246, 250, 253, 255))
    base = Image.alpha_composite(base, radial_glow(s, (0.2, 0.1), 0.6, (255, 255, 255, 200), 0.1))
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    body, fold, line = plane_polygons(s, 0.78)
    ImageDraw.Draw(layer).polygon(body, fill=(30, 136, 196, 255))
    ImageDraw.Draw(layer).polygon(fold, fill=(120, 196, 236, 255))
    glow = layer.filter(ImageFilter.GaussianBlur(s * 0.02))
    base = Image.alpha_composite(base, glow)
    base = draw_plane(base, 0.78, body=(255, 255, 255, 255), fold=(178, 218, 242, 255),
                      outline=(30, 136, 196, 255), shadow=True)
    base.putalpha(squircle(s))
    return base


def v_sticker() -> Image.Image:
    s = SIZE
    base = gradient(s, (50, 190, 245), (9, 100, 158), 55)
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    body, fold, _ = plane_polygons(s, 0.88, (0.52, 0.55))
    ImageDraw.Draw(layer).polygon(body, fill=(6, 44, 76, 190))
    base = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(s * 0.008)))
    base = draw_plane(base, 0.88, (0.5, 0.50), body=(255, 255, 255, 255),
                      fold=(186, 225, 246, 255), outline=(15, 84, 130, 255), shadow=False)
    base.putalpha(squircle(s, 0.26))
    return base


def label_sheet(items: list[tuple[str, Image.Image]]) -> None:
    cols, tile, pad = 4, 380, 26
    rows = math.ceil(len(items) / cols)
    width = cols * tile + (cols + 1) * pad
    height = rows * (tile + 54) + (rows + 1) * pad + 40
    sheet = Image.new("RGB", (width, height), (12, 20, 28))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FONT, 24) if Path(FONT).is_file() else ImageFont.load_default()
    title_font = ImageFont.truetype(FONT, 30) if Path(FONT).is_file() else font
    d.text((pad, 12), "telegram_chats_bot — варианты иконки", font=title_font, fill=(235, 245, 252))
    for index, (name, image) in enumerate(items):
        col, row = index % cols, index // cols
        x = pad + col * (tile + pad)
        y = 58 + pad + row * (tile + 54 + pad)
        sheet.paste(image.convert("RGB").resize((tile, tile), Image.LANCZOS), (x, y))
        d.text((x, y + tile + 10), name, font=font, fill=(180, 205, 222))
    sheet.save(OUT / "all-variants.jpg", quality=95)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    variants = [
        ("A — Aurora", v_aurora),
        ("B — Chat bubble", v_bubble),
        ("C — 3D plane", v_plane3d),
        ("D — Neon", v_neon),
        ("E — Glass", v_glass),
        ("F — Bot chat", v_bot),
        ("G — Minimal", v_minimal),
        ("H — Sticker", v_sticker),
    ]
    made: list[tuple[str, Image.Image]] = []
    for name, builder in variants:
        icon = builder()
        icon.resize((768, 768), Image.LANCZOS).save(OUT / f"{name.split(' — ')[0].lower()}.png")
        made.append((name, icon))
    label_sheet(made)
    print("Готово:", OUT / "all-variants.jpg")


if __name__ == "__main__":
    main()
