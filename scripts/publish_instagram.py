import os
import json
import time
import requests
from pathlib import Path
import datetime as dt
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

REPO_ROOT = Path(__file__).resolve().parent.parent
MENU_PATH = REPO_ROOT / "data" / "menu.json"

GRAPH_API_VERSION = "v22.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Repo GitHub pubblica — le immagini vengono servite tramite raw.githubusercontent.com
GITHUB_REPO = "plumkewe/mense-unipi-bot"
GITHUB_BRANCH = "main"

CANTEEN_NAME = "Mensa Martiri"
COURSE_ORDER = ["Primi Piatti", "Secondi Piatti", "Contorni"]
COURSE_LABELS = {
    "Primi Piatti": "Primi",
    "Secondi Piatti": "Secondi",
    "Contorni": "Contorni",
}
HASHTAGS = "#doveunipi #cibounipibot #mensa #universita #martiri"


# ---------------------------------------------------------------------------
# Caption builder (invariato)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# URL pubblico raw di GitHub
# La Graph API di Instagram richiede URL pubblici accessibili da internet.
# Le immagini sono già committate nella repo pubblica, quindi usiamo
# raw.githubusercontent.com direttamente — nessun servizio esterno.
# ---------------------------------------------------------------------------

def github_raw_url(relative_path: str) -> str:
    """Restituisce l'URL raw di GitHub per un file nella repo."""
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{relative_path}"


# ---------------------------------------------------------------------------
# Instagram Graph API helpers
# ---------------------------------------------------------------------------

def _ig_post(endpoint: str, access_token: str, **params) -> dict:
    """Esegue una POST alla Graph API e restituisce il JSON della risposta."""
    params["access_token"] = access_token
    resp = requests.post(f"{GRAPH_API_BASE}/{endpoint}", data=params, timeout=60)
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"Graph API error: {result['error']}")
    return result


def create_image_container(ig_user_id: str, access_token: str, image_url: str,
                            caption: str = None, is_carousel_item: bool = False) -> str:
    """Crea un media container per un'immagine. Restituisce l'ID del container."""
    params = {
        "image_url": image_url,
    }
    if caption:
        params["caption"] = caption
    if is_carousel_item:
        params["is_carousel_item"] = "true"

    result = _ig_post(f"{ig_user_id}/media", access_token, **params)
    container_id = result["id"]
    print(f"  Container immagine creato: {container_id}")
    return container_id


def create_carousel_container(ig_user_id: str, access_token: str,
                               children_ids: list[str], caption: str) -> str:
    """Crea un media container di tipo Carousel. Restituisce l'ID del container."""
    result = _ig_post(
        f"{ig_user_id}/media",
        access_token,
        media_type="CAROUSEL",
        children=",".join(children_ids),
        caption=caption,
    )
    container_id = result["id"]
    print(f"  Container carousel creato: {container_id}")
    return container_id


