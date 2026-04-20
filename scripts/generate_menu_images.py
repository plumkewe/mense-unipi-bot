import argparse
import datetime as dt
import json
import random
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
MENU_PATH = DATA_DIR / "menu.json"
CANTEENS_PATH = DATA_DIR / "canteens.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "assets" / "posts"

MEAL_ORDER = ["Pranzo", "Cena"]
COURSE_ORDER = [
    "Primi Piatti",
    "Secondi Piatti",
    "Contorni",
]

POST_BG_COLOR = "#F3F4F6"


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def pick_target_date(menu_data: dict, requested_date: str | None, use_latest: bool) -> str:
    if requested_date:
        if requested_date not in menu_data:
            raise ValueError(f"Data {requested_date} non presente in menu.json")
        return requested_date

    today = dt.date.today().isoformat()
    if today in menu_data:
        return today

    if use_latest:
        return max(menu_data.keys())

    raise ValueError(
        f"Menu di oggi ({today}) non trovato. Usa --latest o --date YYYY-MM-DD."
    )


def collect_canteen_menu(day_menu: dict, canteen_name: str) -> dict:
    canteen_menu = {meal: {} for meal in MEAL_ORDER}

    for meal in MEAL_ORDER:
        meal_data = day_menu.get(meal, {})
        if not isinstance(meal_data, dict):
            continue

        all_courses = list(meal_data.keys())
        ordered_courses = [course for course in COURSE_ORDER if course in all_courses]

        for course in ordered_courses:
            dishes = meal_data.get(course, [])
            filtered_names = []
            for dish in dishes:
                available_at = dish.get("available_at", [])
                if canteen_name in available_at:
                    dish_name = str(dish.get("name", "")).strip()
                    if dish_name:
                        filtered_names.append(dish_name)

            if filtered_names:
                canteen_menu[meal][course] = filtered_names

    return canteen_menu


def _strip_piatti(course: str) -> str:
    """Remove the word 'Piatti' (and surrounding spaces) from a course label."""
    return course.replace(" Piatti", "").replace("Piatti ", "").replace("Piatti", "").strip()


def _format_date_label(date_iso: str) -> str:
    try:
        return dt.date.fromisoformat(date_iso).strftime("%d.%m.%Y")
    except ValueError:
        return date_iso


def _random_light_color(date_iso: str, canteen_id: str) -> str:
    # Use the day of the year and year to spread hues apart
    try:
        dt_obj = dt.date.fromisoformat(date_iso)
        day_of_week = dt_obj.weekday()  # 0 to 6
        week_num = dt_obj.isocalendar()[1]
    except ValueError:
        day_of_week = 0
        week_num = 0

    import hashlib
    h = hashlib.sha256(canteen_id.encode('utf-8')).hexdigest()
    canteen_shift = int(h, 16) % 360

    # Golden ratio conjugate is approx 0.618033988749895.
    # We want a different hue each day of the week, well separated
    hue = (canteen_shift / 360.0 + (day_of_week * 0.381966)) % 1.0
    
    # Introduce small variations with week number
    rng = random.Random(f"{date_iso}_{canteen_id}")
    
    # Tiny random hue shift to avoid exact repeats for the same weekday across weeks
    hue = (hue + rng.uniform(-0.05, 0.05)) % 1.0

    saturation = rng.uniform(0.25, 0.5)  # pastel colors (lower saturation)
    value = rng.uniform(0.95, 1.0)
    
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


def _darken_color(hex_color: str, factor: float = 0.75) -> str:
    color = hex_color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    red = max(0, min(255, int(red * factor)))
    green = max(0, min(255, int(green * factor)))
    blue = max(0, min(255, int(blue * factor)))
    blue = max(0, min(255, int(blue * factor)))
    return f"#{red:02X}{green:02X}{blue:02X}"


