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
CARD_BG_COLOR = "#FFFFFF"
TEXT_COLOR = "#374151"
TITLE_COLOR = "#111827"
TOP_BAR_COLOR = "#E5E7EB"
BORDER_COLOR = "#F3F4F6"
DIVIDER_COLOR = "#D1D5DB"


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

    saturation = rng.uniform(0.5, 0.9)
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
    return f"#{red:02X}{green:02X}{blue:02X}"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    _fonts_dir = REPO_ROOT / "assets" / "fonts"
    if bold:
        font_path = _fonts_dir / "Poppins-Bold.ttf"
    else:
        font_path = _fonts_dir / "Poppins-Regular.ttf"
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
        "hexagons",
        "zigzag",
        "concentric_circles",
        "plus_grid",
        "waves",
        "triangles",
        "squares",
        "hollow_dots",
        "x_shapes",
        "vertical_stripes",
        "horizontal_stripes"
    ])

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if pattern_type == "dot_grid":
        # Offset polka-dot grid — perfectly aligned rows and columns, centered
        spacing = rng.choice([140, 180, 220])
        radius  = spacing // 4
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for row, y in enumerate(range(oy, height + spacing, spacing)):
            x_offset = (spacing // 2) if (row % 2) else 0
            for x in range(-spacing, width + spacing, spacing):
                cx = x + x_offset + ox
                draw.ellipse((cx - radius, y - radius, cx + radius, y + radius), fill=pc)

    elif pattern_type == "diagonal_stripes":
        # Crisp parallel diagonal stripes at 45°
        spacing   = rng.choice([120, 160, 200])
        thickness = rng.choice([20, 30, 40])
        size      = (width + height) * 2
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        for i in range(-size, size, spacing):
            tmp_draw.line([(i, 0), (i + size, size)], fill=pc, width=thickness)
        rotated = tmp.rotate(0)   # already 45° by construction
        layer.paste(rotated, (-(size - width) // 2, -(size - height) // 2), rotated)

    elif pattern_type == "crosshatch":
        # Regular grid of thin crossing lines, centered
        spacing = rng.choice([140, 180, 240])
        thickness = rng.choice([12, 16, 20])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for x in range(ox, width + spacing, spacing):
            draw.line([(x, 0), (x, height)], fill=pc, width=thickness)
        for y in range(oy, height + spacing, spacing):
            draw.line([(0, y), (width, y)], fill=pc, width=thickness)

    elif pattern_type == "diamond_grid":
        # 45°-rotated square grid (diamond lattice)
        spacing = rng.choice([160, 200, 240])
        thickness = rng.choice([12, 16, 20])
        size = (width + height) * 2
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        for i in range(-size, size, spacing):
            tmp_draw.line([(i, 0), (i, size)], fill=pc, width=thickness)
            tmp_draw.line([(0, i), (size, i)], fill=pc, width=thickness)
        rotated = tmp.rotate(45, center=(size // 2, size // 2))
        layer.paste(rotated, (-(size - width) // 2, -(size - height) // 2), rotated)

    elif pattern_type == "hexagons":
        # Regular hexagonal tiling
        size = rng.choice([100, 140, 180])
        thickness = rng.choice([10, 14, 18])
        hex_w = size * 2
        hex_h = int(size * 1.732)  # sqrt(3) * size
        import math
        for row in range(-1, height // hex_h + 2):
            for col in range(-1, width // (hex_w - size // 2) + 2):
                cx = col * (hex_w - size // 2) + (hex_w // 2 if row % 2 else 0)
                cy = row * hex_h + hex_h // 2
                pts = [
                    (cx + int(size * math.cos(math.radians(60 * i - 30))),
                     cy + int(size * math.sin(math.radians(60 * i - 30))))
                    for i in range(6)
                ]
                draw.polygon(pts, outline=pc, width=thickness)

    elif pattern_type == "zigzag":
        # Horizontal chevron / zigzag bands, centered
        spacing = rng.choice([140, 180, 240])
        amplitude = spacing // 2
        thickness = rng.choice([14, 18, 22])
        step = 60
        ox = (width % (step * 2)) // 2
        oy = (height % spacing) // 2
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
        spacing = rng.choice([140, 180, 240])
        thickness = rng.choice([14, 18, 22])
        for r in range(spacing, max_r, spacing):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=pc, width=thickness)

    elif pattern_type == "plus_grid":
        # Evenly spaced + signs on a regular grid, centered
        spacing  = rng.choice([160, 200, 240])
        arm_len  = spacing // 3
        thickness = rng.choice([14, 18, 24])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for y in range(oy, height + spacing, spacing):
            for x in range(ox, width + spacing, spacing):
                draw.line([(x - arm_len, y), (x + arm_len, y)], fill=pc, width=thickness)
                draw.line([(x, y - arm_len), (x, y + arm_len)], fill=pc, width=thickness)

    elif pattern_type == "waves":
        import math
        spacing = rng.choice([140, 180, 220])
        amplitude = spacing // 3
        thickness = rng.choice([14, 18, 22])
        oy = (height % spacing) // 2
        # Center the sine wave horizontally: shift phase so wave is symmetric around center
        cx = width / 2.0
        for y_base in range(oy, height + spacing, spacing):
            pts = []
            for x in range(-40, width + 80, 40):
                y = y_base + int(math.sin((x - cx) / 100.0) * amplitude)
                pts.append((x, y))
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=pc, width=thickness)

    elif pattern_type == "triangles":
        spacing = rng.choice([160, 200, 240])
        thickness = rng.choice([10, 14, 18])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for row, y in enumerate(range(oy, height + spacing, spacing)):
            for col, x in enumerate(range(ox - spacing, width + spacing, spacing)):
                x_off = x + (spacing // 2 if row % 2 == 0 else 0)
                pts = [
                    (x_off, y),
                    (x_off - spacing//2, y + spacing),
                    (x_off + spacing//2, y + spacing)
                ]
                draw.polygon(pts, outline=pc, width=thickness)

    elif pattern_type == "squares":
        spacing = rng.choice([140, 180, 220])
        size = spacing // 2
        thickness = rng.choice([14, 18, 24])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for y in range(oy, height + spacing, spacing):
            for x in range(ox, width + spacing, spacing):
                draw.rectangle((x - size//2, y - size//2, x + size//2, y + size//2), outline=pc, width=thickness)

    elif pattern_type == "hollow_dots":
        spacing = rng.choice([140, 180, 220])
        radius = spacing // 3
        thickness = rng.choice([14, 18, 24])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for row, y in enumerate(range(oy, height + spacing, spacing)):
            x_offset = (spacing // 2) if (row % 2) else 0
            for x in range(-spacing, width + spacing, spacing):
                cx = x + x_offset + ox
                draw.ellipse((cx - radius, y - radius, cx + radius, y + radius), outline=pc, width=thickness)

    elif pattern_type == "x_shapes":
        spacing = rng.choice([160, 200, 240])
        arm_len = spacing // 3
        thickness = rng.choice([14, 18, 24])
        ox = (width % spacing) // 2
        oy = (height % spacing) // 2
        for y in range(oy, height + spacing, spacing):
            for x in range(ox, width + spacing, spacing):
                draw.line([(x - arm_len, y - arm_len), (x + arm_len, y + arm_len)], fill=pc, width=thickness)
                draw.line([(x - arm_len, y + arm_len), (x + arm_len, y - arm_len)], fill=pc, width=thickness)

    elif pattern_type == "vertical_stripes":
        spacing = rng.choice([120, 160, 200])
        # matching diagonal_stripes logic which is spacing // 4
        thickness = spacing // 4
        ox = (width % spacing) // 2
        for x in range(ox, width + spacing, spacing):
            draw.line([(x, 0), (x, height)], fill=pc, width=thickness)

    elif pattern_type == "horizontal_stripes":
        spacing = rng.choice([120, 160, 200])
        # matching diagonal_stripes logic which is spacing // 4
        thickness = spacing // 4
        oy = (height % spacing) // 2
        for y in range(oy, height + spacing, spacing):
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
        section_name = _strip_piatti(course).upper()
        sections.append((section_name, course_dishes))

    if not sections:
        sections = [("MENU", ["Nessun menu disponibile"])]

    canvas_w, canvas_h = 2160, 2880
    
    # Generate Pattern Background
    # Same pattern for the whole day (based on date)
    # The geometric pattern will be identical across all canteens and meals for this date
    seed_key = f"{target_date}"
    base_bg = accent_color or POST_BG_COLOR
    
    # Create the background with pattern
    bg_image = _generate_background_pattern(base_bg, canvas_w, canvas_h, seed_key)
    image = bg_image.convert("RGB")

    sheet_w = 1660
    
    # 1. First pass: Measure content height to determine sheet_h
    # We need a dummy draw object for text measurements
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    title_font = _load_font(84, bold=True)
    body_font = _load_font(66, bold=False)
    section_font = _load_font(52, bold=True)
    footer_font = _load_font(48, bold=True)

    display_name = canteen_name.upper().replace("MENSA ", "").replace(" MENSA", "").strip()
    title_text = display_name
    
    inner_pad_x = 80
    inner_left = inner_pad_x
    inner_right = sheet_w - inner_pad_x
    max_text_width = inner_right - inner_left

    # Measure Title
    current_y = 120
    title_lines = _wrap_text(dummy_draw, title_text, title_font, max_text_width)
    current_y += len(title_lines) * (_line_height(dummy_draw, title_font) + 8)
    current_y += 20 # Gap after title

    # Measure Body Blocks
    body_blocks: list[tuple[str, str]] = []
    for section_name, section_dishes in sections:
        body_blocks.append(("section", section_name))
        for dish in section_dishes:
            body_blocks.append(("dish", dish))
        body_blocks.append(("gap", ""))

    if body_blocks and body_blocks[-1][0] == "gap":
        body_blocks.pop()

    section_line_height = _line_height(dummy_draw, section_font)
    body_line_height = _line_height(dummy_draw, body_font)
    
    for block_type, value in body_blocks:
        if block_type == "section":
            current_y += section_line_height + 18
        elif block_type == "dish":
            wrapped_lines = _wrap_text(dummy_draw, value, body_font, max_text_width)
            current_y += len(wrapped_lines) * (body_line_height + 10) + 10
        else:
             current_y += 22

    # Measure Footer
    footer_text = f"{date_label}"
    footer_height = _line_height(dummy_draw, footer_font)
    
    # Add footer padding: gap before footer (60) + footer height + bottom padding (60)
    total_required_height = current_y + 140 + footer_height
    
    # Clamp height
    min_sheet_h = 800
    max_sheet_h = 2600
    sheet_h = max(min_sheet_h, min(total_required_height, max_sheet_h))

    # 2. Second pass: Draw everything on the sized sheet
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    sheet_draw = ImageDraw.Draw(sheet)

    radius = 36
    sheet_draw.rounded_rectangle(
        [(0, 0), (sheet_w - 1, sheet_h - 1)],
        radius=radius,
        fill=CARD_BG_COLOR,
    )
    
    top_bar_height = 80
    sheet_draw.rounded_rectangle(
        [(0, 0), (sheet_w - 1, top_bar_height)],
        radius=radius,
        fill=TOP_BAR_COLOR,
    )
    sheet_draw.rectangle([(0, radius), (sheet_w - 1, top_bar_height)], fill=TOP_BAR_COLOR)
    
    # Draw outline last to ensure perfect rounded corners
    sheet_draw.rounded_rectangle(
        [(0, 0), (sheet_w - 1, sheet_h - 1)],
        radius=radius,
        outline=BORDER_COLOR,
        width=4,
    )

    y = 120
    for line in title_lines:
        sheet_draw.text((inner_left, y), line, fill=TITLE_COLOR, font=title_font)
        y += _line_height(sheet_draw, title_font) + 8

    y += 20
    
    max_body_bottom = sheet_h - 140 - footer_height
    line_height = _line_height(sheet_draw, body_font)

    for block_type, value in body_blocks:
        if block_type == "section":
            next_y = y + section_line_height
            if next_y > max_body_bottom:
                break
            
            # Restore section divider line
            sheet_draw.line(
                [(inner_left, y + section_line_height // 2), (inner_right, y + section_line_height // 2)],
                fill=DIVIDER_COLOR,
                width=3,
            )

            section_text_w = _text_width(sheet_draw, value, section_font)
            label_pad_x = 18
            # Align section title exactly with dishes (inner_left)
            label_x = inner_left
            label_y = y
            
            # Mask the line behind the text
            sheet_draw.rectangle(
                [
                    (label_x - 4, label_y - 4),
                    (label_x + section_text_w + label_pad_x, label_y + section_line_height + 2),
                ],
                fill=CARD_BG_COLOR,
            )
            sheet_draw.text((label_x, label_y), value, fill=TITLE_COLOR, font=section_font)
            y += section_line_height + 18
        elif block_type == "dish":
            wrapped_lines = _wrap_text(sheet_draw, value, body_font, max_text_width)
            required_h = len(wrapped_lines) * (line_height + 10)
            if y + required_h > max_body_bottom:
                ellipsis = "..."
                last_line = wrapped_lines[0] if wrapped_lines else ""
                while last_line and _text_width(sheet_draw, f"{last_line} {ellipsis}", body_font) > max_text_width:
                    last_line = last_line[:-1]
                sheet_draw.text((inner_left, y), f"{last_line} {ellipsis}".strip(), fill=TEXT_COLOR, font=body_font)
                break

            for line in wrapped_lines:
                sheet_draw.text((inner_left, y), line, fill=TEXT_COLOR, font=body_font)
                y += line_height + 10
            y += 10
        else:
            y += 22

    # Draw footer
    footer_w = _text_width(sheet_draw, footer_text, footer_font)
    footer_x = (sheet_w - footer_w) // 2
    footer_y = sheet_h - 60 - footer_height
    sheet_draw.text((footer_x, footer_y), footer_text, fill="#6B7280", font=footer_font)

    shadow = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [(0, 0), (sheet_w - 1, sheet_h - 1)],
        radius=radius,
        fill=(0, 0, 0, 38),
    )

    angle = random.uniform(-4, 4)
    shadow_rot = shadow.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    sheet_rot = sheet.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)

    x = (canvas_w - sheet_rot.width) // 2
    y = (canvas_h - sheet_rot.height) // 2
    image.paste(shadow_rot, (x + 18, y + 24), shadow_rot)
    image.paste(sheet_rot, (x, y), sheet_rot)

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
            if meal == "Cena":
                accent_color = _darken_color(base_color, factor=0.78)

            filename    = f"{date_tag}_{meal.lower()}_{canteen_id}.jpg"
            output_path = args.output_dir / filename

            build_and_save_gt(canteen_name, meal, meal_menu, target_date, accent_color, output_path)
            generated.append(output_path)

    print(f"Data usata: {target_date}")
    for path in generated:
        print(f"Generata: {path}")


if __name__ == "__main__":
    main()
