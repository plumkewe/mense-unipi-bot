from datetime import time
import re

DAYS_MAP = {
    "lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6,
    "lune": 0, "mart": 1, "merc": 2, "giov": 3, "vene": 4, "saba": 5, "dome": 6
}
DAYS_REV = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]

def parse_schedule_string(schedule_str):
    """
    Analizza la stringa degli orari (es. 'Lun-Ven: 12:00-14:30') e restituisce una mappa:
    { day_index (0-6): [ (start_time, end_time), ... ] }
    """
    schedule = {i: [] for i in range(7)}
    if not schedule_str:
        return schedule
        
    # Normalizziamo le righe
    lines = schedule_str.replace(" – ", "-").replace(" - ", "-").split("\n")
    
    for line in lines:
        line = line.strip().lower()
        if not line or "chiuso" in line:
            continue
            
        # Separa giorni da orari (giorni: orari)
        parts = line.split(":")
        if len(parts) < 2:
            continue
            
        days_part = parts[0].strip()
        times_part = parts[1].strip()
        
        # Analizza i giorni
        target_days = []
        if "-" in days_part: # Range: lun-ven
            d_range = days_part.split("-")
            # Problem might be here if split returns more than 2 or strict format
            
            # Additional cleanup for safety
            start_s = d_range[0].strip()[:3]
            end_s = d_range[1].strip()[:3]
            
            start_d = DAYS_MAP.get(start_s, -1)
            end_d = DAYS_MAP.get(end_s, -1)
            
            if start_d != -1 and end_d != -1:
                cur = start_d
                while True:
                    target_days.append(cur)
                    if cur == end_d:
                        break
                    cur = (cur + 1) % 7
        else: # Singolo o lista
            d_s = days_part.strip()[:3]
            d_idx = DAYS_MAP.get(d_s, -1)
            if d_idx != -1:
                target_days.append(d_idx)
                
        # Analizza gli orari
        # formati: 12:00-14:30 / 19:00-21:15
        time_slots = []
        raw_slots = times_part.split("/")
        for slot in raw_slots:
            slot = slot.strip()
            # Cerca pattern HH:MM-HH:MM o HH.MM-HH.MM
            times = re.findall(r"(\d{1,2})[:.](\d{2})", slot)
            if len(times) == 2: # start e end
                try:
                    t1 = time(int(times[0][0]), int(times[0][1]))
                    t2 = time(int(times[1][0]), int(times[1][1]))
                    time_slots.append((t1, t2))
                except ValueError:
                    pass
                    
        # Assegna
        for d in target_days:
            schedule[d].extend(time_slots)
            
    return schedule

test_str = "Lun-Ven: 11:45-14:30 / 19:00-21:15\nSab: 12:00-14:30\nDom: 12:00-14:30 / 19:00-21:15"
res = parse_schedule_string(test_str)
print("Parsed Result:")
for d in range(7):
    print(f"{DAYS_REV[d]}: {res[d]}")
