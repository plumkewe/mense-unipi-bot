import requests
import json
import time
from bs4 import BeautifulSoup
import sys
import datetime

def init_session():
    session = requests.Session()
    # 1. Initialize session by visiting base URL
    base_url = "https://canteen.dsutoscana.cloud/menu/0/0/3/3"
    try:
        session.get(base_url, timeout=10)
    except requests.RequestException as e:
        print(f"Warning: Failed to connect to base URL: {e}")
    return session

def fetch_week_data(session, timestamp):
    api_url = "https://canteen.dsutoscana.cloud/ajax_tools/get_week"
    
    payload = {
        'timestamp_selezionato': str(timestamp),
        'tipo_menu_id': '3'
    }
    
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = session.post(api_url, data=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API request failed for timestamp {timestamp}: {e}")
        return None

def parse_menu_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    
    meal_sections = soup.find_all('div', class_='tipo_pasto_settimanale')
    
    for section in meal_sections:
        meal_type = section.get('data-tipo-pasto', 'Sconosciuto')
        result[meal_type] = {}
        
        table = section.find('table', class_='tabella_menu_settimanale')
        if not table:
            continue
            
        header_row = table.find('tr')
        days = []
        if header_row:
            day_headers = header_row.find_all('th', class_='giorno_della_settimana')
            days = [th.get_text(strip=True) for th in day_headers]
            
        for day in days:
            result[meal_type][day] = {}
            
        rows = table.find_all('tr', class_='portata')
        for row in rows:
            course_header = row.find('th')
            if not course_header:
                continue
            course_name = course_header.get_text(strip=True)
            
            cells = row.find_all('td')
            
            for i, cell in enumerate(cells):
                if i >= len(days):
                    break
                
                day = days[i]
                dishes = []
                dish_elements = cell.find_all('p', class_='piatto_inline')
                for p in dish_elements:
                    text_content = p.get_text(strip=True)
                    if text_content:
                        # Estrai il link se presente
                        link_tag = p.find('a')
                        raw_link = link_tag.get('href') if link_tag else None
                        
                        link_url = None
                        if raw_link:
                            # Aggiungi il prefisso per aprire correttamente l'overlay
                            # Se il link è già assoluto
                            if raw_link.startswith("http"):
                                link_url = f"https://canteen.dsutoscana.cloud/menu#cbp={raw_link}"
                            # Se è relativo
                            else:
                                if raw_link.startswith("/"):
                                    full_raw = f"https://canteen.dsutoscana.cloud{raw_link}"
                                else:
                                    full_raw = f"https://canteen.dsutoscana.cloud/{raw_link}"
                                link_url = f"https://canteen.dsutoscana.cloud/menu#cbp={full_raw}"

                        # Salva come dizionario invece che stringa semplice
                        dish_obj = {
                            "name": text_content,
                            "link": link_url
                        }
                        dishes.append(dish_obj)
                
                if dishes:
                    if course_name not in result[meal_type][day]:
                        result[meal_type][day][course_name] = []
                    result[meal_type][day][course_name].extend(dishes)
                    
    return result

def scrape_year(year):
    session = init_session()
    all_menus = {}
    
    # Start from the Monday of the week containing Jan 1st of the target year
    current_date = datetime.date(year, 1, 1)
    start_week_monday = current_date - datetime.timedelta(days=current_date.weekday())
    
    print(f"Starting scrape for year {year}...")
    
    # Day name mapping for Italian
    day_mapping = {
        'Lunedì': 0, 'Martedì': 1, 'Mercoledì': 2, 'Giovedì': 3,
        'Venerdì': 4, 'Sabato': 5, 'Domenica': 6
    }

    current_monday = start_week_monday
    
    # Continue as long as the week starts within the year (or slightly before/after to cover full year)
    # We will loop until the Monday is in the next year
    while current_monday.year <= year:
        # Create a timestamp for noon of the Monday (to be safe with timezones)
        # Using datetime.combine for clarity
        dt = datetime.datetime.combine(current_monday, datetime.time(12, 0))
        timestamp = int(dt.timestamp())
        
        print(f"Fetching week starting {current_monday}...")
        
        data = fetch_week_data(session, timestamp)
        
        if data and data.get('status') == 'success':
            html_content = data.get('visualizzazione_settimanale', '')
            weekly_data = parse_menu_html(html_content)
            
            # Reorganize data by Date
            # weekly_data structure: { 'Pranzo': { 'Lunedì': ... }, ... }
            
            parsed_something = False
            for meal_type, days_dict in weekly_data.items():
                for day_key, courses in days_dict.items():
                    # day_key could be "Lunedì" or "Lunedì 10/02"
                    # We extract the day name to find the offset
                    day_name = day_key.split()[0].capitalize() 
                    
                    if day_name in day_mapping:
                        offset = day_mapping[day_name]
                        actual_date = current_monday + datetime.timedelta(days=offset)
                        date_str = actual_date.isoformat()
                        
                        if date_str not in all_menus:
                            all_menus[date_str] = {"date": date_str}
                        
                        # Add meal info
                        # We might want to separate Pranzo and Cena
                        all_menus[date_str][meal_type] = courses
                        parsed_something = True
            
            if not parsed_something:
                print(f"  No menu found for week {current_monday}")
                
        else:
            err = data.get('errors') if data else "Request failed"
            print(f"  Error/No data for {current_monday}: {err}")
            
            # Stop if we hit the limit of available data (NOSEASON)
            if err and "NOSEASON" in str(err):
                print("  Future data not yet available (NOSEASON). Stopping scrape.")
                break
            
        # Be nice to the server
        time.sleep(1)
        current_monday += datetime.timedelta(days=7)
        
    return all_menus

if __name__ == "__main__":
    year = 2026
    menu_data = scrape_year(year)
    
    output_file = 'menu.json'
    print(f"Saving {len(menu_data)} days of menu to {output_file}...")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Sort by date
        sorted_menu = dict(sorted(menu_data.items()))
        json.dump(sorted_menu, f, indent=2, ensure_ascii=False)
    
    print("Done.")
