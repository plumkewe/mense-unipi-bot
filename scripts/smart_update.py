import json
import datetime
import os
import sys
from extract_menu import init_session, fetch_week_data, parse_menu_html

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# Quante settimane consecutive vuote prima di fermarsi
MAX_EMPTY_WEEKS = 4

DAY_MAPPING = {
    'Lunedì': 0, 'Martedì': 1, 'Mercoledì': 2, 'Giovedì': 3,
    'Venerdì': 4, 'Sabato': 5, 'Domenica': 6
}


def get_tipo_menu_id(url):
    try:
        parts = url.rstrip('/').split('/')
        if len(parts) >= 2:
            return parts[-2]
    except:
        pass
    return '3'


def scrape_from_today(canteens, start_monday):
    """
    Scrapes all canteens week by week starting from `start_monday`.
    Returns aggregated dict: date_str -> meal -> course -> dish_name -> dish_obj
    Only includes dates >= today.
    """
    today = datetime.date.today()
    aggregated = {}  # date_str -> meal -> course -> dish_name -> dish_obj

    for canteen in canteens:
        c_name = canteen.get('name')
        c_url = canteen.get('today_menu_url')
        if not c_url:
            continue

        tipo_menu_id = get_tipo_menu_id(c_url)
        session = init_session(c_url)
        print(f"Scraping {c_name} da {start_monday}...")

        current_monday = start_monday
        empty_streak = 0

        while True:
            timestamp = int(
                datetime.datetime.combine(current_monday, datetime.time(12, 0)).timestamp()
            )
            data = fetch_week_data(session, timestamp, tipo_menu_id)

            week_has_data = False

            if data and data.get('status') == 'success':
                html = data.get('visualizzazione_settimanale', '')
                weekly = parse_menu_html(html)

                for meal_type, days_dict in weekly.items():
                    for day_key, courses in days_dict.items():
                        day_name = day_key.split()[0].capitalize()
                        if day_name not in DAY_MAPPING:
                            continue
                        offset = DAY_MAPPING[day_name]
                        actual_date = current_monday + datetime.timedelta(days=offset)

                        # Skip past dates
                        if actual_date < today:
                            continue

                        date_str = actual_date.isoformat()

                        for course, dishes in courses.items():
                            if not dishes:
                                continue
                            week_has_data = True
                            aggregated.setdefault(date_str, {})
                            aggregated[date_str].setdefault(meal_type, {})
                            aggregated[date_str][meal_type].setdefault(course, {})

                            for dish in dishes:
                                d_name = dish['name'].strip()
                                if d_name not in aggregated[date_str][meal_type][course]:
                                    aggregated[date_str][meal_type][course][d_name] = {
                                        'name': d_name,
                                        'link': dish['link'],
                                        'available_at': []
                                    }
                                entry = aggregated[date_str][meal_type][course][d_name]
                                if c_name not in entry['available_at']:
                                    entry['available_at'].append(c_name)

            if week_has_data:
                empty_streak = 0
            else:
                if data and isinstance(data, dict) and 'NOSEASON' in str(data.get('errors', '')):
                    print(f"  -> NOSEASON ricevuto. Stop per {c_name}.")
                    break
                empty_streak += 1
                if empty_streak >= MAX_EMPTY_WEEKS:
                    print(f"  -> {MAX_EMPTY_WEEKS} settimane vuote consecutive. Stop per {c_name}.")
                    break

            current_monday += datetime.timedelta(days=7)

    return aggregated


MEAL_ORDER = ['Pranzo', 'Cena']


def build_final_days(aggregated):
    """
    Converts the aggregated dish-dict structure to the final list-based structure
    used in menu.json. Always includes Pranzo and Cena keys (empty {} if no data).
    """
    result = {}
    for date_str, meals in aggregated.items():
        result[date_str] = {'date': date_str}
        for meal_type in MEAL_ORDER:
            if meal_type not in meals:
                result[date_str][meal_type] = {}
                continue
            result[date_str][meal_type] = {}
            for course, dish_map in meals[meal_type].items():
                dish_list = sorted(dish_map.values(), key=lambda x: x['name'])
                result[date_str][meal_type][course] = dish_list
    return result


def _load_json(path, fallback=None):
    """Load a JSON file, returning fallback if missing or empty/invalid."""
    if fallback is None:
        fallback = {}
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return fallback
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return fallback


