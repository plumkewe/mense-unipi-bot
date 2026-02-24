import json
import re
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

DAYS_MAP = {
    "lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6,
    "lune": 0, "mart": 1, "merc": 2, "giov": 3, "vene": 4, "saba": 5, "dome": 6
}

def parse_schedule_string(schedule_str):
    schedule = {str(i): [] for i in range(7)}
    if not schedule_str:
        return schedule
        
    lines = schedule_str.replace(" – ", "-").replace(" - ", "-").split("\n")
    
    for line in lines:
        line = line.strip().lower()
        if not line or "chiuso" in line:
            continue
            
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
            
        days_part = parts[0].strip()
        times_part = parts[1].strip()
        
        target_days = []
        if "-" in days_part:
            d_range = days_part.split("-")
            start_d = DAYS_MAP.get(d_range[0].strip()[:3], -1)
            end_d = DAYS_MAP.get(d_range[1].strip()[:3], -1)
            
            if start_d != -1 and end_d != -1:
                cur = start_d
                while True:
                    target_days.append(cur)
                    if cur == end_d:
                        break
                    cur = (cur + 1) % 7
        else:
            d_s = days_part.strip()[:3]
            d_idx = DAYS_MAP.get(d_s, -1)
            if d_idx != -1:
                target_days.append(d_idx)
                
        raw_slots = times_part.split("/")
        final_slots = []
        for slot in raw_slots:
            slot = slot.strip()
            # Just clean up spaces
            if slot:
                final_slots.append(slot)
                
        for d in target_days:
            schedule[str(d)].extend(final_slots)
            
    return schedule

def migrate():
    with open(os.path.join(DATA_DIR, "canteens.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
        
    for canteen in data:
        if "opening_hours" in canteen:
            new_oh = {}
            for service, times_str in canteen["opening_hours"].items():
                if isinstance(times_str, str):
                    new_oh[service] = parse_schedule_string(times_str)
            
            canteen["opening_hours"] = new_oh
            
    with open(os.path.join(DATA_DIR, "canteens.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Migration complete.")

if __name__ == "__main__":
    migrate()