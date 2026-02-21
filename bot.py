import os
import json
import logging
import pytz
import asyncio
import requests

# --- FIX per APScheduler < 3.10 su Python recenti ---
# APScheduler 3.6.3 (usato da python-telegram-bot su certi setup) crasha
# se riceve una timezone tipo ZoneInfo (nuovo standard) invece di pytz.
# Monkeypatchiamo la funzione di utility per accettare fallback.
try:
    import apscheduler.util
    original_astimezone = apscheduler.util.astimezone
    def safe_astimezone(timezone):
        if timezone is None:
            return None
        try:
            return original_astimezone(timezone)
        except TypeError:
            # Se è un oggetto ZoneInfo o simile che APScheduler non digerisce,
            # cerchiamo di convertirlo in pytz o usiamo UTC come fallback.
            if hasattr(timezone, 'key'): # ZoneInfo
                return pytz.timezone(timezone.key)
            return pytz.utc
    apscheduler.util.astimezone = safe_astimezone
except ImportError:
    pass
# ----------------------------------------------------

from datetime import datetime, timedelta, time
import re
from uuid import uuid4
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InlineQueryResultArticle, InputTextMessageContent, InlineQueryResultsButton, InlineQueryResultPhoto
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, InlineQueryHandler

# Configurazione del logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Carica il file menu.json
def load_menu():
    try:
        with open("menu.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: menu.json non trovato!")
        return {}

MENU = load_menu()

