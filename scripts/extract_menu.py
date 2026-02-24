import requests
import json
import time
from bs4 import BeautifulSoup
import sys
import datetime
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

def init_session(canteen_url):
    """
    Initialize a session by visiting the canteen-specific URL first.
    This ensures that the server sets the correct cookies/session variables
    for that specific canteen (e.g. correct 'id_ristorante').
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    try:
        session.get(canteen_url, timeout=10)
    except requests.RequestException as e:
        print(f"Warning: Failed to connect to base URL {canteen_url}: {e}")
    return session

def fetch_week_data(session, timestamp, tipo_menu_id):
    api_url = "https://canteen.dsutoscana.cloud/ajax_tools/get_week"
    
    payload = {
        'timestamp_selezionato': str(timestamp),
        'tipo_menu_id': str(tipo_menu_id) # Should match the canteen URL suffix
    }
    
    headers = {
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    try:
        response = session.post(api_url, data=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        # print(f"API request failed for timestamp {timestamp}: {e}")
        return None

def parse_menu_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {} # Meal -> Day -> Course -> [Dishes]
    
    meal_sections = soup.find_all('div', class_='tipo_pasto_settimanale')
    
    for section in meal_sections:
        meal_type = section.get('data-tipo-pasto', 'Sconosciuto') # e.g. "Pranzo", "Cena"
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
                        # Extract link if present
                        link_tag = p.find('a')
                        raw_link = link_tag.get('href') if link_tag else None
                        
                        link_url = None
                        if raw_link:
                            if raw_link.startswith("http"):
                                link_url = f"https://canteen.dsutoscana.cloud/menu#cbp={raw_link}"
                            else:
                                if raw_link.startswith("/"):
                                    full_raw = f"https://canteen.dsutoscana.cloud{raw_link}"
                                else:
                                    full_raw = f"https://canteen.dsutoscana.cloud/{raw_link}"
                                link_url = f"https://canteen.dsutoscana.cloud/menu#cbp={full_raw}"

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

def scrape_canteen_menu(canteen, year):
    """
    Scrapes the menu for a single canteen for the given year.
    Returns a dict: Date -> Meal -> Course -> [List of dishes]
    """
    url = canteen.get('today_menu_url')
    name = canteen.get('name')
    if not url:
        return {}

    # Extract tipo_menu_id from URL
    # URL structure: .../menu/0/0/{tipo_menu_id}/{tipo_pasto_id}
    # e.g., https://canteen.dsutoscana.cloud/menu/0/0/4/3 -> tipo_menu_id = 4
    try:
        parts = url.rstrip('/').split('/')
        # We want the second to last part
        if len(parts) >= 2:
            tipo_menu_id = parts[-2]
        else:
            print(f"Warning: URL format unexpected: {url}. Defaulting to 3.")
            tipo_menu_id = '3'
    except Exception as e:
        print(f"Error parsing URL {url}: {e}. Defaulting to 3.")
        tipo_menu_id = '3'

    session = init_session(url)
    canteen_menus = {} # Key: Date -> Meal -> Course -> [Dishes]
    
    # Start mainly from the beginning of the year
    current_date = datetime.date(year, 1, 1)
    # Align to Monday
    start_week_monday = current_date - datetime.timedelta(days=current_date.weekday())
    
    day_mapping = {
        'Lunedì': 0, 'Martedì': 1, 'Mercoledì': 2, 'Giovedì': 3,
        'Venerdì': 4, 'Sabato': 5, 'Domenica': 6
    }
    
    current_monday = start_week_monday
    # Loop until we are well into the next year to cover everything
    end_limit = datetime.date(year + 1, 1, 15)
    
    # Track consecutive failures to break early if needed
    empty_streak = 0
    
    while current_monday < end_limit:
        timestamp = int(datetime.datetime.combine(current_monday, datetime.time(12, 0)).timestamp())
        
        data = fetch_week_data(session, timestamp, tipo_menu_id)
        
        week_has_data = False
        if data and data.get('status') == 'success':
            html_content = data.get('visualizzazione_settimanale', '')
            weekly_data = parse_menu_html(html_content)
            
            # Map simplified day names back to real ISO dates
            for meal_type, days_dict in weekly_data.items():
                for day_key, courses in days_dict.items():
                    # day_key is "Lunedì" or "Lunedì 10/02"
                    # We just need the day name to calculate offset
                    day_name = day_key.split()[0].capitalize() 
                    
                    if day_name in day_mapping:
                        offset = day_mapping[day_name]
                        actual_date = current_monday + datetime.timedelta(days=offset)
                        date_str = actual_date.isoformat()
                        
                        # Only store if within reasonable range (optional, but clean)
                        # if actual_date.year != year: ...
                        
                        if date_str not in canteen_menus:
                            canteen_menus[date_str] = {"date": date_str}
                        
                        if meal_type not in canteen_menus[date_str]:
                             canteen_menus[date_str][meal_type] = {}
                             
                        # Merge courses
                        for course, dishes in courses.items():
                            canteen_menus[date_str][meal_type][course] = dishes
                            week_has_data = True
        
        if week_has_data:
            empty_streak = 0
        else:
            empty_streak += 1
            if data and data.get('errors') and "NOSEASON" in str(data.get('errors')):
                # Explicit end of season signal
                break
        
        # If we have too many empty weeks in a row late in the year, maybe stop
        # But holidays exist, so be careful. 
        
        current_monday += datetime.timedelta(days=7)
        # time.sleep(0.2) # Be nice
        
    return canteen_menus

def main():
    _canteens_path = os.path.join(DATA_DIR, 'canteens.json')
    if not os.path.exists(_canteens_path):
        print("Error: canteens.json not found.")
        return

    with open(_canteens_path, 'r') as f:
        canteens = json.load(f)
        
    scrape_year_target = 2026
    print(f"Updating menu cache for year {scrape_year_target}...")
    
    # We will aggregate all data into this structure:
    # aggregated[Date][Meal][Course][DishName] = { ... info + list of canteens ... }
    aggregated = {}
    
    for canteen in canteens:
        c_name = canteen['name']
        print(f"Scraping {c_name} ...")
        
        c_data = scrape_canteen_menu(canteen, scrape_year_target)
        days_found = len(c_data)
        print(f"  -> Found menus for {days_found} days.")
        
        # Merge this canteen's data into the aggregated structure
        for date_str, day_content in c_data.items():
            if date_str not in aggregated:
                aggregated[date_str] = {}
            
            for meal_type, courses in day_content.items():
                if meal_type == "date": continue
                
                if meal_type not in aggregated[date_str]:
                    aggregated[date_str][meal_type] = {}
                
                for course, dishes in courses.items():
                    if course not in aggregated[date_str][meal_type]:
                         aggregated[date_str][meal_type][course] = {}
                    
                    target_course_map = aggregated[date_str][meal_type][course]
                    
                    for dish in dishes:
                        # Use exact name for now as key, could be normalized if needed
                        d_name = dish['name'].strip()
                        
                        if d_name not in target_course_map:
                            target_course_map[d_name] = {
                                "name": d_name,
                                "link": dish['link'],
                                "available_at": []
                            }
                        
                        # Append current canteen if not already present
                        if c_name not in target_course_map[d_name]['available_at']:
                            target_course_map[d_name]['available_at'].append(c_name)

    # Convert aggregated data to the final list-based structure
    print("Aggregating results...")
    final_output = {}
    
    dates_sorted = sorted(aggregated.keys())
    for date_str in dates_sorted:
        final_output[date_str] = {"date": date_str}
        
        # Sort meals? Usually Prano, Cena. Use extracted keys.
        for meal_type, courses in aggregated[date_str].items():
            final_output[date_str][meal_type] = {}
            
            for course, dish_map in courses.items():
                # Convert dict of dishes back to list
                dish_list = list(dish_map.values())
                # Sort dishes alphabetically
                dish_list.sort(key=lambda x: x['name'])
                
                final_output[date_str][meal_type][course] = dish_list

    output_file = os.path.join(DATA_DIR, 'menu.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    print(f"Done. Saved {len(final_output)} days to {output_file}.")

if __name__ == "__main__":
    main()