def _derive_ui_colors(hex_color: str) -> dict:
    color = hex_color.lstrip("#")
    r, g, b = int(color[0:2], 16)/255.0, int(color[2:4], 16)/255.0, int(color[4:6], 16)/255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    
    # Distinctly tinted background (no white) with relative contrast steps
    c_card_bg = colorsys.hsv_to_rgb(h, 0.15, 0.96)  # distinctly colored pastel base
    c_tab_act = c_card_bg
    c_dish_bg = colorsys.hsv_to_rgb(h, 0.20, 0.90)  # slightly more saturated/darker
    c_cat_bg  = colorsys.hsv_to_rgb(h, 0.25, 0.84)  # category/tab background
    c_border  = colorsys.hsv_to_rgb(h, 0.30, 0.76)  # borders
    c_sec     = colorsys.hsv_to_rgb(h, 0.55, 0.45)  # secondary text (high contrast)
    c_title   = colorsys.hsv_to_rgb(h, 0.60, 0.15)  # title text (almost black)

    def to_hex(rgb):
        return f"#{int(rgb[0]*255):02X}{int(rgb[1]*255):02X}{int(rgb[2]*255):02X}"

    return {
        "CARD": to_hex(c_card_bg),
        "TAB_ACTIVE": to_hex(c_tab_act),
        "DISH": to_hex(c_dish_bg),
        "CAT": to_hex(c_cat_bg),
        "BORDER": to_hex(c_border),
        "SECONDARY": to_hex(c_sec),
        "TITLE": to_hex(c_title)
    }

def _lighten_color(hex_color: str, factor: float = 0.95) -> str:
    color = hex_color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    red = int(red + (255 - red) * factor)
    green = int(green + (255 - green) * factor)
    blue = int(blue + (255 - blue) * factor)
    return f"#{red:02X}{green:02X}{blue:02X}"


def _load_font(size: int, bold: bool = False, weight: str = None) -> ImageFont.FreeTypeFont:
    _fonts_dir = REPO_ROOT / "assets" / "fonts"
    if weight:
        font_path = _fonts_dir / f"Poppins-{weight}.ttf"
    elif bold:
        font_path = _fonts_dir / "Poppins-Bold.ttf"
    else:
        font_path = _fonts_dir / "Poppins-Regular.ttf"
    return ImageFont.truetype(str(font_path), size)