# Carica il file canteens.json
def load_canteens():
    try:
        with open("canteens.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            # Mappa id -> nome per filtro e nome -> id visualizzazione se serve
            return {c["id"]: c["name"] for c in data}
    except FileNotFoundError:
        logger.error("Errore: canteens.json non trovato!")
        return {}

def load_canteens_full():
    try:
        with open("canteens.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: canteens.json non trovato!")
        return []

CANTEENS = load_canteens()
CANTEENS_FULL = load_canteens_full()

# Carica il file rates.json
def load_rates():
    try:
        with open("rates.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: rates.json non trovato!")
        return []

RATES = load_rates()

# Carica il file combinations.json
def load_combinations():
    try:
        with open("combinations.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: combinations.json non trovato!")
        return {}

COMBINATIONS = load_combinations()

FEEDBACK_TEXT = (
    "\n\n*Feedback e Supporto*\n"
    "Hai suggerimenti o vuoi segnalare un bug?\n"
    "Invia una mail: `lyubomyr.malay@gmail.com`\n"
    "Scrivici su Telegram: @doveunipi"
)


# --- RIMOSSO PATCH APSCHEDULER RIDONDANTE ---


def get_menu_text(date_str, meal_type, canteen_name=None):
    """Recupera il testo del menù per una data, un tipo di pasto e una mensa specifica."""
    day_menu = MENU.get(date_str)
    
    # Intestazione Data Decorativa
    header = ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_pretty = format_date_it(dt)
        if canteen_name:
            canteen_clean = canteen_name.replace("Mensa ", "").upper()
            header = f"꧁   {canteen_clean}   ꧂\n_{date_pretty}_\n\n"
        else:
            header = f"꧁   {date_pretty}   ꧂\n\n"
    except Exception:
        header = f"꧁   {date_str}   ꧂\n\n"

    if not day_menu:
        return f"{header}Nessun menù disponibile per questa data."

    meal_menu = day_menu.get(meal_type)
    
    # A volte potrebbe esserci la data ma non il tipo di pasto
    if not meal_menu:
         return f"{header}Nessun menù disponibile per il {meal_type.lower()}."

    # Calcoliamo le mense attive per questo pasto se siamo in modalità TUTTE
    is_all_mode = (canteen_name == "TUTTE")
    active_canteens = set()
    if is_all_mode:
        for cat, dishes in meal_menu.items():
            if dishes:
                for dish in dishes:
                    if isinstance(dish, dict):
                        available = dish.get("available_at", [])
                        active_canteens.update(available)

    text = header
    has_dishes = False

    # Itera sulle categorie (es. Primi Piatti, Secondi Piatti)
    for category, dishes in meal_menu.items():
        if dishes: 
            # Filtra i piatti per mensa
            filtered_dishes = []
            for dish in dishes:
                if isinstance(dish, dict):
                    # Se il piatto ha la lista 'available_at', controlliamo se la mensa è inclusa
                    available = dish.get("available_at", [])
                    if canteen_name and canteen_name != "TUTTE" and available:
                        if canteen_name in available:
                            filtered_dishes.append(dish)
                    else:
                        # Se non c'è filtro mensa o siamo in modalità TUTTE, mostriamo tutto
                        filtered_dishes.append(dish)
                else:
                    # Stringa semplice (vecchio formato), mostra sempre
                    filtered_dishes.append(dish)

            if filtered_dishes:
                has_dishes = True
                clean_category = category.upper().replace(" PIATTI", "")
                text += f"*{clean_category}*\n"
                for dish in filtered_dishes:
                    if isinstance(dish, dict):
                        name = dish.get("name", "").strip().capitalize()
                        link = dish.get("link")
                        
                        # Aggiunta logica "Solo in..."
                        suffix = ""
                        if is_all_mode:
                            available = dish.get("available_at", [])
                            if available:
                                dish_canteens = set(available)
                                # Se il piatto non è disponibile in tutte le mense attive, mostriamo dove lo è
                                # Usiamo active_canteens calcolato all'inizio della funzione
                                if dish_canteens != active_canteens and len(active_canteens) > 1:
                                    # Formatta i nomi delle mense (rimuovi "Mensa ")
                                    short_canteens = [c.replace("Mensa ", "") for c in available]
                                    suffix = f" (Solo {', '.join(short_canteens)})"

                        if link:
                            text += f"- {name}{suffix} [↗︎\uFE0E]({link})\n"
                        else:
                            text += f"- {name}{suffix}\n"
                    else:
                        text += f"- {dish.capitalize()}\n"
                text += "\n"
            
    if not has_dishes:
        return f"{header}Nessun piatto disponibile per questa mensa."

    return text

def get_canteen_selection_keyboard():
    """Tastiera per selezionare la mensa."""
    buttons = []
    # Ordina per nome per consistenza
    sorted_canteens = sorted(CANTEENS.items(), key=lambda x: x[1])
    
    # Aggiungi bottone TUTTE
    buttons.append([InlineKeyboardButton("TUTTE", callback_data="sel_canteen|all")])

    for c_id, c_name in sorted_canteens:
        # Pulisci o accorcia il nome se serve, per ora usiamo il nome completo
        clean_name = c_name.replace("Mensa ", "")
        buttons.append([InlineKeyboardButton(clean_name, callback_data=f"sel_canteen|{c_id}")])
        
    return InlineKeyboardMarkup(buttons)

def get_keyboard(date_str, meal_type, canteen_id, is_inline=False):
    """Crea la tastiera inline con i pulsanti di navigazione."""
    
    # Bottone per cambiare pasto (Pranzo <-> Cena)
    other_meal = "Cena" if meal_type == "Pranzo" else "Pranzo"
    # callback_data format: action|date|meal|canteen_id
    toggle_button = InlineKeyboardButton(other_meal.upper(), callback_data=f"toggle|{date_str}|{other_meal}|{canteen_id}")
    
    try:
        current_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        current_date_obj = datetime.now(pytz.timezone('Europe/Rome'))

    prev_date = (current_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (current_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    today_date = datetime.now(pytz.timezone('Europe/Rome')).strftime("%Y-%m-%d")

    # Logica bottone centrale (Oggi/Home)
    if not is_inline and date_str == today_date:
        # Se NON è inline e siamo già a oggi, torna alla selezione mense
        center_callback = "sel_canteen|reset"
    else:
        # Altrimenti (inline o data diversa da oggi), torna sempre a oggi per la stessa mensa
        center_callback = f"nav|{today_date}|{meal_type}|{canteen_id}"

    nav_buttons = [
        InlineKeyboardButton("◀︎\uFE0E", callback_data=f"nav|{prev_date}|{meal_type}|{canteen_id}"),
        InlineKeyboardButton("○︎\uFE0E", callback_data=center_callback),
        InlineKeyboardButton("▶︎\uFE0E", callback_data=f"nav|{next_date}|{meal_type}|{canteen_id}"),
    ]
    
    orario_button = InlineKeyboardButton("ORARIO", callback_data=f"orario|{date_str}|{meal_type}|{canteen_id}")
    
    keyboard = [
        nav_buttons,
        [toggle_button],
        [orario_button]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def format_date_it(date_obj):
    days = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    months = ["", "GEN", "FEB", "MAR", "APR", "MAG", "GIU", "LUG", "AGO", "SET", "OTT", "NOV", "DIC"]
    return f"{days[date_obj.weekday()]} {date_obj.day} {months[date_obj.month]}"

def get_dish_schedule(dish_name):
    """Genera il testo con la lista delle future occorrenze del piatto (senza emoji)."""
    target_clean = dish_name.strip().upper()
    occurrences = []
    today = datetime.now(pytz.timezone('Europe/Rome')).date()
    sorted_dates = sorted(MENU.keys())
    
    for date_str in sorted_dates:
        try:
             menu_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
             continue
        
        if menu_date < today:
             continue
             
        days_diff = (menu_date - today).days
        day_menu = MENU[date_str]
        
        for meal in ["Pranzo", "Cena"]:
             if meal in day_menu:
                 found_canteens = []
                 found = False
                 
                 for cat_dishes in day_menu[meal].values():
                     if not cat_dishes: continue
                     
                     for d in cat_dishes:
                         d_name = ""
                         d_canteens = []
                         if isinstance(d, dict):
                             d_name = d.get("name", "").strip().upper()
                             d_canteens = d.get("available_at", [])
                         else:
                             d_name = d.strip().upper()
                             
                         if d_name == target_clean:
                             found = True
                             if d_canteens:
                                 found_canteens.extend(d_canteens)
                 
                 if found:
                     unique_canteens = sorted(list(set(found_canteens)))
                     occurrences.append({
                         "date": menu_date,
                         "diff": days_diff,
                         "meal": "P" if meal == "Pranzo" else "C",
                         "canteens": unique_canteens
                     })
    
    if not occurrences:
        return f"*{target_clean}*\n\nNessuna occorrenza futura trovata."

    # Costruisci il messaggio
    # Header: nome piatto in caps e bold
    # SPAZIO TRA TITOLO E LISTA
    text_lines = [f"*{target_clean}*", ""]
    
    list_lines = []
    
    # Helper per formattazione data lista
    days_short = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    # Mesi abbreviati per risparmiare spazio e far entrare le mense
    months_short = ["", "GEN", "FEB", "MAR", "APR", "MAG", "GIU", "LUG", "AGO", "SET", "OTT", "NOV", "DIC"]

    for occ in occurrences:
        d = occ["date"]
        wd = days_short[d.weekday()]
        day_month = f"{d.day} {months_short[d.month]}"
        diff_str = f"{occ['diff']}G" # Accorciato GG in G
        meal_flag = occ["meal"]
        
        # Mense: M. Martiri -> Martiri
        c_list = []
        for c in occ["canteens"]:
            c_clean = c.replace("Mensa ", "").upper()
            c_list.append(c_clean)
        
        c_str = ", ".join(c_list)
        if not c_str:
             c_str = "-"

        # Allineamento ottimizzato per colonna Mense
        # ES: MAR 17 MAR  33G P Martiri
        # wd (3) + 1
        # day_month (6) + 1 ("17 MAR")
        # diff (4) + 1 ("33G")
        # meal (1) + 1 ("P")
        # c_str
        
        line = f"{wd:<3} {day_month:<6} {diff_str:<4} {meal_flag} {c_str}"
        list_lines.append(line)
    
    # Unico blocco codice per allineamento
    text_lines.append("```")
    text_lines.extend(list_lines)
    text_lines.append("```")
    
    return "\n".join(text_lines)

def get_update_keyboard(dish_name):
    """Tastiera con bottone Aggiorna per i risultati di ricerca."""
    # Tagliamo il nome se troppo lungo per evitare errori API (limite 64 bytes totali)
    # upd| è 4 char, restano 60.
    safe_name = dish_name.strip().upper()
    if len(safe_name.encode('utf-8')) > 50:
         safe_name = safe_name[:50]
         
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("AGGIORNA", callback_data=f"upd|{safe_name}")]
    ])

# --- FUNZIONI PER ORARI MENSE ---
DAYS_REV = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]

