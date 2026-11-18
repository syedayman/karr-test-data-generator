"""Pictures drawn locally: a fallback render, simple logos, a section and a plan.

The AI render (ai.generate_render) replaces `fallback_render` when a key is
set. Everything here is plain Pillow so the app works offline.
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def fallback_render(spec: dict, seed: int) -> bytes:
    """Flat elevation-style illustration of the building's floor stack."""
    rng = random.Random(seed)
    floors = [f for f in spec["floors"] if not str(f["name"]).upper().startswith("B")]
    w, h = 1536, 1024
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # sky gradient
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(120 + 90 * t), int(170 + 60 * t), int(225 + 20 * t)))
    ground_y = int(h * 0.86)
    d.rectangle([0, ground_y, w, h], fill=(196, 182, 150))
    n = max(1, len(floors))
    floor_px = min(26, (ground_y - 90) / n)
    bw = rng.randint(380, 560) if n > 12 else rng.randint(600, 900)
    x0 = (w - bw) // 2
    glass = rng.choice([(70, 110, 140), (90, 120, 120), (60, 90, 120)])
    frame = rng.choice([(230, 230, 225), (210, 200, 185), (80, 80, 85)])
    for i, f in enumerate(reversed(floors)):
        y1 = ground_y - i * floor_px
        y0 = y1 - floor_px + 2
        podium = i < 2
        xa, xb = (x0 - 90, x0 + bw + 90) if podium else (x0, x0 + bw)
        d.rectangle([xa, y0, xb, y1], fill=frame)
        for wx in range(xa + 8, xb - 8, 34):
            d.rectangle([wx, y0 + 3, wx + 24, y1 - 3], fill=glass)
    top_y = ground_y - n * floor_px
    d.rectangle([x0 + bw * 0.3, top_y - 30, x0 + bw * 0.7, top_y], fill=frame)
    for tx in range(60, w, 220):  # palms
        if x0 - 120 < tx < x0 + bw + 120:
            continue
        d.line([(tx, ground_y), (tx + 6, ground_y - 120)], fill=(110, 80, 50), width=8)
        d.ellipse([tx - 50, ground_y - 160, tx + 60, ground_y - 100], fill=(60, 120, 60))
    d.text((24, 20), spec["project_info"]["project_name"], fill=(255, 255, 255), font=_font(44, True))
    d.text((24, 74), "Illustrative render - fictional test project", fill=(240, 240, 240), font=_font(24))
    return _png(img)


def logo(name: str, seed: int) -> bytes:
    rng = random.Random(seed)
    colour = rng.choice([(20, 60, 110), (120, 40, 40), (30, 100, 80), (90, 60, 120), (40, 40, 40)])
    img = Image.new("RGB", (600, 240), (255, 255, 255))
    d = ImageDraw.Draw(img)
    initials = "".join(word[0] for word in name.split()[:2]).upper()
    d.rounded_rectangle([20, 40, 180, 200], radius=28, fill=colour)
    f = _font(76, True)
    tw = d.textlength(initials, font=f)
    d.text((100 - tw / 2, 78), initials, fill=(255, 255, 255), font=f)
    words = name.split()
    lines = [" ".join(words[: len(words) // 2 + 1]), " ".join(words[len(words) // 2 + 1:])]
    d.text((205, 70), lines[0], fill=colour, font=_font(40, True))
    if lines[1]:
        d.text((205, 122), lines[1], fill=(90, 90, 90), font=_font(32))
    return _png(img)


def section_figure(spec: dict, derived: dict) -> bytes:
    """Schematic building section: floors with FFL labels and the lift run."""
    from .excel import floor_levels

    floors = spec["floors"]
    levels = floor_levels(floors)
    n = len(floors)
    row = max(16, min(34, 1500 // n))
    w, h = 1400, row * n + 160
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_small, f_head = _font(max(11, row - 10)), _font(30, True)
    d.text((40, 20), f"{spec['project_info']['project_name']} - schematic section", fill=(0, 0, 0), font=f_head)
    top_name, bottom_name = derived["passenger_top"], derived["passenger_bottom"]
    names = [f["name"] for f in floors]
    run_top, run_bottom = names.index(top_name), names.index(bottom_name)
    x0, x1 = 360, 1000
    for i, (f, lvl) in enumerate(zip(floors, levels)):
        y = 90 + i * row
        fill = (235, 240, 248) if f.get("occupied") else (245, 238, 225) if f.get("boarding") else (240, 240, 240)
        d.rectangle([x0, y, x1, y + row], fill=fill, outline=(120, 120, 120))
        d.text((40, y + 2), f"{f['name']}", fill=(0, 0, 0), font=f_small)
        d.text((150, y + 2), f"FFL {lvl:+.2f}", fill=(60, 60, 60), font=f_small)
        d.text((x0 + 10, y + 2), str(f["use"])[:48], fill=(40, 40, 40), font=f_small)
    sx = x1 + 60
    d.rectangle([sx, 90 + run_top * row, sx + 60, 90 + (run_bottom + 1) * row], outline=(200, 40, 40), width=4)
    d.text((sx + 75, 90 + run_top * row), "Passenger lifts", fill=(200, 40, 40), font=f_small)
    d.text((sx + 75, 90 + run_top * row + row), f"Travel {derived['passenger_travel_m']} m",
           fill=(200, 40, 40), font=f_small)
    return _png(img)


def plan_figure(spec: dict) -> bytes:
    """Schematic typical-floor plan with a central lift core."""
    b = spec["building"]
    lifts = max(1, b.get("passenger_lifts_prelim", 2))
    fire = max(1, b.get("fire_service_lifts_prelim", 1))
    w, h = 1400, 900
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 20), f"{spec['project_info']['project_name']} - typical floor plan (schematic)",
           fill=(0, 0, 0), font=_font(30, True))
    d.rectangle([100, 100, 1300, 820], outline=(0, 0, 0), width=6)
    cx0, cy0 = 470, 330
    d.rectangle([cx0, cy0, cx0 + 460, cy0 + 260], fill=(230, 230, 230), outline=(0, 0, 0), width=3)
    per_row = (lifts + 1) // 2
    size = min(90, 420 // max(per_row, 1))
    for i in range(lifts):
        r, c = divmod(i, per_row)
        x = cx0 + 20 + c * (size + 8)
        y = cy0 + 20 + r * (size + 70)
        d.rectangle([x, y, x + size, y + size], outline=(30, 60, 140), width=3)
        d.line([(x, y), (x + size, y + size)], fill=(30, 60, 140), width=2)
        d.text((x + 6, y + size + 4), f"P{i + 1}", fill=(30, 60, 140), font=_font(20))
    for j in range(fire):
        x = cx0 + 460 - 20 - (j + 1) * (size + 8)
        y = cy0 + 260 - size - 20
        d.rectangle([x, y, x + size, y + size], outline=(190, 40, 40), width=3)
        d.text((x + 6, y - 26), f"F{j + 1}", fill=(190, 40, 40), font=_font(20))
    d.text((cx0, cy0 + 270), "Lift core (preliminary)", fill=(0, 0, 0), font=_font(22))
    for x in range(140, 1280, 190):
        d.rectangle([x, 120, x + 150, 290], outline=(150, 150, 150), width=2)
        d.rectangle([x, 630, x + 150, 800], outline=(150, 150, 150), width=2)
    return _png(img)
