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


def main():
    _menu_path = os.path.join(DATA_DIR, 'menu.json')
    _canteens_path = os.path.join(DATA_DIR, 'canteens.json')
    if not os.path.exists(_menu_path) or not os.path.exists(_canteens_path):
        print("File richiesti mancanti.")
        sys.exit(1)

    with open(_menu_path, 'r') as f:
        menu_data = json.load(f)

    with open(_canteens_path, 'r') as f:
        canteens = json.load(f)

    today = datetime.date.today()
    # Lunedì della settimana corrente (include anche i giorni già passati questa settimana)
    start_monday = today - datetime.timedelta(days=today.weekday())
    print(f"Oggi: {today} | Scraping da lunedì: {start_monday}")

    # Scarica i menu da oggi in poi
    aggregated = scrape_from_today(canteens, start_monday)

    today_str = today.isoformat()
    if aggregated:
        # Costruisci i giorni nel formato finale (liste di piatti)
        new_days = build_final_days(aggregated)
        print(f"Trovati dati per {len(new_days)} giorni (da oggi in poi).")

        # Rimuovi dal menu esistente tutti i giorni >= oggi e sostituiscili con i dati freschi
        # I giorni passati (< oggi) restano intatti
        filtered_old = {d: v for d, v in menu_data.items() if d < today_str}

        merged = {**filtered_old, **new_days}
        sorted_menu = dict(sorted(merged.items()))
    else:
        print("Nessun dato nuovo trovato. Uso menu.json esistente per generare i file di oggi.")
        sorted_menu = dict(sorted(menu_data.items()))

    # Salva solo se ci sono modifiche effettive
    old_json = json.dumps(dict(sorted(menu_data.items())), ensure_ascii=False)
    new_json = json.dumps(sorted_menu, ensure_ascii=False)

    menu_changed = old_json != new_json

    if menu_changed:
        with open(_menu_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_menu, f, indent=2, ensure_ascii=False)

        added = len(new_days)
        kept = len(filtered_old)
        print(f"menu.json aggiornato: {kept} giorni passati conservati + {added} giorni da oggi riscritti.")
    else:
        print("Nessuna modifica rilevata. menu.json invariato.")

    # Genera sempre menu_today.json con il menu di oggi
    _today_path = os.path.join(DATA_DIR, 'menu_today.json')
    _today_min_path = os.path.join(DATA_DIR, 'menu_today.min.json')
    if today_str in sorted_menu:
        today_menu = {today_str: sorted_menu[today_str]}
        with open(_today_path, 'w', encoding='utf-8') as f:
            json.dump(today_menu, f, indent=2, ensure_ascii=False)
        with open(_today_min_path, 'w', encoding='utf-8') as f:
            json.dump(today_menu, f, separators=(',', ':'), ensure_ascii=False)
        print(f"menu_today.json e menu_today.min.json generati per {today_str}.")
    else:
        # Nessun menu per oggi: salva oggetto vuoto
        with open(_today_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2, ensure_ascii=False)
        with open(_today_min_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, separators=(',', ':'), ensure_ascii=False)
        print(f"Nessun menu trovato per oggi ({today_str}). menu_today.json e menu_today.min.json vuoti.")

    if not menu_changed:
        sys.exit(0)


if __name__ == "__main__":
    main()