def _load_json_raw(path):
    """Load a JSON file returning both raw text and parsed data.
    Returns ('', {}) if missing or empty/invalid."""
    if not os.path.exists(path):
        return '', {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()
        if not raw.strip():
            return '', {}
        return raw, json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return '', {}


def update_site(data_dir, label):
    """
    Runs the full smart-update pipeline for a single site (Pisa or Firenze).
    data_dir: path to the data directory containing canteens.json, menu.json, etc.
    label: human-readable label for log output (e.g. "UNIPI", "UNIFI").
    Returns True if any file was changed.
    """
    print(f"\n{'='*50}")
    print(f"  Aggiornamento {label}")
    print(f"{'='*50}")

    _menu_path = os.path.join(data_dir, 'menu.json')
    _history_path = os.path.join(data_dir, 'menu_history.json')
    _canteens_path = os.path.join(data_dir, 'canteens.json')
    _today_path = os.path.join(data_dir, 'menu_today.json')

    if not os.path.exists(_canteens_path):
        print(f"[{label}] canteens.json non trovato in {data_dir}. Salto.")
        return False

    canteens = _load_json(_canteens_path, fallback=[])
    if not canteens:
        print(f"[{label}] canteens.json è vuoto. Salto.")
        return False

    menu_raw, menu_data = _load_json_raw(_menu_path)
    history_data = _load_json(_history_path)

    today = datetime.date.today()
    start_monday = today - datetime.timedelta(days=today.weekday())
    print(f"[{label}] Oggi: {today} | Scraping da lunedì: {start_monday}")

    # Scarica i menu da oggi in poi
    aggregated = scrape_from_today(canteens, start_monday)

    today_str = today.isoformat()

    # Sposta i giorni passati dallo snapshot corrente allo storico.
    past_days = {d: v for d, v in menu_data.items() if d < today_str}
    history_merged = dict(history_data)
    appended_to_history = 0
    for date_key in sorted(past_days.keys()):
        if date_key not in history_merged:
            history_merged[date_key] = past_days[date_key]
            appended_to_history += 1
    sorted_history = dict(sorted(history_merged.items()))

    if aggregated:
        new_days = build_final_days(aggregated)
        print(f"[{label}] Trovati dati per {len(new_days)} giorni (da oggi in poi).")
        sorted_menu = dict(sorted(new_days.items()))
    else:
        print(f"[{label}] Nessun dato nuovo trovato. Mantengo in menu.json solo i giorni da oggi in poi.")
        future_days = {d: v for d, v in menu_data.items() if d >= today_str}
        sorted_menu = dict(sorted(future_days.items()))

    # Salva solo se ci sono modifiche effettive
    old_json = json.dumps(dict(sorted(menu_data.items())), ensure_ascii=False)
    new_json = json.dumps(sorted_menu, ensure_ascii=False)
    menu_changed = old_json != new_json

    old_history_json = json.dumps(dict(sorted(history_data.items())), ensure_ascii=False)
    new_history_json = json.dumps(sorted_history, ensure_ascii=False)
    history_changed = old_history_json != new_history_json

    minified_menu_json = json.dumps(sorted_menu, separators=(',', ':'), ensure_ascii=False)
    menu_already_minified = menu_raw.strip() == minified_menu_json
    menu_write_required = menu_changed or not menu_already_minified

    if menu_write_required:
        with open(_menu_path, 'w', encoding='utf-8') as f:
            f.write(minified_menu_json)

    if menu_changed:
        print(f"[{label}] menu.json aggiornato con {len(sorted_menu)} giorni da oggi in poi.")
    elif menu_write_required:
        print(f"[{label}] Nessuna modifica dati rilevata. menu.json riscritto in formato minificato.")
    else:
        print(f"[{label}] Nessuna modifica rilevata. menu.json invariato.")

    if history_changed:
        with open(_history_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_history, f, indent=2, ensure_ascii=False)
        print(f"[{label}] menu_history.json aggiornato: aggiunte {appended_to_history} nuove date passate.")
    else:
        print(f"[{label}] Nessuna modifica rilevata su menu_history.json.")

    # Genera sempre menu_today.json con il menu di oggi
    if today_str in sorted_menu:
        today_menu = {today_str: sorted_menu[today_str]}
        with open(_today_path, 'w', encoding='utf-8') as f:
            json.dump(today_menu, f, separators=(',', ':'), ensure_ascii=False)
        print(f"[{label}] menu_today.json generato per {today_str}.")
    else:
        with open(_today_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, separators=(',', ':'), ensure_ascii=False)
        print(f"[{label}] Nessun menu trovato per oggi ({today_str}). menu_today.json vuoto.")

    return menu_changed or history_changed


def main():
    today = datetime.date.today()

    # Siti da aggiornare: (data_dir, label)
    sites = [
        (DATA_DIR, 'UNIPI'),
        (os.path.join(DATA_DIR, 'unifi'), 'UNIFI'),
    ]

    any_changed = False
    for data_dir, label in sites:
        changed = update_site(data_dir, label)
        if changed:
            any_changed = True

    if not any_changed:
        print("\nNessuna modifica rilevata su nessun sito.")
        sys.exit(0)


if __name__ == "__main__":
    main()