def wait_for_container(ig_user_id: str, access_token: str, container_id: str,
                        max_wait: int = 120) -> None:
    """Attende che il container sia nello stato FINISHED prima di pubblicarlo."""
    for _ in range(max_wait // 5):
        resp = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code", "")
        print(f"  Stato container {container_id}: {status}")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container {container_id} in stato ERROR.")
        time.sleep(5)
    raise TimeoutError(f"Container {container_id} non pronto dopo {max_wait}s.")


def publish_container(ig_user_id: str, access_token: str, container_id: str,
                      max_retries: int = 3, retry_delay: int = 10) -> str:
    """Pubblica il container con retry per errori 'media not ready' (9007)."""
    for attempt in range(1, max_retries + 1):
        try:
            result = _ig_post(
                f"{ig_user_id}/media_publish",
                access_token,
                creation_id=container_id,
            )
            media_id = result["id"]
            print(f"  Media pubblicato con ID: {media_id}")
            return media_id
        except RuntimeError as e:
            if "9007" in str(e) and attempt < max_retries:
                print(f"  Media non ancora pronto (tentativo {attempt}/{max_retries}). Riprovo tra {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Token ufficiale Instagram Graph API (da GitHub Secrets)
    ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
    IG_USER_ID = os.environ.get("IG_USER_ID")

    if not ACCESS_TOKEN:
        print("Errore: IG_ACCESS_TOKEN non impostato.")
        return
    if not IG_USER_ID:
        print("Errore: IG_USER_ID non impostato.")
        return

    # Cartella target
    posts_dir = REPO_ROOT / "assets" / "posts"
    if not posts_dir.exists():
        print(f"La cartella {posts_dir} non esiste. Non c'è nulla da pubblicare.")
        return

    oggi_iso = dt.date.today().isoformat()
    oggi_tag = dt.date.today().strftime("%Y%m%d")
    oggi_ita = dt.date.today().strftime("%d.%m.%Y")

    # Check for holidays before publishing
    feste_path = REPO_ROOT / "data" / "feste.json"
    if feste_path.exists():
        try:
            with open(feste_path, "r", encoding="utf-8") as f:
                feste_data = json.load(f)
            martiri_feste = feste_data.get("martiri", [])
            date_obj = dt.date.today()
            is_closed = False
            for period in martiri_feste:
                start_d = dt.datetime.strptime(period["start_date"], "%Y-%m-%d").date()
                end_d = dt.datetime.strptime(period["end_date"], "%Y-%m-%d").date()
                if start_d <= date_obj <= end_d and period.get("status") == "closed":
                    is_closed = True
                    break
            if is_closed:
                print(f"Oggi ({oggi_ita}) la mensa Martiri è in vacanza. Salto la pubblicazione.")
                return
        except Exception as e:
            print(f"Errore durante il controllo festività: {e}")

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

    # 1) Costruisci URL raw di GitHub per ogni immagine
    # Le immagini sono già committate nella repo pubblica su GitHub.
    print("Costruzione URL raw GitHub per le immagini...")
    public_urls = []
    for path in album_paths:
        relative = f"assets/posts/{path.name}"
        url = github_raw_url(relative)
        print(f"  {path.name} → {url}")
        public_urls.append(url)

    print()

    # 2) Crea i container e pubblica tramite Graph API
    if not is_manual and ZoneInfo is not None:
        tz_rome = ZoneInfo("Europe/Rome")
        now_rome = dt.datetime.now(tz_rome)
        target_time = now_rome.replace(hour=9, minute=21, second=0, microsecond=0)
        
        # Se siamo tra le 09:20 e le 09:21, aspetta il momento esatto
        if now_rome < target_time and now_rome.hour == 9 and now_rome.minute == 20:
            wait_seconds = (target_time - now_rome).total_seconds()
            print(f"Action avviata alle {now_rome.strftime('%H:%M:%S')}. Attendo {wait_seconds:.1f} secondi per pubblicare esattamente alle 09:21:00...")
            time.sleep(wait_seconds)
            print("Ora esatta raggiunta. Avvio pubblicazione!")

    try:
        if len(public_urls) == 1:
            # Singola foto
            print(f"Creazione container per singola foto...")
            container_id = create_image_container(
                IG_USER_ID, ACCESS_TOKEN, public_urls[0], caption=didascalia
            )
            wait_for_container(IG_USER_ID, ACCESS_TOKEN, container_id)
            publish_container(IG_USER_ID, ACCESS_TOKEN, container_id)

        else:
            # Carousel (Pranzo → Cena)
            print("Creazione container per ogni immagine del carousel...")
            children_ids = []
            for url in public_urls:
                cid = create_image_container(
                    IG_USER_ID, ACCESS_TOKEN, url, is_carousel_item=True
                )
                wait_for_container(IG_USER_ID, ACCESS_TOKEN, cid)
                children_ids.append(cid)

            print("Creazione container carousel...")
            carousel_id = create_carousel_container(
                IG_USER_ID, ACCESS_TOKEN, children_ids, didascalia
            )
            wait_for_container(IG_USER_ID, ACCESS_TOKEN, carousel_id)
            publish_container(IG_USER_ID, ACCESS_TOKEN, carousel_id)

    except Exception as e:
        print(f"Errore durante la pubblicazione: {e}")
        return

    print("Pubblicazione completata!")

    # Crea un file di lock per impedire post duplicati
    # se la GitHub action dovesse essere lanciata una seconda volta nello stesso giorno
    with open(lock_file, "w") as f:
        f.write("Pubblicato con successo.")


if __name__ == "__main__":
    main()