def get_canteen_status_info(schedule_map, service_name=""):
    """Calcola stato attuale (Aperta/Chiusa) e orari formattati per ogni giorno."""
    tz = pytz.timezone('Europe/Rome')
    now = datetime.now(tz)
    now_time = now.time()
    today_idx = now.weekday()
    
    # Determina genere grammaticale
    # Default femminile (Mensa, Pizzeria), maschile se "Prendi e vai"
    is_female = True
    if "prendi" in service_name.lower():
        is_female = False
        
    txt_open = "APERTA" if is_female else "APERTO"
    txt_closed = "CHIUSA" if is_female else "CHIUSO"
    
    # 1. Calcola Stato
    status = txt_closed
    
    # Recupera gli slot di ogg (da JSON sono stringhe "HH:MM-HH:MM")
    # schedule_map ha chiavi stringa "0".."6"
    today_slots_str = schedule_map.get(str(today_idx), [])
    
    # Converti in oggetti time per confronto
    today_slots_objs = []
    for slot in today_slots_str:
        times = re.findall(r"(\d{1,2})[:.](\d{2})", slot)
        if len(times) == 2:
            try:
                t1 = time(int(times[0][0]), int(times[0][1]))
                t2 = time(int(times[1][0]), int(times[1][1]))
                today_slots_objs.append((t1, t2))
            except ValueError:
                pass
    
    today_slots_objs.sort(key=lambda x: x[0])
    
    is_open = False
    next_open = None
    
    for start_t, end_t in today_slots_objs:
        if start_t <= now_time <= end_t:
            is_open = True
            # Controlla chiusura imminente (es. entro 30 min)
            today_date = now.date()
            dt_end = tz.localize(datetime.combine(today_date, end_t))
            
            closing_in = dt_end - now
            if closing_in < timedelta(minutes=30):
                status = f"CHIUDE ALLE {end_t.strftime('%H:%M')}"
            else:
                status = f"{txt_open} FINO ALLE {end_t.strftime('%H:%M')}"
            break
        elif now_time < start_t:
            if next_open is None:
                next_open = start_t
                
    if not is_open:
        if next_open:
            status = f"{txt_closed} (Apre {next_open.strftime('%H:%M')})"
        else:
            status = txt_closed

    # 2. Formatta Tabella Orari (Lun ... Dom)
    lines = []
    for i in range(7):
        day_name = DAYS_REV[i]
        # Recupera stringhe orari
        slots_str = schedule_map.get(str(i), [])
        
        if not slots_str:
             lines.append(f"{day_name:<3} Chiuso")
             continue
            
        first_slot = True
        for slot in slots_str:
            # Slot è già "HH:MM-HH:MM", lo usiamo così
            if first_slot:
                lines.append(f"{day_name:<3} {slot}")
                first_slot = False
            else:
                lines.append(f"    {slot}")
                
    formatted_schedule = "\n".join(lines) if lines else "    Chiuso"
    
    return status, formatted_schedule

