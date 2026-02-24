import json
import datetime
import os
import sys
import time
from extract_menu import init_session, fetch_week_data, parse_menu_html

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

def get_tipo_menu_id(url):
    try:
        parts = url.rstrip('/').split('/')
        if len(parts) >= 2:
            return parts[-2]
    except:
        pass
    return '3'

def main():
    _menu_path = os.path.join(DATA_DIR, 'menu.json')
    _canteens_path = os.path.join(DATA_DIR, 'canteens.json')
    if not os.path.exists(_menu_path) or not os.path.exists(_canteens_path):
        print("Required files missing.")
        sys.exit(1)

    with open(_menu_path, 'r') as f:
        menu_data = json.load(f)

    with open(_canteens_path, 'r') as f:
        canteens = json.load(f)

    # Find last date in current menu
    if not menu_data:
        # If empty, default to today
        last_date_str = datetime.date.today().isoformat()
    else:
        # Assuming keys are ISO dates
        last_date_str = max(menu_data.keys())

    last_date = datetime.date.fromisoformat(last_date_str)
    print(f"Last date in menu.json: {last_date}")

    # OPTIMIZATION: Check if we are close to the expiry date.
    # The user wants to run ONLY when the current menu is about to end (the last day).
    # If today is strictly before the last date, we do not need to check for new menus yet.
    today = datetime.date.today()
    
    # If the last_date is greater than today, it means the menu is still valid for days in the future.
    # We only update if we have reached (or passed) the last known day.
    if today < last_date:
        print(f"Current menu is valid until {last_date}. Today is {today}.")
        print("It is not yet the last day of the menu. Skipping update check.")
        sys.exit(0)

    print("Menu is expiring or has expired. checking for updates...")

    # Determine start date for scraping
    # We want to check the weeks following the last known date.
    # If last_date is in a specific week, we start checking the NEXT Monday.
    
    days_ahead = 7 - last_date.weekday() # 0=Monday...6=Sunday. If today is Sunday(6), +1 day -> Monday.
    if days_ahead <= 0:
        days_ahead += 7
    
    start_monday = last_date + datetime.timedelta(days=days_ahead)
    print(f"Starting to check for new menus from week of: {start_monday}")
    
    # Also check if the start_monday is too far in the past? 
    # User surely implies updating constantly.
    
    # User requests to stop ONLY when 'NOSEASON' is returned.
    # We will loop indefinitely week by week until that signal is received.
    
    aggregated_updates = {} # Date -> Meal -> Course -> DishName -> { ... }
    something_found = False

    for canteen in canteens:
        c_name = canteen['name']
        c_url = canteen.get('today_menu_url')
        if not c_url: continue
        
        tipo_menu_id = get_tipo_menu_id(c_url)
        session = init_session(c_url)
        
        print(f"Checking {c_name} starting from {start_monday}...")
        
        local_monday = start_monday
        
        while True:
            timestamp = int(datetime.datetime.combine(local_monday, datetime.time(12, 0)).timestamp())
            data = fetch_week_data(session, timestamp, tipo_menu_id)
            
            week_has_data = False
            if data and data.get('status') == 'success':
                html = data.get('visualizzazione_settimanale', '')
                weekly_parsed = parse_menu_html(html)
                
                # Check if we actually got dishes
                has_dishes = False
                for m in weekly_parsed.values():
                    for d in m.values():
                         if d: has_dishes = True
                
                if has_dishes:
                    week_has_data = True
                    
                    day_mapping = {
                        'Lunedì': 0, 'Martedì': 1, 'Mercoledì': 2, 'Giovedì': 3,
                        'Venerdì': 4, 'Sabato': 5, 'Domenica': 6
                    }
                    
                    for meal_type, days_dict in weekly_parsed.items():
                        for day_key, courses in days_dict.items():
                            clean_day_key = day_key.split()[0].capitalize()
                            if clean_day_key in day_mapping:
                                offset = day_mapping[clean_day_key]
                                actual_date = local_monday + datetime.timedelta(days=offset)
                                date_str = actual_date.isoformat()
                                
                                if date_str not in aggregated_updates:
                                    aggregated_updates[date_str] = {}
                                
                                if meal_type not in aggregated_updates[date_str]:
                                    aggregated_updates[date_str][meal_type] = {}
                                    
                                for course, dishes in courses.items():
                                    if course not in aggregated_updates[date_str][meal_type]:
                                        aggregated_updates[date_str][meal_type][course] = {}
                                    
                                    target_course_map = aggregated_updates[date_str][meal_type][course]

                                    for dish in dishes:
                                        d_name = dish['name'].strip()
                                        if d_name not in target_course_map:
                                             target_course_map[d_name] = {
                                                "name": d_name,
                                                "link": dish['link'],
                                                "available_at": []
                                             }
                                        if c_name not in target_course_map[d_name]['available_at']:
                                            target_course_map[d_name]['available_at'].append(c_name)
            
            if week_has_data:
                something_found = True
            else:
                # Stop immediately if the server explicitly tells us the season (year/period) is over.
                if data and isinstance(data, dict) and data.get('errors') and "NOSEASON" in str(data.get('errors')):
                    print(f"  -> NOSEASON signal received. Terminating scrape for {c_name}.")
                    break
            
            # Safety check
            if (local_monday - start_monday).days > SAFETY_DAYS_LIMIT:
              cal_monday += datetime.timedelta(days=7)

    if something_found:
        print("New menu data collected. Merging...")
        
        count_new_days = 0
        
        for date_str, meal_data in aggregated_updates.items():
            if date_str not in menu_data:
                menu_data[date_str] = {"date": date_str}
                count_new_days += 1
            
            for meal_type, courses in meal_data.items():
                if meal_type not in menu_data[date_str]:
                    menu_data[date_str][meal_type] = {}
                
                existing_courses = menu_data[date_str][meal_type]
                
                for course, dish_dict in courses.items():
                    # dish_dict is Name -> DishObj
                    existing_dish_list = existing_courses.get(course, [])
                    existing_map = {d['name']: d for d in existing_dish_list}
                    
                    for d_name, d_obj in dish_dict.items():
                        if d_name in existing_map:
                            # Merge available_at
                            existing_avail = set(existing_map[d_name]['available_at'])
                            new_avail = set(d_obj['available_at'])
                            combined = list(existing_avail.union(new_avail))
                            combined.sort()
                            existing_map[d_name]['available_at'] = combined
                            
                            if not existing_map[d_name]['link'] and d_obj['link']:
                                existing_map[d_name]['link'] = d_obj['link']
                        else:
                            existing_map[d_name] = d_obj
                    
                    # Convert back to list and sort
                    new_list = list(existing_map.values())
                    new_list.sort(key=lambda x: x['name'])
                    existing_courses[course] = new_list
                
                menu_data[date_str][meal_type] = existing_courses
        
        print(f"Saving menu.json with {count_new_days} new days added/updated.")
        
        # Sort by date
        sorted_menu = dict(sorted(menu_data.items()))
        
        with open(os.path.join(DATA_DIR, 'menu.json'), 'w', encoding='utf-8') as f:
            json.dump(sorted_menu, f, indent=2, ensure_ascii=False)
            
    else:
        print("No new data found for future weeks.")

if __name__ == "__main__":
    main()
