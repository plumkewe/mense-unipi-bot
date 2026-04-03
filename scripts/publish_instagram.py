import os
import sys
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
# Retry config
# ---------------------------------------------------------------------------
# Retry per singole chiamate API (create container, publish, ecc.)
API_MAX_RETRIES = 5
API_RETRY_BASE_DELAY = 15  # seconds

# Retry globale per l'intero flusso di pubblicazione
GLOBAL_MAX_RETRIES = 5
GLOBAL_RETRY_DELAYS = [30, 60, 120, 240, 480]  # backoff esponenziale ~15 min totali

# Orario di pubblicazione
PUBLISH_HOUR = 9
PUBLISH_MINUTE = 21


# ---------------------------------------------------------------------------
# Caption builder
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
# ---------------------------------------------------------------------------

def github_raw_url(relative_path: str) -> str:
    """Restituisce l'URL raw di GitHub per un file nella repo."""
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{relative_path}"


# ---------------------------------------------------------------------------
# Instagram Graph API helpers (con retry robusto)
# ---------------------------------------------------------------------------

def _ig_post(endpoint: str, access_token: str, **params) -> dict:
    """Esegue una POST alla Graph API con retry automatico su errori."""
    params["access_token"] = access_token

    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{GRAPH_API_BASE}/{endpoint}",
                data=params,
                timeout=60,
            )
            result = resp.json()

            if "error" in result:
                error_msg = result["error"].get("message", str(result["error"]))
                error_code = result["error"].get("code", "")

                # Non riprovare per errori di autenticazione/permessi
                if error_code in (190, 10, 100):
                    raise RuntimeError(f"Graph API error (non recuperabile, code {error_code}): {error_msg}")

                if attempt < API_MAX_RETRIES:
                    delay = API_RETRY_BASE_DELAY * attempt
                    print(f"  ⚠ Graph API error (tentativo {attempt}/{API_MAX_RETRIES}, code {error_code}): {error_msg}")
                    print(f"    Riprovo tra {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    raise RuntimeError(f"Graph API error dopo {API_MAX_RETRIES} tentativi: {error_msg}")

            return result

        except requests.RequestException as e:
            if attempt < API_MAX_RETRIES:
                delay = API_RETRY_BASE_DELAY * attempt
                print(f"  ⚠ Errore di rete (tentativo {attempt}/{API_MAX_RETRIES}): {e}")
                print(f"    Riprovo tra {delay}s...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Errore di rete dopo {API_MAX_RETRIES} tentativi: {e}")

    # Non dovrebbe mai arrivarci, ma per sicurezza
    raise RuntimeError("Tentativi esauriti in _ig_post")


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
    print(f"  ✓ Container immagine creato: {container_id}")
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
    print(f"  ✓ Container carousel creato: {container_id}")
    return container_id


def wait_for_container(ig_user_id: str, access_token: str, container_id: str,
                        max_wait: int = 180) -> None:
    """Attende che il container sia nello stato FINISHED prima di pubblicarlo."""
    for _ in range(max_wait // 5):
        try:
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
        except requests.RequestException as e:
            print(f"  ⚠ Errore durante polling stato container: {e}")
        time.sleep(5)
    raise TimeoutError(f"Container {container_id} non pronto dopo {max_wait}s.")


def publish_container(ig_user_id: str, access_token: str, container_id: str) -> str:
    """Pubblica il container. Il retry è gestito da _ig_post()."""
    result = _ig_post(
        f"{ig_user_id}/media_publish",
        access_token,
        creation_id=container_id,
    )
    media_id = result["id"]
    print(f"  ✓ Media pubblicato con ID: {media_id}")
    return media_id


# ---------------------------------------------------------------------------
# Pubblicazione con retry globale
# ---------------------------------------------------------------------------

def _do_publish(ig_user_id: str, access_token: str, public_urls: list[str],
                didascalia: str) -> None:
    """Esegue il flusso di pubblicazione (singola foto o carousel)."""
    if len(public_urls) == 1:
        # Singola foto
        print("Creazione container per singola foto...")
        container_id = create_image_container(
            ig_user_id, access_token, public_urls[0], caption=didascalia
        )
        wait_for_container(ig_user_id, access_token, container_id)
        publish_container(ig_user_id, access_token, container_id)
    else:
        # Carousel (Pranzo → Cena)
        print("Creazione container per ogni immagine del carousel...")
        children_ids = []
        for url in public_urls:
            cid = create_image_container(
                ig_user_id, access_token, url, is_carousel_item=True
            )
            wait_for_container(ig_user_id, access_token, cid)
            children_ids.append(cid)

        print("Creazione container carousel...")
        carousel_id = create_carousel_container(
            ig_user_id, access_token, children_ids, didascalia
        )
        wait_for_container(ig_user_id, access_token, carousel_id)
        publish_container(ig_user_id, access_token, carousel_id)


def publish_with_retry(ig_user_id: str, access_token: str, public_urls: list[str],
                       didascalia: str) -> None:
    """
    Esegue _do_publish con retry globale.
    Se tutti i tentativi falliscono, rilancia l'eccezione.
    """
    last_error = None

    for attempt in range(1, GLOBAL_MAX_RETRIES + 1):
        try:
            print(f"\n{'='*60}")
            print(f"TENTATIVO DI PUBBLICAZIONE {attempt}/{GLOBAL_MAX_RETRIES}")
            print(f"{'='*60}\n")

            _do_publish(ig_user_id, access_token, public_urls, didascalia)

            print(f"\n✓ Pubblicazione riuscita al tentativo {attempt}!")
            return  # Successo!

        except Exception as e:
            last_error = e
            print(f"\n✗ Tentativo {attempt}/{GLOBAL_MAX_RETRIES} fallito: {e}")

            if attempt < GLOBAL_MAX_RETRIES:
                delay = GLOBAL_RETRY_DELAYS[attempt - 1]
                print(f"  Riprovo tra {delay}s (backoff esponenziale)...")
                time.sleep(delay)
            else:
                print(f"\n{'='*60}")
                print(f"TUTTI I {GLOBAL_MAX_RETRIES} TENTATIVI FALLITI!")
                print(f"{'='*60}")

    raise RuntimeError(f"Pubblicazione fallita dopo {GLOBAL_MAX_RETRIES} tentativi. Ultimo errore: {last_error}")


# ---------------------------------------------------------------------------
# Attesa orario di pubblicazione
# ---------------------------------------------------------------------------

def wait_for_publish_time() -> None:
    """
    Se non è un'esecuzione manuale, aspetta fino all'orario di pubblicazione
    esatto (09:21:00 IT). Il workflow viene triggerato ~3 min prima per dare
    tempo alla GitHub Action di avviarsi.
    """
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if is_manual or ZoneInfo is None:
        return

    tz_rome = ZoneInfo("Europe/Rome")
    now_rome = dt.datetime.now(tz_rome)
    target_time = now_rome.replace(hour=PUBLISH_HOUR, minute=PUBLISH_MINUTE, second=0, microsecond=0)

    if now_rome < target_time:
        wait_seconds = (target_time - now_rome).total_seconds()
        if wait_seconds <= 900:  # max 15 minuti di attesa (copre tolleranza ±10min + startup)
            print(f"Action avviata alle {now_rome.strftime('%H:%M:%S')}.")
            print(f"Attendo {wait_seconds:.0f} secondi per pubblicare esattamente alle {PUBLISH_HOUR:02d}:{PUBLISH_MINUTE:02d}:00...")
            time.sleep(wait_seconds)
            print("Ora esatta raggiunta. Avvio pubblicazione!")
        else:
            print(f"Troppo presto ({now_rome.strftime('%H:%M:%S')}), attesa > 10 min. Pubblico subito.")
    else:
        diff = (now_rome - target_time).total_seconds()
        print(f"Orario {PUBLISH_HOUR:02d}:{PUBLISH_MINUTE:02d} già passato da {diff:.0f}s. Pubblico subito.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Token ufficiale Instagram Graph API (da GitHub Secrets)
    ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
    IG_USER_ID = os.environ.get("IG_USER_ID")

    if not ACCESS_TOKEN:
        print("Errore: IG_ACCESS_TOKEN non impostato.")
        sys.exit(1)
    if not IG_USER_ID:
        print("Errore: IG_USER_ID non impostato.")
        sys.exit(1)

    # Cartella target
    posts_dir = REPO_ROOT / "assets" / "posts"
    if not posts_dir.exists():
        print(f"La cartella {posts_dir} non esiste. Non c'è nulla da pubblicare.")
        sys.exit(1)

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

    # Costruisci URL raw di GitHub per ogni immagine
    print("Costruzione URL raw GitHub per le immagini...")
    public_urls = []
    for path in album_paths:
        relative = f"assets/posts/{path.name}"
        url = github_raw_url(relative)
        print(f"  {path.name} → {url}")
        public_urls.append(url)

    print()

    # ── Aspetta l'orario di pubblicazione esatto (09:21:00 IT) ──
    wait_for_publish_time()

    # ── Pubblica con retry globale ──
    try:
        publish_with_retry(IG_USER_ID, ACCESS_TOKEN, public_urls, didascalia)
    except RuntimeError as e:
        print(f"\n❌ ERRORE FATALE: {e}")
        sys.exit(1)

    print("\n🎉 Pubblicazione completata con successo!")

    # Crea un file di lock per impedire post duplicati
    with open(lock_file, "w") as f:
        f.write("Pubblicato con successo.")


if __name__ == "__main__":
    main()
