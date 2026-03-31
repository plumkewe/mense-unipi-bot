import re
from datetime import datetime

with open("bot.py", "r", encoding="utf-8") as f:
    bot_code = f.read()

feste_code = """
def load_feste():
    try:
        data_file = os.path.join(DATA_DIR, "feste.json")
        with open(data_file, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

FESTE = load_feste()

def get_holiday_status(canteen_id, date_obj):
    feste = load_feste()
    canteen_feste = feste.get(canteen_id, [])
    for f_period in canteen_feste:
        try:
            start_date = datetime.strptime(f_period["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(f_period["end_date"], "%Y-%m-%d").date()
            if start_date <= date_obj <= end_date:
                return f_period["status"]
        except Exception:
            continue
    return "normal"
"""

bot_code = bot_code.replace("CANTEENS_FULL = load_canteens_full()", "CANTEENS_FULL = loabotanbot_code = bot_co feste_code)

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(bot_code)