def format_canteen_info_for_day(canteen, date_str):
    """Genera il testo HTML con gli orari di una mensa per un giorno specifico."""
    c_name = canteen.get("name", "").replace("Mensa ", "")
    
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_idx = target_date.weekday()
        day_name = DAYS_REV[day_idx]
    except ValueError:
        return f"<b>MENSA {c_name.upper()}</b>\nErrore data."
        
    tz = pytz.timezone('Europe/Rome')
    today_date = datetime.now(tz).date()
        
    message_lines = [f"<b>MENSA {c_name.upper()}</b>"]
    
    if "opening_hours" in canteen:
        oh = canteen["opening_hours"]
        for service_type, schedule_map in oh.items():
            
            svc_title = service_type.replace("_", " ").capitalize()
            if svc_title.lower() == "mensa":
                svc_title = "Mensa"
            
            if target_date == today_date:
                status_text, _ = get_canteen_status_info(schedule_map, service_name=service_type)
                message_lines.append(f"<b>{svc_title}</b> {status_text}")
            else:
                message_lines.append(f"<b>{svc_title}</b>")
            
            slots_str = schedule_map.get(str(day_idx), [])
            schedule_block = ""
            if not slots_str:
                 schedule_block = f"{day_name:<3} Chiuso"
            else:
                 lines = []
                 first_slot = True
                 for slot in slots_str:
                     if first_slot:
                         lines.append(f"{day_name:<3} {slot}")
                         first_slot = False
                     else:
                         lines.append(f"    {slot}")
                 schedule_block = "\n".join(lines)
                 
            message_lines.append(f"<pre>{schedule_block}</pre>")
                         
    return "\n".join(message_lines)

def format_canteen_info(canteen):
    """Genera il testo HTML con le informazioni della mensa (stato, orari, ecc)."""
    c_name = canteen["name"]
    seats = canteen.get("seats", "N/D")
    
    message_lines = [f"<b>{c_name.upper()}</b>", ""]
    
    if "services" in canteen:
        services = ", ".join(canteen["services"])
        message_lines.append(f"<b>Servizi:</b> {services}")
        
    message_lines.append(f"<b>Capienza:</b> {seats} posti")
    message_lines.append("") # Spacer
    
    # Orari e Stato
    if "opening_hours" in canteen:
        oh = canteen["opening_hours"]
        # Iteriamo su tutti i tipi di orari (mensa, prendi_e_vai, ecc)
        for service_type, schedule_map in oh.items():
            # Status
            status_text, schedule_block = get_canteen_status_info(schedule_map, service_name=service_type)
            
            # Pretty service name
            svc_title = service_type.replace("_", " ").capitalize()
            if svc_title.lower() == "mensa":
                svc_title = "Mensa" # Just explicit
            
            message_lines.append(f"<b>{svc_title}</b> {status_text}")
            message_lines.append(f"<pre>{schedule_block}</pre>")
            message_lines.append("")

    # Link sito e Google Maps
    links = []
    if "website" in canteen:
        links.append(f"<a href='{canteen['website']}'>SITO↗︎\uFE0E</a>")
        
    lat = canteen.get("coordinates", {}).get("lat")
    lon = canteen.get("coordinates", {}).get("lon")
    
    if lat and lon:
            maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            links.append(f"<a href='{maps_url}'>GOOGLE MAPS↗︎\uFE0E</a>")
    
    if links:
        message_lines.append("  ".join(links))

    return "\n".join(message_lines)

