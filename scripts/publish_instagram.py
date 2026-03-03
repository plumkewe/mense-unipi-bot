import os
import json
from instagrapi import Client
from pathlib import Path
import datetime as dt

REPO_ROOT = Path(__file__).resolve().parent.parent
MENU_PATH = REPO_ROOT / "data" / "menu.json"

CANTEEN_NAME = "Mensa Martiri"
COURSE_ORDER = ["Primi Piatti", "Secondi Piatti", "Contorni"]
COURSE_LABELS = {
    "Primi Piatti": "Primi",
    "Secondi Piatti": "Secondi",
    "Contorni": "Contorni",
}
HASHTAGS = "#doveunipi #cibounipibot #mensa #universita #martiri"


def _get_dishes_for_canteen(meal_data: dict, canteen: str) -> dict[str, list[str]]:
    """Returns {course_label: [dish_name, ...]} filtered for the given canteen."""
    result = {}
    for course in COURSE_ORDER:
        dishes = meal_data.get(course, [])
        names = [
            d["name"].capitalize()
            for d in dishes
            if canteen in d.get("available_at", [])
        ]
        if names:
            result[COURSE_LABELS[course]] = names
    return result


def _format_meal_block(label: str, courses: dict[str, list[str]]) -> str:
    lines = [label]
    for course, dishes in courses.items():
        lines.append(f"{course}:")
        for dish in dishes:
            lines.append(f"  {dish}")
    return "\n".join(lines)


def build_caption(menu_data: dict, date_iso: str, has_pranzo: bool, has_cena: bool) -> str:
    oggi_ita = dt.date.fromisoformat(date_iso).strftime("%d.%m.%Y")
    day_data = menu_data.get(date_iso, {})

    pranzo_courses = _get_dishes_for_canteen(day_data.get("Pranzo", {}), CANTEEN_NAME) if has_pranzo else {}
    cena_courses = _get_dishes_for_canteen(day_data.get("Cena", {}), CANTEEN_NAME) if has_cena else {}

    lines = [f"Mensa Martiri - {oggi_ita}", ""]

    if has_cena and has_pranzo:
        lines.append("Fai swipe per vedere il menu della cena.")
    elif has_pranzo and not has_cena:
        lines.append("Oggi solo pranzo disponibile.")
    elif has_cena and not has_pranzo:
        lines.append("Oggi solo cena disponibile.")

    lines.append("")

    if pranzo_courses:
        lines.append(_format_meal_block("A pranzo:", pranzo_courses))
        lines.append("")

    if cena_courses:
        lines.append(_format_meal_block("A cena:", cena_courses))
        lines.append("")

    lines.append("Buon appetito!")
    lines.append("")
    lines.append(HASHTAGS)

    return "\n".join(lines)


def main():
    # Credentials dal GitHub Secrets
    USERNAME = os.environ.get("IG_USERNAME")
    PASSWORD = os.environ.get("IG_PASSWORD")
    SESSION_STR = os.environ.get("IG_SESSION")

    if not USERNAME or not PASSWORD:
        print("Errore: credenziali IG_USERNAME o IG_PASSWORD non impostate.")
        return

    # Inizializza e Accedi
    cl = Client()
    try:
        if SESSION_STR:
            import json
            cl.set_settings(json.loads(SESSION_STR))
            print("Trovata chiave di sessione, ignorerò il blocco IP...")
            
        cl.login(USERNAME, PASSWORD)
        print("Login ad Instagram effettuato con successo!")
    except Exception as e:
        print(f"Errore durante il login: {e}")
        return

    # Cartella target
    posts_dir = REPO_ROOT / "assets" / "posts"
    if not posts_dir.exists():
        print(f"La cartella {posts_dir} non esiste. Non c'è nulla da pubblicare.")
        return

    oggi_iso = dt.date.today().isoformat()
    oggi_tag = dt.date.today().strftime("%Y%m%d")
    oggi_ita = dt.date.today().strftime("%d.%m.%Y")

    # Prendi SOLO le immagini di OGGI per evitare ri-pubblicazioni di ieri
    pranzo_files = sorted(list(posts_dir.glob(f"{oggi_tag}_pranzo_martiri.jpg")))
    cena_files = sorted(list(posts_dir.glob(f"{oggi_tag}_cena_martiri.jpg")))

    album_paths = []

    if pranzo_files:
        album_paths.append(pranzo_files[-1])
    else:
        print("Nessun menu Pranzo trovato per oggi.")

    if cena_files:
        album_paths.append(cena_files[-1])
    else:
        print("Nessun menu Cena trovato per oggi.")

    if not album_paths:
        print("Nessuna immagine di oggi da pubblicare. Potrebbe essere chiusa o già pubblicata/rinominata.")
        return

    # Evitiamo di ripubblicare se esiste già un segnale che oggi è stato pubblicato (es. file di lock)
    lock_file = posts_dir / f"{oggi_tag}_published.lock"

    # Se l'evento è manuale (workflow_dispatch), ignora il lock
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    if lock_file.exists():
        if is_manual:
            print(f"Lock file trovato per {oggi_ita}, ma ignorato perché eseguito manualmente.")
        else:
            print(f"I menu di oggi ({oggi_ita}) sono GIA' stati pubblicati! (Trovato file lock)")
            return

    # Costruisci didascalia dinamica dal menu
    menu_data = {}
    if MENU_PATH.exists():
        with MENU_PATH.open("r", encoding="utf-8") as f:
            menu_data = json.load(f)

    didascalia = build_caption(
        menu_data,
        date_iso=oggi_iso,
        has_pranzo=bool(pranzo_files),
        has_cena=bool(cena_files),
    )
    print("Didascalia generata:\n")
    print(didascalia)
    print()

    if len(album_paths) == 1:
        # Pubblica singola foto
        print(f"Pubblico singola foto: {album_paths[0]}")
        cl.photo_upload(album_paths[0], didascalia)
    else:
        # Pubblica album (Pranzo -> Cena)
        print(f"Pubblico Carousel (Album) con foto: {[p.name for p in album_paths]}")
        cl.album_upload(album_paths, didascalia)
        
    print("Pubblicazione completata!")

    # Crea un file di lock per impedire post duplicati 
    # se la GitHub action dovesse essere lanciata una seconda volta nello stesso giorno
    with open(lock_file, "w") as f:
        f.write("Pubblicato con successo.")
        
if __name__ == "__main__":
    main()