def _load_nunito(size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    """Load Nunito variable font at a specific weight (200-1000)."""
    _fonts_dir = REPO_ROOT / "assets" / "fonts"
    font_path = _fonts_dir / "Nunito-latin.ttf"
    font = ImageFont.truetype(str(font_path), size)
    font.set_variation_by_axes([weight])
    return font


def _load_fa_solid(size: int) -> ImageFont.FreeTypeFont:
    """Load FontAwesome Solid font."""
    _fonts_dir = REPO_ROOT / "assets" / "fonts" / "fa-webfonts"
    font_path = _fonts_dir / "fa-solid-900.ttf"
    return ImageFont.truetype(str(font_path), size)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, top, _, bottom = draw.textbbox((0, 0), "Ag", font=font)
    return bottom - top


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def _pattern_color(base_color: str, alpha: int = 150) -> tuple:
    r, g, b = Image.new("RGB", (1, 1), base_color).getpixel((0, 0))
    lum = (r + g + b) / 3
    factor = 1.4 if lum < 160 else 0.55
    pr = min(255, max(0, int(r * factor)))
    pg = min(255, max(0, int(g * factor)))
    pb = min(255, max(0, int(b * factor)))
    return (pr, pg, pb, alpha)


def _generate_background_pattern(base_color: str, width: int, height: int, seed: str, force_pattern: str = None) -> Image.Image:
    rng = random.Random(seed)
    bg = Image.new("RGBA", (width, height), base_color)
    pc = _pattern_color(base_color)

    pattern_type = force_pattern or rng.choice([
        "dot_grid",
        "diagonal_stripes",
        "crosshatch",
        "diamond_grid",
        "zigzag",
        "concentric_circles",
        "plus_grid",
        "waves",
        "triangles",
        "x_shapes",
        "vertical_stripes",
        "horizontal_stripes"
    ])

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if pattern_type == "dot_grid":
        # Offset polka-dot grid — perfectly aligned rows and columns, centered
        spacing = rng.choice([240, 300, 360])
        radius  = spacing // 4
        ox = (width // 2) % spacing
        oy = (height // 2) % spacing
        for row, y in enumerate(range(oy - spacing * 2, height + spacing, spacing)):
            x_offset = (spacing // 2) if (row % 2) else 0
            for x in range(-spacing, width + spacing, spacing):
                cx = x + x_offset + ox
                draw.ellipse((cx - radius, y - radius, cx + radius, y + radius), fill=pc)

    elif pattern_type == "diagonal_stripes":
        # Crisp parallel diagonal stripes at 45°
        spacing   = rng.choice([240, 300, 360])
        thickness = rng.choice([50, 70, 90])
        size      = (width + height) * 2
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        for i in range(-size, size, spacing):
            tmp_draw.line([(i, 0), (i + size, size)], fill=pc, width=thickness)
        rotated = tmp.rotate(0)   # already 45° by construction
        layer.paste(rotated, (-(size - width) // 2, -(size - height) // 2), rotated)

    elif pattern_type == "crosshatch":
        # Regular grid of thin crossing lines, centered
        spacing = rng.choice([240, 300, 360])
        thickness = rng.choice([50, 70, 90])
        ox = (width // 2) % spacing
        oy = (height // 2) % spacing
        for x in range(ox - spacing * 2, width + spacing, spacing):
            draw.line([(x, 0), (x, height)], fill=pc, width=thickness)
        for y in range(oy - spacing * 2, height + spacing, spacing):
            draw.line([(0, y), (width, y)], fill=pc, width=thickness)

    elif pattern_type == "diamond_grid":
        # 45°-rotated square grid (diamond lattice)
        spacing = rng.choice([240, 300, 360])
        thickness = rng.choice([50, 70, 90])
        size = (width + height) * 2
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        for i in range(-size, size, spacing):
            tmp_draw.line([(i, 0), (i, size)], fill=pc, width=thickness)
            tmp_draw.line([(0, i), (size, i)], fill=pc, width=thickness)
        rotated = tmp.rotate(45, center=(size // 2, size // 2))
        layer.paste(rotated, (-(size - width) // 2, -(size - height) // 2), rotated)

 

    elif pattern_type == "zigzag":
        # Horizontal chevron / zigzag bands, centered
        spacing = rng.choice([240, 300, 360])
        amplitude = spacing // 2
        thickness = rng.choice([50, 70, 90])
        step = 60
        ox = (width // 2) % (step * 2)
        oy = (height // 2) % spacing
        for band in range(-1, height // spacing + 2):
            y_base = band * spacing + oy
            pts = []
            for x in range(-step * 2, width + step * 2, step):
                phase = (x // step) % 2
                y = y_base + (amplitude if phase else -amplitude)
                pts.append((x + ox, y))
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=pc, width=thickness)

    elif pattern_type == "concentric_circles":
        # Rings expanding from centre
        cx, cy = width // 2, height // 2
        max_r = int((width ** 2 + height ** 2) ** 0.5 // 2) + 200
        spacing = rng.choice([240, 300, 360])
        thickness = rng.choice([50, 70, 90])
        for r in range(spacing, max_r, spacing):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=pc, width=thickness)

    elif pattern_type == "plus_grid":
        # Evenly spaced + signs on a regular grid, centered
        spacing  = rng.choice([240, 300, 360])
        arm_len  = spacing // 3
        thickness = rng.choice([50, 70, 90])
        ox = (width // 2) % spacing
        oy = (height // 2) % spacing
        for y in range(oy - spacing * 2, height + spacing, spacing):
            for x in range(ox - spacing * 2, width + spacing, spacing):
                draw.line([(x - arm_len, y), (x + arm_len, y)], fill=pc, width=thickness)
                draw.line([(x, y - arm_len), (x, y + arm_len)], fill=pc, width=thickness)

    elif pattern_type == "waves":
        import math
        spacing = rng.choice([240, 300, 360])
        amplitude = spacing // 3
        thickness = rng.choice([50, 70, 90])
        oy = (height // 2) % spacing
        # Center the sine wave horizontally: shift phase so wave is symmetric around center
        cx = width / 2.0
        for y_base in range(oy - spacing * 2, height + spacing, spacing):
            pts = []
            for x in range(-40, width + 80, 40):
                y = y_base + int(math.sin((x - cx) / 100.0) * amplitude)
                pts.append((x, y))
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=pc, width=thickness)

    elif pattern_type == "triangles":
        spacing = rng.choice([240, 300, 360])
        thickness = rng.choice([50, 70, 90])
        ox = (width // 2) % spacing
        oy = (height // 2) % spacing
        for row, y in enumerate(range(oy - spacing * 2, height + spacing, spacing)):
            for col, x in enumerate(range(ox - spacing, width + spacing, spacing)):
                x_off = x + (spacing // 2 if row % 2 == 0 else 0)
                pts = [
                    (x_off, y),
                    (x_off - spacing//2, y + spacing),
                    (x_off + spacing//2, y + spacing)
                ]
                draw.polygon(pts, outline=pc, width=thickness)

 

    elif pattern_type == "x_shapes":
        spacing = rng.choice([240, 300, 360])
        arm_len = spacing // 3
        thickness = rng.choice([50, 70, 90])
        ox = (width // 2) % spacing
        oy = (height // 2) % spacing
        for y in range(oy - spacing * 2, height + spacing, spacing):
            for x in range(ox - spacing * 2, width + spacing, spacing):
                draw.line([(x - arm_len, y - arm_len), (x + arm_len, y + arm_len)], fill=pc, width=thickness)
                draw.line([(x - arm_len, y + arm_len), (x + arm_len, y - arm_len)], fill=pc, width=thickness)

    elif pattern_type == "vertical_stripes":
        spacing = rng.choice([240, 300, 360])
        thickness = spacing // 3
        ox = (width // 2) % spacing
        for x in range(ox - spacing * 2, width + spacing, spacing):
            draw.line([(x, 0), (x, height)], fill=pc, width=thickness)

    elif pattern_type == "horizontal_stripes":
        spacing = rng.choice([240, 300, 360])
        thickness = spacing // 3
        oy = (height // 2) % spacing
        for y in range(oy - spacing * 2, height + spacing, spacing):
            draw.line([(0, y), (width, y)], fill=pc, width=thickness)

    bg.paste(layer, (0, 0), layer)
    return bg


def build_and_save_gt(
    canteen_name: str,
    meal_name: str,
    meal_menu: dict,
    target_date: str,
    accent_color: str,
    output_path: Path,
) -> None:
    date_label = _format_date_label(target_date)

    sections: list[tuple[str, list[str]]] = []
    for course in COURSE_ORDER:
        course_dishes = meal_menu.get(course, [])
        if not course_dishes:
            continue
        section_name = _strip_piatti(course)
        sections.append((section_name, course_dishes))

    if not sections:
        sections = [("Menu", ["Nessun menu disponibile"])]

    canvas_w, canvas_h = 2160, 2880

    # Generate patterned background (same pattern for the whole day)
    seed_key = f"{target_date}"
    base_bg = accent_color or POST_BG_COLOR
    bg_image = _generate_background_pattern(base_bg, canvas_w, canvas_h, seed_key)
    image = bg_image.convert("RGB")

    # ── Card UI constants (matching mensa-menu-ui.html) ──────────────
    card_w      = 1660
    card_radius = 80

    # Dynamically derive contrasting UI palette based purely on background hue
    palette = _derive_ui_colors(base_bg)
    C_CARD_BG     = palette["CARD"]
    C_TITLE       = palette["TITLE"]
    C_SECONDARY   = palette["SECONDARY"]
    C_TAB_BG      = palette["CAT"]
    C_TAB_ACTIVE  = palette["TAB_ACTIVE"]
    C_CAT_BG      = palette["CAT"]
    C_DISH_BG     = palette["DISH"]
    C_DISH_BORDER = palette["BORDER"]

    # ── Fonts (Nunito, matching mensa-menu-ui.html) ───────────────────
    title_font = _load_nunito(72, weight=800)   # h2: 18px × 4, weight 800
    tab_font   = _load_nunito(52, weight=800)   # tab: 13px × 4, weight 800
    cat_font   = _load_nunito(52, weight=800)   # cat: 13px × 4, weight 800
    dish_font  = _load_nunito(60, weight=700)   # dish: 15px × 4, weight 700
    date_font  = _load_nunito(44, weight=800)   # badge text
    fa_font    = _load_fa_solid(44)             # FontAwesome icons

    # ── Layout constants (≈ 4× scale from 420 px HTML) ──────────────
    pad_x             = 80       # header side padding: 20px × 4
    header_top        = 72       # header top padding: 18px × 4
    header_bottom     = 48       # header bottom padding: 12px × 4
    tab_margin_top    = 16       # mensa-tabs margin-top: 4px × 4
    tab_margin_bottom = 48       # mensa-tabs margin-bottom: 12px × 4
    tab_pad           = 24       # mensa-tabs padding: 6px × 4
    tab_btn_pad_v     = 32       # tab button padding: 8px × 4
    tab_radius        = 56       # mensa-tabs border-radius: 14px × 4
    tab_btn_radius    = 40       # tab button border-radius: 10px × 4
    list_radius       = 56       # menu-list border-radius: 14px × 4
    cat_pad_top       = 32       # cat padding-top: 8px × 4
    cat_pad_bottom    = 16       # cat padding-bottom: 4px × 4
    cat_pad_x         = 64       # cat padding-left: 16px × 4
    dish_pad_v        = 48       # dish padding vertical: 12px × 4
    dish_pad_x        = 64       # dish padding horizontal: 16px × 4
    dish_border_w     = 4        # border-bottom: 1px × 4
    bottom_pad        = 80       # body bottom padding: 20px × 4 (matches pad_x)

    # ── Derived metrics ──────────────────────────────────────────────
    dummy = Image.new("RGB", (1, 1))
    dd    = ImageDraw.Draw(dummy)

    title_h     = _line_height(dd, title_font)
    tab_text_h  = _line_height(dd, tab_font)
    cat_text_h  = _line_height(dd, cat_font)
    dish_line_h = _line_height(dd, dish_font)
    date_text_h = _line_height(dd, date_font)

    tab_btn_h       = tab_btn_pad_v * 2 + tab_text_h
    tab_container_h = tab_pad * 2 + tab_btn_h
    cat_row_h       = cat_pad_top + cat_text_h + cat_pad_bottom
    max_dish_text_w = card_w - pad_x * 2 - dish_pad_x * 2

    # ── 1. Measurement pass ──────────────────────────────────────────
    y_m = header_top + title_h + header_bottom
    y_m += tab_margin_top + tab_container_h + tab_margin_bottom

    for _, dishes in sections:
        y_m += cat_row_h
        for dish in dishes:
            dish = dish.strip().capitalize()
            wrapped = _wrap_text(dd, dish, dish_font, max_dish_text_w)
            y_m += dish_pad_v * 2 + max(1, len(wrapped)) * (dish_line_h + 6) - 6

    y_m += bottom_pad
    card_h = max(800, min(y_m, 2600))

    # ── 2. Draw the card ─────────────────────────────────────────────
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    cd   = ImageDraw.Draw(card)

    cd.rounded_rectangle(
        [(0, 0), (card_w - 1, card_h - 1)],
        radius=card_radius, fill=C_CARD_BG,
    )

    y = header_top

    # ── Header: title + date badge ───────────────────────────────────
    cd.text((pad_x, y + title_h // 2), canteen_name, fill=C_TITLE, font=title_font, anchor="lm")

    badge_pad_h, badge_pad_v_ = 36, 16
    date_w  = _text_width(dd, date_label, date_font)
    badge_w = date_w + badge_pad_h * 2
    badge_h = date_text_h + badge_pad_v_ * 2
    badge_x = card_w - pad_x - badge_w
    badge_y = y + (title_h - badge_h) // 2
    cd.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=badge_h // 2, fill=C_TAB_BG,
    )
    cd.text(
        (badge_x + badge_pad_h, badge_y + badge_h // 2),
        date_label, fill=C_SECONDARY, font=date_font, anchor="lm",
    )

    y += title_h + header_bottom

    # ── Tab bar (Pranzo / Cena) ──────────────────────────────────────
    tab_x       = pad_x
    tab_y       = y + tab_margin_top
    tab_total_w = card_w - pad_x * 2

    cd.rounded_rectangle(
        [(tab_x, tab_y), (tab_x + tab_total_w, tab_y + tab_container_h)],
        radius=tab_radius, fill=C_TAB_BG,
    )

    btn_area_w   = tab_total_w - tab_pad * 2
    single_btn_w = btn_area_w // 2          # each tab is exactly 50%, no gap
    btn_y        = tab_y + tab_pad

    for idx, tab_label in enumerate(MEAL_ORDER):
        bx     = tab_x + tab_pad + idx * single_btn_w
        active = tab_label == meal_name

        if active:
            cd.rounded_rectangle(
                [(bx, btn_y), (bx + single_btn_w, btn_y + tab_btn_h)],
                radius=tab_btn_radius, fill=C_TAB_ACTIVE,
            )

        tw = _text_width(dd, tab_label, tab_font)
        cd.text(
            (bx + single_btn_w // 2, btn_y + tab_btn_h // 2),
            tab_label,
            fill=C_TITLE if active else C_SECONDARY,
            font=tab_font,
            anchor="mm",
        )

    y = tab_y + tab_container_h + tab_margin_bottom

    # ── Menu list (rendered into a buffer, masked for rounded corners) ──
    list_x = pad_x
    list_w = card_w - pad_x * 2

    menu_h = 0
    for _, dishes in sections:
        menu_h += cat_row_h
        for dish in dishes:
            dish = dish.strip().capitalize()
            wrapped = _wrap_text(dd, dish, dish_font, max_dish_text_w)
            menu_h += dish_pad_v * 2 + max(1, len(wrapped)) * (dish_line_h + 6) - 6

    max_menu_h = card_h - y - bottom_pad
    menu_h = min(menu_h, max(max_menu_h, 200))

    menu_img = Image.new("RGBA", (list_w, menu_h), (0, 0, 0, 0))
    md = ImageDraw.Draw(menu_img)

    # base fill (dish background colour)
    md.rounded_rectangle(
        [(0, 0), (list_w - 1, menu_h - 1)],
        radius=list_radius, fill=C_DISH_BG,
    )

    total_dishes  = sum(len(d) for _, d in sections)
    dish_counter  = 0
    my            = 0
    overflow      = False

    for sec_idx, (section_name, dishes) in enumerate(sections):
        if my >= menu_h or overflow:
            break

        # ── category header ──
        cat_icons = {
            "primi": chr(58091),      # fa-bowl-rice
            "secondi": chr(63191),    # fa-drumstick-bite
            "contorni": chr(61548),   # fa-leaf
            "dolci": chr(127874),     # fa-cake-candles
        }
        
        md.rectangle([(0, my), (list_w - 1, my + cat_row_h - 1)], fill=C_CAT_BG)
        
        cat_lower_name = section_name.lower().strip()
        icon = cat_icons.get(cat_lower_name, "")
        
        cx = cat_pad_x
        if icon:
            md.text((cx, my + cat_row_h // 2), icon, fill=C_SECONDARY, font=fa_font, anchor="lm")
            cx += _text_width(dd, icon, fa_font) + 16  # spacing between icon and text
            
        md.text(
            (cx, my + cat_row_h // 2),
            section_name.upper(), fill=C_SECONDARY, font=cat_font, anchor="lm",
        )
        my += cat_row_h

        # ── dishes ──
        for dish in dishes:
            dish = dish.strip().capitalize()
            dish_counter += 1
            is_last = dish_counter == total_dishes

            wrapped   = _wrap_text(dd, dish, dish_font, max_dish_text_w)
            content_h = max(1, len(wrapped)) * (dish_line_h + 6) - 6
            row_h     = dish_pad_v * 2 + content_h

            if my + row_h > menu_h:
                remaining = menu_h - my
                if remaining > dish_pad_v + dish_line_h:
                    first = wrapped[0] if wrapped else dish
                    ell = f"{first} \u2026"
                    while (
                        _text_width(dd, ell, dish_font) > max_dish_text_w
                        and len(ell) > 3
                    ):
                        ell = ell[:-3] + "\u2026"
                    md.text((dish_pad_x, my + dish_pad_v), ell, fill=C_TITLE, font=dish_font)
                overflow = True
                break

            # Center text block vertically in the row
            block_h = max(1, len(wrapped)) * (dish_line_h + 6) - 6
            text_y = my + (row_h - block_h) // 2
            for line in wrapped:
                md.text((dish_pad_x, text_y + dish_line_h // 2), line, fill=C_TITLE, font=dish_font, anchor="lm")
                text_y += dish_line_h + 6

            if not is_last:
                border_y = my + row_h - dish_border_w // 2
                md.line(
                    [(0, border_y), (list_w, border_y)],
                    fill=C_DISH_BORDER, width=dish_border_w,
                )

            my += row_h

    # rounded-corner mask
    mask = Image.new("L", (list_w, menu_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (list_w - 1, menu_h - 1)],
        radius=list_radius, fill=255,
    )
    card.paste(menu_img, (list_x, y), mask)

    # ── Slight rotation (no shadow) ──────────────────────────────────
    angle = random.uniform(-4, 4)
    card_rot = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

    cx = (canvas_w - card_rot.width)  // 2
    cy = (canvas_h - card_rot.height) // 2
    image.paste(card_rot, (cx, cy), card_rot)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=95, dpi=(300, 300))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Genera immagini del menu giornaliero per ogni mensa."
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Data in formato YYYY-MM-DD. Se non fornita usa oggi.")
    parser.add_argument("--latest", action="store_true",
                        help="Se il menu di oggi non esiste, usa la data più recente disponibile.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Directory di output (default: assets/posts).")
    parser.add_argument("--canteen", type=str, default=None,
                        help="ID o nome di una mensa specifica da generare (es. martiri). Se non fornito, genera per tutte.")
    return parser.parse_args()


def main():
    args = parse_args()
    menu_data = load_json(MENU_PATH)
    canteens  = load_json(CANTEENS_PATH)

    if args.canteen:
        filtered = [c for c in canteens if slugify(c.get("name", "")) == slugify(args.canteen) or c.get("id") == args.canteen]
        if not filtered:
            print(f"Attenzione: nessuna mensa trovata per '{args.canteen}'.")
            return
        canteens = filtered

    target_date = pick_target_date(menu_data, args.date, args.latest)
    day_menu    = menu_data.get(target_date, {})
    date_tag    = target_date.replace("-", "")
    generated   = []

    for canteen in canteens:
        canteen_name = canteen.get("name", "Mensa")
        canteen_id   = canteen.get("id", slugify(canteen_name))
        
        # Color is consistent for the canteen on a specific day
        bg_seed = f"{date_tag}_{canteen_id}"
        base_color = _random_light_color(target_date, canteen_id)
        
        canteen_menu = collect_canteen_menu(day_menu, canteen_name)

        for meal in MEAL_ORDER:
            meal_menu = canteen_menu.get(meal, {})
            # Skip if there are no dishes for this meal
            if not any(meal_menu.values()):
                continue

            accent_color = base_color
            

            filename    = f"{date_tag}_{meal.lower()}_{canteen_id}.jpg"
            output_path = args.output_dir / filename

            build_and_save_gt(canteen_name, meal, meal_menu, target_date, accent_color, output_path)
            generated.append(output_path)

    print(f"Data usata: {target_date}")
    for path in generated:
        print(f"Generata: {path}")


if __name__ == "__main__":
    main()