def get_info_keyboard(canteen_id):
    """Tastiera per aggiornare le info della mensa."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("AGGIORNA", callback_data=f"upd_info|{canteen_id}")]
    ])

def get_rates_for_isee(isee_value):
    """Trova la fascia di prezzo corrispondente al valore ISEE."""
    if isee_value < 0:
        return None
        
    for band in RATES:
        min_i = band.get("min_isee")
        max_i = band.get("max_isee")
        
        match = True
        if min_i is not None:
             # For the very first band (starts at 0), we want to include 0 probably.
             if min_i == 0:
                 if isee_value < 0: match = False
             else:
                 if isee_value <= min_i: match = False
                 
        if max_i is not None and match:
            if isee_value > max_i:
                match = False
                
        if match:
            return band
            
    # If no band matched (e.g. > max of all bands? Last band has max_isee: null)
    # The last band has max_isee: null, so it catches everything above 100000.
    return None

def get_rate_message_text(band, note=None):
    """
    Costruisce il testo del messaggio con le tariffe per una specifica fascia.
    """
    header_msg = f"*TARIFFE PER FASCIA {band.get('original_label', '')}*"
    
    code_lines = []
    items_ord = [
        ("pasto_completo", "PASTO COMPLETO"),
        ("pasto_ridotto_a", "PASTO RIDOTTO A"),
        ("pasto_ridotto_b", "PASTO RIDOTTO B"),
        ("pasto_ridotto_c", "PASTO RIDOTTO C")
    ]
    
    first = True
    for key, label in items_ord:
        if not first:
            code_lines.append("-----------")
        first = False
        
        price = band.get(key)
        if price is not None:
            price_fmt = "GRATUITO" if price == 0 else f"€ {price:.2f}"
        else:
            price_fmt = "N/A"
        
        desc = COMBINATIONS.get(key, "")
        
        code_lines.append(f"{label} {price_fmt}")
        if desc:
            code_lines.append(desc)

    final_msg = f"{header_msg}\n\n```\n" + "\n".join(code_lines) + "\n```"
    
    if note:
        final_msg += f"\n\n{note}"
        
    return final_msg


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce le ricerche inline dei piatti."""
    query = update.inline_query.query
    results = []

    # Se la query è vuota, mostra il menu di ogni mensa
    if not query:
        today = datetime.now(pytz.timezone('Europe/Rome')).strftime("%Y-%m-%d")
        meal_type = "Pranzo"
        
        # --- AGGIUNTA VOCE TUTTE ---
        text_all = get_menu_text(today, meal_type, canteen_name="TUTTE")
        
        # is_inline=True così il bottone centrale ricarica la stessa vista e non prova a tornare indietro
        reply_markup_all = get_keyboard(today, meal_type, canteen_id="all", is_inline=True)
        
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="TUTTE",
                description="Visualizza il menù di tutte le mense oggi...",
                thumbnail_url="https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/tutte.png?v=5",
                input_message_content=InputTextMessageContent(text_all, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True),
                reply_markup=reply_markup_all
            )
        )
        
        # Ordiniamo le mense alfabeticamente
        sorted_canteens = sorted(CANTEENS.items(), key=lambda x: x[1])
        
        for c_id, c_name in sorted_canteens:
            # Testo e tastiera specifici per ogni mensa
            text = get_menu_text(today, meal_type, canteen_name=c_name)
            # Passiamo is_inline=True così il bottone centrale NON torna alla selezione mense
            reply_markup = get_keyboard(today, meal_type, canteen_id=c_id, is_inline=True)
            
            clean_name = c_name.upper() # Nome mensa in CAPS
            
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=clean_name,
                    description=f"Visualizza il menù di oggi...",
                    thumbnail_url="https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/mensa.png?v=2", 
                    input_message_content=InputTextMessageContent(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True),
                    reply_markup=reply_markup
                )
            )

        # --- ISTRUZIONI DI UTILIZZO (stile vecchiobot) ---
        instructions = [
            {
                "id": "inst_p",
                "title": "Cerca Piatto",
                "desc": "p:<piatto> (es. p:Arista)",
                "text": "@cibounipibot p: ",
                "thumb": "https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/info.png?v=2"
            },
            {
                "id": "inst_i",
                "title": "Informazioni Mense",
                "desc": "i:<mensa> (es. i:Martiri)",
                "text": "@cibounipibot i: ",
                "thumb": "https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/info.png?v=2"
            },
            {
                "id": "inst_t",
                "title": "Tariffe & ISEE",
                "desc": "t: <isee> (es. t:21065)",
                "text": "@cibounipibot t: ",
                "thumb": "https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/info.png?v=2"
            }
        ]

        for inst in instructions:
            results.append(
                InlineQueryResultArticle(
                    id=inst["id"],
                    title=inst["title"],
                    description=inst["desc"],
                    input_message_content=InputTextMessageContent(
                        message_text=inst["text"],
                        parse_mode=ParseMode.MARKDOWN
                    ),
                    thumbnail_url=inst["thumb"],
                    thumbnail_width=48, 
                    thumbnail_height=48
                )
            )
        
        await update.inline_query.answer(results, cache_time=0)
        return
    
    # Intercetta query che iniziano con "i:" per info mensa
    if query.lower().startswith("i:"):
        # Se la query è solo "i:", mostra lista mense per info
        search_term = query[2:].strip().lower()
        
        for canteen in CANTEENS_FULL:
            c_name = canteen["name"]
            c_id = canteen["id"]
            
            if search_term in c_name.lower() or not search_term:
                seats = canteen.get("seats", "N/D")
                
                message_text = format_canteen_info(canteen)
                reply_markup = get_info_keyboard(c_id)

                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title=f"{c_name} (Informazioni)",
                        description=f"Capienza: {seats} posti",
                        thumbnail_url="https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/mensa.png?v=3", 
                        input_message_content=InputTextMessageContent(message_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True),
                        reply_markup=reply_markup
                    )
                )
        
        button = None
        if not results:
            button = InlineQueryResultsButton(text="Rimaniamo a Pisa...", start_parameter="help")
        await update.inline_query.answer(results, cache_time=0, button=button)
        return

    # Intercetta query che iniziano con "t:" per tariffe
    if query.lower().startswith("t:"):
        search_term = query[2:].strip()
        
        # Caso 1: Solo "t:" -> Mostra immagine tabella generale
        if not search_term:
            results.append(
                InlineQueryResultPhoto(
                    id=str(uuid4()),
                    title="TARIFFE",
                    description="Visualizza le tariffe della mensa...",
                    photo_url="https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/img/table.png?v=1",
                    thumbnail_url="https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/table.png?v=1",
                    caption="Verifica le agevolazioni e i dettagli direttamente sul sito di DSU: https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee",
                    parse_mode=ParseMode.MARKDOWN
                )
            )
            await update.inline_query.answer(results, cache_time=0)
            return
            
        # Caso 2: t:<isee> -> Calcola tariffe specifiche (anche per borsa di studio)
        try:
            isee_val = None
            band = None
            
            # Controlla se è una keyword per borsa di studio
            scholarship_keywords = ["borsa", "dsu", "borsista", "scholarship", "gratis", "idoneo"]
            if any(k in search_term.lower() for k in scholarship_keywords):
                # Cerca la fascia con "scholarship": true nei dati RATES
                for r in RATES:
                    if r.get("scholarship") is True:
                        band = r
                        break
            else:
                # Altrimenti prova a parsare come numero
                isee_val = float(search_term.replace(",", "."))
                band = get_rates_for_isee(isee_val)
            
            if band:
                # 1. Costruisci il messaggio completo (che verrà inviato al click)
                note = None
                reply_markup = None
                
                is_scholarship = band.get("scholarship") is True
                change_date = datetime(2026, 4, 1).date()
                today_date = datetime.now(pytz.timezone('Europe/Rome')).date()
                
                if is_scholarship:
                    if today_date >= change_date:
                        # DATA RAGGIUNTA: Mostra direttamente i prezzi della prima fascia
                        # Cerchiamo la prima fascia per sostituire 'band'
                        for r in RATES:
                             if r.get("min_isee") == 0 and r.get("scholarship") is False:
                                 band = r
                                 break
                        note = "*Nota:* Dal 01/04/2026 i prezzi per i borsisti sono equiparati alla prima fascia."
                    else:
                        # DATA NON RAGGIUNTA: Mostra prezzi attuali (0€) ma con bottone per vedere i futuri
                        note = "*Nota:* Dal 01/04/2026 i prezzi cambieranno."
                        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Visualizza prezzi I fascia", callback_data="show_first_fascia")]])
                
                final_msg = get_rate_message_text(band, note)
                
                items_ord = [
                    ("pasto_completo", "PASTO COMPLETO"),
                    ("pasto_ridotto_a", "PASTO RIDOTTO A"),
                    ("pasto_ridotto_b", "PASTO RIDOTTO B"),
                    ("pasto_ridotto_c", "PASTO RIDOTTO C")
                ]
                thumb_money = "https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/icons/money.png?v=2"
                
                # 2. Genera i risultati singoli per la visualizzazione inline (come prima)
                # Ognuno però invierà lo stesso final_msg
                for key, label in items_ord:
                    price = band.get(key)
                    
                    price_text = ""
                    if price is not None:
                        if price == 0:
                            price_text = "Gratuito"
                        else:
                            price_text = f"€ {price:.2f}"
                    else:
                        price_text = "N/A"

                    # Titolo formattato (es. Pasto Completo)
                    display_title = label.replace("_", " ").title()
                    
                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=display_title,
                            description=price_text,
                            thumbnail_url=thumb_money,
                            input_message_content=InputTextMessageContent(final_msg, parse_mode=ParseMode.MARKDOWN),
                            reply_markup=reply_markup
                        )
                    )
                        
        except ValueError:
            # Se il formato non è valido, non mostriamo risultati ma usiamo il bottone in alto
            results = []
            button = InlineQueryResultsButton(
                text="Usa solo i numeri!", 
                start_parameter="help"
            )
            await update.inline_query.answer(results, cache_time=0, button=button)
            return
            
        await update.inline_query.answer(results, cache_time=0)
        return

    # Intercetta solo le query che iniziano con "p:"
    if not query.lower().startswith("p:"):
        return

    search_term = query[2:].strip().lower() # Rimuove "p:"
    # if len(search_term) < 3: # Opzionale: lunghezza minima
    #     return

    results = []
    today = datetime.now(pytz.timezone('Europe/Rome')).date()
    
    # Ordina le date del menu
    sorted_dates = sorted(MENU.keys())
    
    count = 0
    for date_str in sorted_dates:
        # Controllo rapido per uscire dai loop esterni
        if len(results) >= 49: 
            break
            
        try:
            menu_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
            
        if menu_date < today:
            continue
            
        days_diff = (menu_date - today).days
        
        # Cerca nei pasti
        day_menu = MENU[date_str]
        
        for meal in ["Pranzo", "Cena"]:
            if meal in day_menu:
                 for category, dishes in day_menu[meal].items():
                     if not dishes: continue
                     
                     for dish in dishes:
                         # Controllo limite risultati
                         if len(results) >= 49:
                             break
                        
                         dish_str = dish.get("name", "") if isinstance(dish, dict) else dish

                         if search_term in dish_str.lower():
                             clean_dish_name = dish_str.strip().upper()
                             date_fmt = format_date_it(menu_date)
                             
                             # Recupera le mense per questo piatto specifico
                             canteen_list = []
                             if isinstance(dish, dict):
                                 avail = dish.get("available_at", [])
                                 for c in avail:
                                     canteen_list.append(c.replace("Mensa ", "").upper())
                             canteen_desc = ", ".join(canteen_list)
                             
                             meal_short = "P" if meal == "Pranzo" else "C"
                             description_text = f"{date_fmt}  {meal_short}"
                             if canteen_desc:
                                 description_text += f"\n{canteen_desc}"
                             
                             # Immagine con il numero di giorni (#4cadfd, Bold, Transparent)
                             thumb_url = f"https://placehold.co/128x128/transparent/4cadfd.png?text={days_diff}&font=oswald"
                             
                             # ID Univoco per il risultato
                             result_id = str(uuid4())
                             
                             # Costruisci il messaggio con la lista di tutte le occorrenze future
                             content_text = get_dish_schedule(clean_dish_name)
                             reply_markup = get_update_keyboard(clean_dish_name)

                             results.append(
                                 InlineQueryResultArticle(
                                     id=result_id,
                                     title=clean_dish_name,
                                     description=description_text,
                                     thumbnail_url=thumb_url,
                                     input_message_content=InputTextMessageContent(content_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True),
                                     reply_markup=reply_markup
                                 )
                             )
                             count += 1
    
    button = None
    if not results:
        button = InlineQueryResultsButton(text="Piatto che non servono!", start_parameter="help")
    await update.inline_query.answer(results, cache_time=5, button=button)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /start."""
    user = update.effective_user.first_name
    text = (
        f"*CIBOUNIPI BOT*\n\n"
        "Consulta i menù delle mense universitarie di Pisa.\n\n"
        "*Ricerca Piatto*\n"
        "Digita `@cibounipibot p:nome piatto` in qualsiasi chat.\n\n"
        "*Menu di Oggi*\n"
        "Digita `@cibounipibot` (seguito da spazio) in qualsiasi chat e seleziona la mensa.\n\n"
        "*Info & Orari*\n"
        "Digita `@cibounipibot i:` in qualsiasi chat per orari e stato.\n\n"
        "*Tariffe ISEE*\n"
        "Digita `@cibounipibot t:` per tabella, o `t:isee` (es. `t:20000`) per calcolo personalizzato.\n\n"
        "*Comandi*\n"
        "/menu - Seleziona mensa\n"
            "/links - Link utili DSU\n"
            "/help - Guida completa" +
            FEEDBACK_TEXT
        )
    
    keyboard = [
        [InlineKeyboardButton("Menu di Oggi", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("Cerca Piatto", switch_inline_query_current_chat="p:")],
        [InlineKeyboardButton("Informazioni Mense", switch_inline_query_current_chat="i:")],
        [InlineKeyboardButton("Calcola Tariffa", switch_inline_query_current_chat="t:")],
        [InlineKeyboardButton("Scegli Mensa", callback_data="sel_canteen|reset")],
        [InlineKeyboardButton("Guida", callback_data="show_help")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /menu. Mostra la selezione della mensa."""
    text = "*Seleziona una mensa per vedere il menù:*"
    reply_markup = get_canteen_selection_keyboard()
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /links. Mostra link utili."""
    text = (
        "*LINK UTILI*\n\n"
        "[Sito](https://www.dsu.toscana.it)\n\n"
        "[Sportello studente](https://sportellostudente.dsu.toscana.it/)\n\n"
        "[Instagram](https://www.instagram.com/dsutoscana/)\n\n"
        "[Facebook](https://www.facebook.com/dsutoscana)\n\n"
        "[Canale Whatsapp](https://www.whatsapp.com/channel/0029Vb5mhtEKrWQsuxlBw73k)\n\n"
        "[Canale Telegram](https://t.me/DSUToscana)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /help."""
    text = (
        "*GUIDA ALL'USO*\n\n"
        "*Comandi Principali*\n"
        "/start - Avvia il bot e mostra il menu principale\n"
        "/menu - Seleziona una mensa specifica\n"
        "/links - Mostra link utili DSU\n"
        "/help - Mostra questo messaggio\n\n"
        "*1. Ricerca Piatto*\n"
        "Puoi cercare un piatto specifico (es. \"Pollo\") per scoprire quando e dove verrà servito.\n"
        "Digita `@cibounipibot p:Arista` in qualsiasi chat.\n\n"
        "*2. Menu di Oggi*\n"
        "Per vedere rapidamente il menu di oggi:\n"
        "Digita `@cibounipibot` (seguito da spazio) in qualsiasi chat e seleziona la mensa.\n\n"
        "*3. Info & Orari*\n"
        "Vuoi sapere se una mensa è aperta?\n"
        "Digita `@cibounipibot i:` in qualsiasi chat e seleziona la mensa per vedere orari e stato.\n\n"
        "*4. Tariffe su base ISEE*\n"
        "Digita `@cibounipibot t:` per visualizzare la tabella riassuntiva.\n"
        "Digita `@cibounipibot t:<valore>` (es. `t:20000`) per calcolare la tua tariffa specifica.\n\n"
        "*5. Navigazione Menu*\n"
        "Una volta aperto un menu:\n"
        "◀︎\uFE0E ▶︎\uFE0E : Scorri i giorni (Precedente / Successivo)\n"
        "○︎\uFE0E : Torna ad oggi (o alla lista mense)\n"
        "PRANZO / CENA : Cambia il pasto visualizzato" +
        FEEDBACK_TEXT
    )
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i cl sui bottoni inline."""
    query = update.callback_query
    await query.answer() 

    data = query.data.split("|")
    action = data[0]

    if action == "show_help":
        await help_command(update, context)
        return

    if action == "show_links":
        await links_command(update, context)
        return

    if action == "show_first_fascia":
        # Trova la prima fascia
        target_band = None
        for r in RATES:
             # Prima fascia: non scholarship, min_isee 0
             if r.get("min_isee") == 0 and r.get("scholarship") is False:
                 target_band = r
                 break
        
        if target_band:
            text = get_rate_message_text(target_band)
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("INDIETRO", callback_data="back_to_scholarship")]])
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    if action == "back_to_scholarship":
         # Trova la fascia scholarship
        target_band = None
        for r in RATES:
             if r.get("scholarship") is True:
                 target_band = r
                 break
        
        if target_band:
            note = "*Nota:* Dal 01/04/2026 i prezzi per i borsisti sono equiparati alla prima fascia."
            text = get_rate_message_text(target_band, note)
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("PREZZI I FASCIA", callback_data="show_first_fascia")]])
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return

    if action == "sel_canteen":
        # Data format: sel_canteen|canteen_id
        canteen_id = data[1]
        
        if canteen_id == "reset":
            text = "*Seleziona una mensa per vedere il menù:*"
            reply_markup = get_canteen_selection_keyboard()
            
            # Se il messaggio originale contiene "CIBOUNIPI BOT", è il messaggio di start
            # In questo caso mandiamo un NUOVO messaggio.
            # Altrimenti (siamo già nel flusso menu), modifichiamo il messaggio esistente.
            if "CIBOUNIPI BOT" in query.message.text:
                 await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                 await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            return
            
        # Selezionata una mensa, mostra il menù di oggi
        if canteen_id == "all":
            canteen_name = "TUTTE"
        else:
            canteen_name = CANTEENS.get(canteen_id)

        current_date = datetime.now(pytz.timezone('Europe/Rome')).strftime("%Y-%m-%d")
        meal_type = "Pranzo" # Default
        
        text = get_menu_text(current_date, meal_type, canteen_name)
        reply_markup = get_keyboard(current_date, meal_type, canteen_id)
        
        # Modifica il messaggio esistente
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        return

    if action == "upd":
        dish_name = data[1]
        text = get_dish_schedule(dish_name)
        reply_markup = get_update_keyboard(dish_name)
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        return

    if action == "upd_info":
        canteen_id = data[1]
        # Trova la mensa nei dati completi
        canteen = next((c for c in CANTEENS_FULL if c["id"] == canteen_id), None)
        
        if canteen:
            try:
                text = format_canteen_info(canteen)
                reply_markup = get_info_keyboard(canteen_id)
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except BadRequest as e:
                # Se il messaggio non è cambiato, ignoriamo l'errore
                if "Message is not modified" in str(e):
                    pass
                else:
                    logger.warning(f"Errore durante l'aggiornamento info: {e}")
            except Exception as e:
                logger.error(f"Errore generico aggiornamento info: {e}")
        return

    if action == "orario":
        date_str = data[1]
        meal_type = data[2]
        canteen_id = data[3]
        
        blocks = []
        if canteen_id == "all":
            # Mostriamo gli orari per tutte le mense (solo query del giorno stesso)
            sorted_canteens = sorted(CANTEENS_FULL, key=lambda x: x["name"])
            for c in sorted_canteens:
                blocks.append(format_canteen_info_for_day(c, date_str))
            text = "\n\n".join(blocks)
        else:
            canteen = next((c for c in CANTEENS_FULL if c["id"] == canteen_id), None)
            if canteen:
                text = format_canteen_info_for_day(canteen, date_str)
            else:
                text = "Mensa non trovata."
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("AGGIORNA", callback_data=query.data)],
            [InlineKeyboardButton("INDIETRO", callback_data=f"nav|{date_str}|{meal_type}|{canteen_id}")]
        ])
        
        try:
            if query.inline_message_id:
                await context.bot.edit_message_text(
                    inline_message_id=query.inline_message_id, 
                    text=text, 
                    reply_markup=reply_markup, 
                    parse_mode=ParseMode.HTML, 
                    disable_web_page_preview=True
                )
            else:
                await query.edit_message_text(
                    text=text, 
                    reply_markup=reply_markup, 
                    parse_mode=ParseMode.HTML, 
                    disable_web_page_preview=True
                )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Errore aggiornamento orario: {e}")
        except Exception as e:
            logger.warning(f"Errore aggiornamento orario: {e}")
        return

    # Navigazione o Toggle: nav|date|meal|canteen_id
    if len(data) < 4:
        # Fallback per vecchi bottoni o errori
        return

    date_str = data[1]
    meal_type = data[2]
    canteen_id = data[3]
    
    # Gestione "None" o id non valido
    if canteen_id == "all":
        canteen_name = "TUTTE"
    else:
        canteen_name = CANTEENS.get(canteen_id)
    
    # Se canteen_id è "None" (stringa) o non trovato, canteen_name è None -> mostra tutto (ma senza logica TUTTE)
    if canteen_id == "None":
        canteen_name = None
    
    # Check if query is from inline message
    is_inline_msg = query.inline_message_id is not None

    text = get_menu_text(date_str, meal_type, canteen_name)
    reply_markup = get_keyboard(date_str, meal_type, canteen_id, is_inline=is_inline_msg)

    try:
        if is_inline_msg:
            await context.bot.edit_message_text(inline_message_id=query.inline_message_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.warning(f"Non è stato possibile aggiornare il messaggio: {e}")
    except Exception as e:
        logger.warning(f"Non è stato possibile aggiornare il messaggio: {e}")

async def post_init(application: Application) -> None:
    """Inizializza i comandi del bot."""
    await application.bot.set_my_commands([
        ("start", "Messaggio di benvenuto"),
        ("menu", "Menù delle mense"),
        ("links", "Link utili DSU"),
        ("help", "Guida all'uso")
    ])

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    """Pinga il server per evitare che vada in sleep su Render."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if url:
        try:
            logger.info(f"Pinging {url}...")
            await asyncio.to_thread(requests.get, url, timeout=10)
        except Exception as e:
            logger.error(f"Ping fallito: {e}")

