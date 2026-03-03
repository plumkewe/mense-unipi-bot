import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import matplotlib.colors as mcolors
from PIL import Image
from great_tables import GT, style, loc


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

CANTEEN_COLORS = {
    "martiri": "#FCE7F3",
    "betti": "#DBEAFE",
    "cammeo": "#DCFCE7",
}


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


def blend_colors(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    a_r, a_g, a_b = mcolors.to_rgb(color_a)
    b_r, b_g, b_b = mcolors.to_rgb(color_b)
    mixed = (
        (1 - ratio) * a_r + ratio * b_r,
        (1 - ratio) * a_g + ratio * b_g,
        (1 - ratio) * a_b + ratio * b_b,
    )
    return mcolors.to_hex(mixed)


def _strip_piatti(course: str) -> str:
    """Remove the word 'Piatti' (and surrounding spaces) from a course label."""
    return course.replace(" Piatti", "").replace("Piatti ", "").replace("Piatti", "").strip()


def _format_date_label(date_iso: str) -> str:
    try:
        return dt.date.fromisoformat(date_iso).strftime("%d.%m.%Y")
    except ValueError:
        return date_iso


def _enforce_output_size(output_path: Path, bg_color: str, width: int = 1080, height: int = 1440) -> None:
    with Image.open(output_path) as img:
        canvas = Image.new("RGBA", (width, height), bg_color)
        
        target_w = width
        scale = target_w / img.width
        new_h = int(img.height * scale)
        img_resized = img.resize((target_w, new_h), Image.Resampling.LANCZOS)
        
        if new_h > height:
            scale = height / img.height
            new_w = int(img.width * scale)
            img_resized = img.resize((new_w, height), Image.Resampling.LANCZOS)
            x_offset = (width - new_w) // 2
            canvas.paste(img_resized, (x_offset, 0))
        else:
            canvas.paste(img_resized, (0, 0))
            
        # Salva con metadati DPI alti e alla risoluzione richiesta
        canvas.convert("RGB").save(output_path, dpi=(300, 300))


def build_and_save_gt(
    canteen_name: str,
    meal_name: str,
    meal_menu: dict,
    target_date: str,
    accent_color: str,
    output_path: Path,
) -> None:
    # Removed meal name from date_label as requested
    date_label = _format_date_label(target_date)

    # Build flat list of rows
    rows: list[dict] = []
    for course, dishes in meal_menu.items():
        group_label = _strip_piatti(course).upper()
        for dish in dishes:
            rows.append({"gruppo": group_label, "piatto": dish})
    if not rows:
        rows = [{"gruppo": "MENU", "piatto": "Nessun menu disponibile"}]

    df = pd.DataFrame(rows)

    # Restoring strong colors but keeping true menu style
    accent_dark = blend_colors(accent_color, "#000000", 0.70)
    section_bg = blend_colors(accent_color, "#FFFFFF", 0.60) 
    page_bg = "#FFFFFF"
    text_color = "#1F2937"

    display_name = canteen_name.upper().replace("MENSA ", "").replace(" MENSA", "").strip()

    gt = (
        GT(df, groupname_col="gruppo")
        .tab_header(title=display_name, subtitle=date_label)
        .cols_label(piatto="")
        .cols_align(align="center", columns="piatto")
        .tab_options(
            table_font_names=["Inter", "system-ui", "Helvetica Neue", "sans-serif"],
            table_width="100%",
            table_background_color=page_bg,
            heading_background_color=accent_color,
            heading_title_font_size="60px",
            heading_title_font_weight="900",
            heading_subtitle_font_size="24px",
            heading_padding="50px",
            heading_padding_horizontal="30px",
            row_group_background_color=section_bg,
            row_group_font_weight="900",
            row_group_font_size="24px",
            row_group_padding="18px",
            row_group_border_top_style="solid",
            row_group_border_top_color="#FFFFFF",
            row_group_border_top_width="3px",
            row_group_border_bottom_style="solid",
            row_group_border_bottom_color="#FFFFFF",
            row_group_border_bottom_width="3px",
            data_row_padding="16px",
            column_labels_hidden=True,
            table_border_top_style="hidden",
            table_border_bottom_style="hidden",
            stub_border_style="none",
        )
        .tab_style(
            style=style.text(size="22px", color=text_color, weight="500"),
            locations=loc.body()
        )
        .tab_style(
            style=style.borders(sides="all", style="none"),
            locations=loc.body(),
        )
        .tab_style(
            style=style.text(color=accent_dark, size="60px", weight="900", align="center"),
            locations=loc.title(),
        )
        .tab_style(
            style=style.text(color=accent_dark, size="24px", weight="600", align="center", whitespace="pre-wrap"),
            locations=loc.subtitle(),
        )
        .tab_style(
            style=[
                style.text(color=accent_dark, size="24px", weight="900", align="center"),
            ],
            locations=loc.row_groups(),
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Aumentiamo lo scale factor per fare il render super nitido originale
    gt.save(str(output_path), scale=4.0, window_size=(1080, 1440))
    
    # Esportiamo al doppio della risoluzione Instagram (2160x2880) mantenendo i 3:4 per super-risoluzione/DPI alti
    _enforce_output_size(output_path, bg_color=page_bg, width=2160, height=2880)


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
        base_color   = CANTEEN_COLORS.get(canteen_id, "#E5E7EB")
        canteen_menu = collect_canteen_menu(day_menu, canteen_name)

        for meal in MEAL_ORDER:
            meal_menu = canteen_menu.get(meal, {})
            # Skip if there are no dishes for this meal
            if not any(meal_menu.values()):
                continue

            # Darken the background colour for dinner menus
            accent_color = base_color
            if meal == "Cena":
                accent_color = blend_colors(base_color, "#000000", 0.20)

            filename    = f"{date_tag}_{meal.lower()}_{canteen_id}.png"
            output_path = args.output_dir / filename

            build_and_save_gt(canteen_name, meal, meal_menu, target_date, accent_color, output_path)
            generated.append(output_path)

    print(f"Data usata: {target_date}")
    for path in generated:
        print(f"Generata: {path}")


if __name__ == "__main__":
    main()