def main() -> None:
    """Avvia il bot."""
    # Recupera il token dalle variabili d'ambiente (GitHub Secrets)
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        logger.error("Errore: La variabile d'ambiente BOT_TOKEN non è impostata.")
        print("Per favore imposta la variabile d'ambiente BOT_TOKEN.")
        return

    # Risoluzione problema timezone per APScheduler e setup applicazione
    # Rimosso .job_queue(None) per permettere l'uso di run_repeating per il ping
    application = Application.builder().token(token).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("links", links_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(InlineQueryHandler(inline_query))

    # Configurazione Webhook (per Render) o Polling (locale)
    PORT = int(os.environ.get("PORT", "8443"))
    WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")

    if WEBHOOK_URL:
        logger.info(f"Avvio in modalità WEBHOOK su porta {PORT}")
        
        # Avvia il ping periodico ogni 14 minuti (840 secondi)
        if application.job_queue:
            application.job_queue.run_repeating(self_ping, interval=840, first=60)
        else:
            logger.error("JobQueue non disponibile! Il self-ping non funzionerà.")

        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=token,
                webhook_url=f"{WEBHOOK_URL}/{token}"
            )
        except Exception as e:
            logger.critical(f"Errore critico durante l'avvio del webhook: {e}")
            raise e
    else:
        logger.info("Avvio in modalità POLLING")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
if __name__ == "__main__":
    main()