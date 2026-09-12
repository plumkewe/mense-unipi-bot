import os
import json
import logging
import pytz
import asyncio
import requests
import hashlib

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_asset_cache = {}

def get_asset_url(rel_path: str) -> str:
    """Restituisce l'URL GitHub Raw con cache-busting automatico calcolato dall'hash MD5 del file locale."""
    fpath = os.path.join(ASSETS_DIR, rel_path)
    if os.path.isfile(fpath):
        mtime = os.path.getmtime(fpath)
        cached = _asset_cache.get(rel_path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            with open(fpath, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()[:10]
        except Exception:
            h = str(int(mtime))
        url = f"https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/{rel_path}?v={h}"
        _asset_cache[rel_path] = (mtime, url)
        return url
    return f"https://raw.githubusercontent.com/plumkewe/mense-unipi-bot/main/assets/{rel_path}"

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
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update, InlineQueryResultArticle,
    InlineQueryResultsButton, ReplyKeyboardMarkup, KeyboardButton,
    BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, InlineQueryHandler, MessageHandler, filters

# Configurazione del logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Carica il file menu.json
def load_menu():
    try:
        with open(os.path.join(DATA_DIR, "menu.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: menu.json non trovato!")
        return {}

MENU = load_menu()

# Carica il file canteens.json
def load_canteens():
    try:
        with open(os.path.join(DATA_DIR, "canteens.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            # Mappa id -> nome per filtro e nome -> id visualizzazione se serve
            return {c["id"]: c["name"] for c in data}
    except FileNotFoundError:
        logger.error("Errore: canteens.json non trovato!")
        return {}

def load_canteens_full():
    try:
        with open(os.path.join(DATA_DIR, "canteens.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: canteens.json non trovato!")
        return []

CANTEENS = load_canteens()
CANTEENS_FULL = load_canteens_full()

def load_feste():
    try:
        with open(os.path.join(DATA_DIR, "feste.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

FESTE = load_feste()

def get_holiday_status(canteen_id, date_obj):
    canteen_feste = FESTE.get(canteen_id, [])
    for f_period in canteen_feste:
        try:
            start_date = datetime.strptime(f_period["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(f_period["end_date"], "%Y-%m-%d").date()
            if start_date <= date_obj <= end_date:
                return f_period["status"]
        except Exception:
            continue
    return "normal"

def get_canteen_meal_availability(canteen_id, date_obj):
    """Restituisce (ha_pranzo, ha_cena) per la mensa nella data specificata."""
    canteen = next((c for c in CANTEENS_FULL if c.get("id") == canteen_id), None)
    if not canteen:
        return False, False
    day_idx = date_obj.weekday()
    oh_mensa = canteen.get("opening_hours", {}).get("mensa", {})
    slots = oh_mensa.get(str(day_idx), [])
    has_lunch = any(int(s.split(":")[0]) < 16 for s in slots)
    has_dinner = any(int(s.split(":")[0]) >= 16 for s in slots)
    day_status = get_holiday_status(canteen_id, date_obj)
    if day_status == "closed":
        return False, False
    elif day_status == "lunch_only":
        has_dinner = False
    elif day_status == "dinner_only":
        has_lunch = False
    return has_lunch, has_dinner

def get_future_closures_text(canteen_id, target_date):
    """Calcola se ci sono chiusure future rispetto alla data target"""
    canteen_feste = FESTE.get(canteen_id, [])
    for f_period in canteen_feste:
        try:
            start_date = datetime.strptime(f_period["start_date"], "%Y-%m-%d").date()
            end_date = datetime.strptime(f_period["end_date"], "%Y-%m-%d").date()
            
            if start_date > target_date and f_period.get("status") == "closed":
                start_str = start_date.strftime("%d/%m")
                end_str = end_date.strftime("%d/%m")
                return f"<i>Chiusa dal {start_str} al {end_str} per festività</i>"
        except Exception:
            continue
    return ""

# Carica il file rates.json
def load_rates():
    try:
        with open(os.path.join(DATA_DIR, "rates.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: rates.json non trovato!")
        return []

RATES = load_rates()

# Carica il file combinations.json
def load_combinations():
    try:
        with open(os.path.join(DATA_DIR, "combinations.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Errore: combinations.json non trovato!")
        return {}

COMBINATIONS = load_combinations()




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
            header = f"『 {canteen_clean} 』\n_{date_pretty}_\n\n"
        else:
            header = f"『 {date_pretty} 』\n\n"
    except Exception:
        header = f"『 {date_str} 』\n\n"

    if not day_menu:
        return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun menù disponibile per questa data."

    meal_menu = day_menu.get(meal_type)
    
    # A volte potrebbe esserci la data ma non il tipo di pasto
    if not meal_menu:
         return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun menù disponibile per il {meal_type.lower()}."

    is_all_mode = (canteen_name == "TUTTE")
    if not is_all_mode and canteen_name:
        c_id_match = next((k for k, v in CANTEENS.items() if v == canteen_name), None)
        if c_id_match:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                holiday_status = get_holiday_status(c_id_match, date_obj)
                if holiday_status == "closed":
                    return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun piatto disponibile per questa mensa."
                elif holiday_status == "lunch_only" and meal_type.lower() == "cena":
                    return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun piatto disponibile per questa mensa."
                elif holiday_status == "dinner_only" and meal_type.lower() == "pranzo":
                    return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun piatto disponibile per questa mensa."
            except Exception:
                pass

    # Calcoliamo le mense attive per questo pasto se siamo in modalità TUTTE
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
                            text += f"- [{name}]({link}){suffix}\n"
                        else:
                            text += f"- {name}{suffix}\n"
                    else:
                        text += f"- {dish.capitalize()}\n"
                text += "\n"
            
    if not has_dishes:
        return f"{header}ʕ ´•̥̥̥ ᴥ•̥̥̥ ʔ Oh no... Nessun piatto disponibile per questa mensa."

    text += "ʕ•ᴥ•ʔﾉ♡ Buon Appetito!"
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

    MAX_OCC = 60
    has_more = len(occurrences) > MAX_OCC
    
    for occ in occurrences[:MAX_OCC]:
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
        
    if has_more:
        list_lines.append("")
        list_lines.append(f"... {len(occurrences) - MAX_OCC} altre")
    
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

def build_dish_rich_message(dish_name: str):
    """Costruisce il Rich Message (Bot API 10.3) con tabella per la programmazione del piatto e i fallback."""
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
                    if not cat_dishes: 
                        continue
                    
                    for d in cat_dishes:
                        if isinstance(d, dict):
                            d_name = d.get("name", "").strip().upper()
                            d_canteens = d.get("available_at", [])
                        else:
                            d_name = d.strip().upper()
                            d_canteens = []
                            
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

    safe_name = target_clean
    if len(safe_name.encode('utf-8')) > 50:
        safe_name = safe_name[:50]

    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": target_clean
        }
    ]

    days_short = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    months_short = ["", "GEN", "FEB", "MAR", "APR", "MAG", "GIU", "LUG", "AGO", "SET", "OTT", "NOV", "DIC"]

    if not occurrences:
        blocks.append({
            "type": "paragraph",
            "text": "Nessuna occorrenza futura trovata nei menù pubblicati."
        })
    else:
        blocks.append({
            "type": "paragraph",
            "text": "Programmazione nei menù dei prossimi giorni:"
        })

        table_rows = [
            [
                {"text": "DATA", "is_header": True, "align": "left"},
                {"text": "PASTO", "is_header": True, "align": "center"},
                {"text": "MENSE", "is_header": True, "align": "left"}
            ]
        ]

        MAX_OCC = 40
        for occ in occurrences[:MAX_OCC]:
            d = occ["date"]
            wd = days_short[d.weekday()]
            diff = occ["diff"]
            month_name = months_short[d.month]
            
            if diff == 0:
                date_label = f"OGGI ({d.day} {month_name})"
            elif diff == 1:
                date_label = f"DOMANI ({d.day} {month_name})"
            else:
                date_label = f"{wd} {d.day} {month_name} ({diff}G)"
            
            meal_label = "PRANZO" if occ["meal"] == "P" else "CENA"
            
            if len(occ["canteens"]) >= len(CANTEENS) and len(CANTEENS) > 0:
                canteen_label = "TUTTE"
            elif occ["canteens"]:
                canteen_label = ", ".join([c.replace("Mensa ", "").upper() for c in occ["canteens"]])
            else:
                canteen_label = "-"

            table_rows.append([
                {"text": date_label, "align": "left"},
                {"text": meal_label, "align": "center"},
                {"text": canteen_label, "align": "left"}
            ])

        blocks.append({
            "type": "table",
            "cells": table_rows
        })

        if len(occurrences) > MAX_OCC:
            blocks.append({
                "type": "paragraph",
                "text": f"... altre {len(occurrences) - MAX_OCC} occorrenze future non mostrate."
            })

    blocks.append({
        "type": "buttons",
        "align": "center",
        "buttons": [
            {"text": "AGGIORNA", "callback_data": f"upd_rm|{safe_name}"}
        ]
    })

    fallback_text = get_dish_schedule(dish_name)
    fallback_markup = get_update_keyboard(dish_name)
    return blocks, fallback_text, fallback_markup

def _get_ephemeral_id(message):
    """Estrae l'ephemeral_message_id da un oggetto Message, cercando in api_kwargs se il campo non è mappato nativamente."""
    # 1. Campo nativo (versioni future della libreria)
    eph_id = getattr(message, "ephemeral_message_id", None)
    if eph_id:
        return eph_id
    # 2. Campo nei dati raw non mappati dalla libreria
    api_kw = getattr(message, "api_kwargs", {}) or {}
    eph_id = api_kw.get("ephemeral_message_id")
    if eph_id:
        return eph_id
    return None

async def safe_edit_message(bot, query, text: str = None, rich_blocks: list = None, reply_markup = None, parse_mode = ParseMode.MARKDOWN):
    """Modifica un messaggio supportando sia messaggi effimeri nei gruppi sia messaggi standard o inline."""
    is_group = bool(query.message and query.message.chat.type in ("group", "supergroup"))
    eph_id = _get_ephemeral_id(query.message) if query.message else None
    
    if rich_blocks is not None:
        if query.inline_message_id:
            rich_payload = {
                "inline_message_id": query.inline_message_id,
                "rich_message": {"blocks": rich_blocks}
            }
            await bot._post("editMessageText", data=rich_payload)
            return
        
        if is_group and eph_id:
            eph_payload = {
                "chat_id": query.message.chat_id,
                "receiver_user_id": query.from_user.id,
                "ephemeral_message_id": eph_id,
                "rich_message": {"blocks": rich_blocks}
            }
            try:
                await bot._post("editEphemeralMessageText", data=eph_payload)
                return
            except Exception as e:
                logger.info(f"editEphemeralMessageText fallito ({e}), provo editMessageText standard.")
        
        rich_payload = {
            "chat_id": query.message.chat_id,
            "message_id": query.message.message_id,
            "rich_message": {"blocks": rich_blocks}
        }
        await bot._post("editMessageText", data=rich_payload)
        return

    # Modifica testuale
    if query.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=query.inline_message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
        return

    if is_group and eph_id:
        try:
            payload = {
                "chat_id": query.message.chat_id,
                "receiver_user_id": query.from_user.id,
                "ephemeral_message_id": eph_id,
                "text": text,
                "parse_mode": "HTML" if parse_mode == ParseMode.HTML else "Markdown",
                "disable_web_page_preview": True
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup.to_dict() if hasattr(reply_markup, "to_dict") else reply_markup
            await bot._post("editEphemeralMessageText", data=payload)
            return
        except Exception as e:
            logger.info(f"editEphemeralMessageText testo fallito ({e}), provo editMessageText standard.")

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=True
    )

async def edit_dish_rich_message(query, bot, dish_name: str):
    """Aggiorna la programmazione del piatto in formato Rich Message con supporto messaggi effimeri e fallback."""
    blocks, fallback_text, fallback_markup = build_dish_rich_message(dish_name)
    try:
        await safe_edit_message(bot, query, rich_blocks=blocks)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        logger.warning(f"Rich dish edit fallito con BadRequest ({e}), provo fallback.")
        try:
            await safe_edit_message(bot, query, text=fallback_text, reply_markup=fallback_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Rich dish edit fallito ({e}), provo fallback.")
        try:
            await safe_edit_message(bot, query, text=fallback_text, reply_markup=fallback_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

# --- FUNZIONI PER ORARI MENSE ---
DAYS_REV = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]

def format_schedule_block(canteen_id, schedule_map):
    """Calcola la tabella orari formattata per ogni giorno della settimana tenendo conto delle festività."""
    tz = pytz.timezone('Europe/Rome')
    now = datetime.now(tz)
    today_idx = now.weekday()

    effective_schedule = {}
    for i in range(7):
        day_date = now.date() - timedelta(days=today_idx) + timedelta(days=i)
        status = get_holiday_status(canteen_id, day_date)
        orig_slots = schedule_map.get(str(i), [])

        if status == "closed":
            effective_schedule[str(i)] = []
        elif status == "lunch_only":
            effective_schedule[str(i)] = [s for s in orig_slots if int(s.split(":")[0]) < 16]
        elif status == "dinner_only":
            effective_schedule[str(i)] = [s for s in orig_slots if int(s.split(":")[0]) >= 16]
        else:
            effective_schedule[str(i)] = orig_slots.copy()

    lines = []
    for i in range(7):
        day_date = now.date() - timedelta(days=today_idx) + timedelta(days=i)
        day_name = DAYS_REV[i]

        day_status = get_holiday_status(canteen_id, day_date)
        if day_status == "closed":
            lines.append(f"{day_name:<3} Chiuso per festa")
            continue

        slots_str = effective_schedule.get(str(i), [])
        if not slots_str:
            lines.append(f"{day_name:<3} Chiuso")
            continue

        first_slot = True
        for slot in slots_str:
            if first_slot:
                lines.append(f"{day_name:<3} {slot}")
                first_slot = False
            else:
                lines.append(f"    {slot}")

    return "\n".join(lines) if lines else "    Chiuso"

def format_canteen_info(canteen):
    """Genera il testo HTML con le informazioni della mensa (stato, orari, ecc)."""
    tz = pytz.timezone('Europe/Rome')
    today_date = datetime.now(tz).date()
    
    c_name = canteen["name"]
    seats = canteen.get("seats", "N/D")
    
    message_lines = [f"<b>{c_name.upper()}</b>", ""]
    
    if "services" in canteen:
        services = ", ".join(canteen["services"])
        message_lines.append(f"<b>Servizi:</b> {services}")
        
    message_lines.append(f"<b>Capienza:</b> {seats} posti")
    message_lines.append("") # Spacer
    
    # Orari
    if "opening_hours" in canteen:
        oh = canteen["opening_hours"]
        # Iteriamo su tutti i tipi di orari (mensa, prendi_e_vai, ecc)
        for service_type, schedule_map in oh.items():
            schedule_block = format_schedule_block(canteen.get("id"), schedule_map)
            
            # Pretty service name
            svc_title = service_type.replace("_", " ").capitalize()
            if svc_title.lower() == "mensa":
                svc_title = "Mensa" # Just explicit
            
            message_lines.append(f"<b>{svc_title}</b>")
            message_lines.append(f"<pre>{schedule_block}</pre>")
            message_lines.append("")

    day_status = get_holiday_status(canteen.get("id"), today_date)
    if day_status != "closed":
        future_closure = get_future_closures_text(canteen.get("id"), today_date)
        if future_closure:
            message_lines.append(future_closure)
            message_lines.append("")

    return "\n".join(message_lines)

def get_info_keyboard(canteen):
    """Tastiera per sito web e google maps della mensa."""
    buttons = []
    row = []
    if "website" in canteen:
        row.append(InlineKeyboardButton("SITO WEB", url=canteen["website"]))
    lat = canteen.get("coordinates", {}).get("lat")
    lon = canteen.get("coordinates", {}).get("lon")
    if lat and lon:
        row.append(InlineKeyboardButton("GOOGLE MAPS", url=f"https://maps.google.com/?q={lat},{lon}"))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons) if buttons else None

def build_canteen_info_rich_message(canteen):
    """Costruisce il Rich Message (Bot API 10.3) con mappa in alto, tabelle orari mensa e prendi e vai, e bottoni sito/maps."""
    tz = pytz.timezone('Europe/Rome')
    now = datetime.now(tz)
    today_idx = now.weekday()
    today_date = now.date()
    
    c_name = canteen["name"]
    c_id = canteen.get("id")
    seats = canteen.get("seats", "N/D")
    lat = canteen.get("coordinates", {}).get("lat")
    lon = canteen.get("coordinates", {}).get("lon")
    website = canteen.get("website")
    maps_url = f"https://maps.google.com/?q={lat},{lon}" if (lat and lon) else None
    
    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": c_name.upper()
        }
    ]
    
    # 1. Mappa nativa con coordinate in alto
    if lat and lon:
        blocks.append({
            "type": "map",
            "location": {
                "latitude": float(lat),
                "longitude": float(lon)
            },
            "zoom": 16,
            "width": 640,
            "height": 360
        })

    # 2. Informazioni generali (solo Capienza e Servizi, senza stato)
    info_lines = []
    if "services" in canteen:
        services = ", ".join(canteen["services"])
        info_lines.append(f"Servizi: {services}")
    info_lines.append(f"Capienza: {seats} posti")
    
    blocks.append({
        "type": "paragraph",
        "text": "\n".join(info_lines)
    })
    
    # Avviso chiusura festività / futura se presente
    future_closure = get_future_closures_text(c_id, today_date)
    if future_closure:
        clean_closure = re.sub(r"<[^>]+>", "", future_closure).strip()
        if clean_closure:
            blocks.append({
                "type": "paragraph",
                "text": clean_closure
            })

    blocks.append({
        "type": "divider"
    })
    
    blocks.append({
        "type": "heading",
        "size": 2,
        "text": "ORARI MENSA"
    })
    
    # 3. Tabella degli orari della mensa
    table_rows = [
        [
            {"text": "GIORNO", "is_header": True, "align": "left"},
            {"text": "PRANZO", "is_header": True, "align": "center"},
            {"text": "CENA", "is_header": True, "align": "center"}
        ]
    ]
    
    mensa_sched = canteen.get("opening_hours", {}).get("mensa", {})
    for i in range(7):
        day_date = today_date - timedelta(days=today_idx) + timedelta(days=i)
        day_name = DAYS_REV[i]
        d_status = get_holiday_status(c_id, day_date)
        
        if d_status == "closed":
            pranzo_str = "Chiuso (festa)"
            cena_str = "Chiuso (festa)"
        else:
            orig_slots = mensa_sched.get(str(i), [])
            if d_status == "lunch_only":
                pranzo_slots = [s for s in orig_slots if int(s.split(":")[0]) < 16]
                cena_slots = []
            elif d_status == "dinner_only":
                pranzo_slots = []
                cena_slots = [s for s in orig_slots if int(s.split(":")[0]) >= 16]
            else:
                pranzo_slots = [s for s in orig_slots if int(s.split(":")[0]) < 16]
                cena_slots = [s for s in orig_slots if int(s.split(":")[0]) >= 16]
                
            pranzo_str = ", ".join(pranzo_slots) if pranzo_slots else "Chiuso"
            cena_str = ", ".join(cena_slots) if cena_slots else "Chiuso"
            
        table_rows.append([
            {"text": day_name, "align": "left"},
            {"text": pranzo_str, "align": "center"},
            {"text": cena_str, "align": "center"}
        ])
        
    blocks.append({
        "type": "table",
        "cells": table_rows
    })
    
    # 4. Tabella orari Prendi e vai se presente
    pv_sched = canteen.get("opening_hours", {}).get("prendi_e_vai", {})
    if pv_sched and any(pv_sched.get(str(i)) for i in range(7)):
        blocks.append({
            "type": "divider"
        })
        blocks.append({
            "type": "heading",
            "size": 2,
            "text": "ORARI PRENDI E VAI"
        })
        pv_rows = [
            [
                {"text": "GIORNO", "is_header": True, "align": "left"},
                {"text": "ORARIO", "is_header": True, "align": "center"}
            ]
        ]
        for i in range(7):
            day_date = today_date - timedelta(days=today_idx) + timedelta(days=i)
            day_name = DAYS_REV[i]
            d_status = get_holiday_status(c_id, day_date)
            if d_status == "closed":
                s_str = "Chiuso (festa)"
            else:
                slots = pv_sched.get(str(i), [])
                s_str = ", ".join(slots) if slots else "Chiuso"
            pv_rows.append([
                {"text": day_name, "align": "left"},
                {"text": s_str, "align": "center"}
            ])
        blocks.append({
            "type": "table",
            "cells": pv_rows
        })
            
    # 5. Pulsanti per Sito Web e Google Maps (nessun bottone aggiorna, nessun link diretto nel testo)
    buttons_row = []
    if website:
        buttons_row.append({"text": "SITO WEB", "url": website})
    if maps_url:
        buttons_row.append({"text": "GOOGLE MAPS", "url": maps_url})
        
    if buttons_row:
        blocks.append({
            "type": "buttons",
            "align": "center",
            "buttons": buttons_row
        })

    fallback_text = format_canteen_info(canteen)
    fallback_markup = get_info_keyboard(canteen)
    return blocks, fallback_text, fallback_markup

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

def build_all_rates_rich_message():
    """Costruisce la tabella completa di tutte le tariffe ISEE in formato Rich Message (Bot API 10.3)."""
    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": "TABELLA TARIFFE ISEE"
        },
        {
            "type": "paragraph",
            "text": "Tariffe agevolate del servizio ristorazione DSU Toscana per fascia ISEE:"
        }
    ]

    header_row = [
        {"text": "FASCIA ISEE", "is_header": True, "align": "left"},
        {"text": "COMPLETO", "is_header": True, "align": "center"},
        {"text": "RID. A", "is_header": True, "align": "center"},
        {"text": "RID. B", "is_header": True, "align": "center"},
        {"text": "RID. C", "is_header": True, "align": "center"}
    ]

    table_rows = [header_row]
    for r in RATES:
        if r.get("scholarship"):
            label = "Borsisti ARDSU"
        else:
            orig = r.get("original_label", "")
            label = orig.replace("≤ € ", "≤ ").replace("> € ", "> ").replace(" ≤ € ", " - ")
        
        comp_v = r.get("pasto_completo", 0)
        ra_v = r.get("pasto_ridotto_a", 0)
        rb_v = r.get("pasto_ridotto_b", 0)
        rc_v = r.get("pasto_ridotto_c", 0)

        comp = "Gratis" if comp_v == 0 else f"€ {comp_v:.2f}"
        ra = "Gratis" if ra_v == 0 else f"€ {ra_v:.2f}"
        rb = "Gratis" if rb_v == 0 else f"€ {rb_v:.2f}"
        rc = "Gratis" if rc_v == 0 else f"€ {rc_v:.2f}"

        table_rows.append([
            {"text": label, "align": "left"},
            {"text": comp, "align": "center"},
            {"text": ra, "align": "center"},
            {"text": rb, "align": "center"},
            {"text": rc, "align": "center"}
        ])

    blocks.append({
        "type": "table",
        "cells": table_rows
    })

    blocks.append({
        "type": "divider"
    })

    blocks.append({
        "type": "heading",
        "size": 2,
        "text": "LEGENDA PASTI"
    })

    blocks.append({
        "type": "paragraph",
        "text": (
            "• Pasto Completo: 1 primo, 1 secondo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto A: 1 primo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto B: 1 secondo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto C: 1 primo o 1 secondo o 2 contorni, 1 frutto o dessert, pane e bevanda"
        )
    })

    blocks.append({
        "type": "divider"
    })

    blocks.append({
        "type": "paragraph",
        "text": [
            "Per il regolamento completo visita il sito ",
            {"type": "url", "text": "DSU Toscana", "url": "https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee"},
            "."
        ]
    })

    fallback_text = (
        "*TABELLA TARIFFE ISEE DSU TOSCANA*\n\n"
        "Verifica le agevolazioni e i dettagli direttamente sul sito di DSU: https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee"
    )
    fallback_markup = None
    return blocks, fallback_text, fallback_markup

def build_rate_rich_message(band, isee_val=None):
    """Costruisce il Rich Message con tabella per una specifica fascia ISEE (Bot API 10.3)."""
    orig_label = band.get("original_label", "")
    if band.get("scholarship"):
        heading_title = "TARIFFE IDONEI BORSA ARDSU"
    else:
        heading_title = f"TARIFFE FASCIA {orig_label.upper()}"

    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": heading_title
        }
    ]

    if isee_val is not None and not band.get("scholarship"):
        blocks.append({
            "type": "paragraph",
            "text": f"Valore ISEE: € {isee_val:,.2f}"
        })

    items_ord = [
        ("pasto_completo", "Pasto Completo"),
        ("pasto_ridotto_a", "Pasto Ridotto A"),
        ("pasto_ridotto_b", "Pasto Ridotto B"),
        ("pasto_ridotto_c", "Pasto Ridotto C")
    ]

    table_rows = [
        [
            {"text": "TIPO DI PASTO", "is_header": True, "align": "left"},
            {"text": "PREZZO", "is_header": True, "align": "center"}
        ]
    ]

    for key, label in items_ord:
        price = band.get(key)
        if price is not None:
            price_str = "Gratuito" if price == 0 else f"€ {price:.2f}"
        else:
            price_str = "N/A"

        table_rows.append([
            {"text": label, "align": "left"},
            {"text": price_str, "align": "center"}
        ])

    blocks.append({
        "type": "table",
        "cells": table_rows
    })

    blocks.append({
        "type": "divider"
    })

    blocks.append({
        "type": "heading",
        "size": 2,
        "text": "COMPOSIZIONE DEI PASTI"
    })

    blocks.append({
        "type": "paragraph",
        "text": (
            "• Pasto Completo: 1 primo, 1 secondo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto A: 1 primo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto B: 1 secondo, 1 contorno, 1 frutto o dessert, pane e bevanda\n"
            "• Pasto Ridotto C: 1 primo o 1 secondo o 2 contorni, 1 frutto o dessert, pane e bevanda"
        )
    })

    blocks.append({
        "type": "divider"
    })

    blocks.append({
        "type": "paragraph",
        "text": [
            "Per dettagli e informazioni visita ",
            {"type": "url", "text": "DSU Toscana", "url": "https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee"},
            "."
        ]
    })

    fallback_text = get_rate_message_text(band)
    fallback_markup = None
    return blocks, fallback_text, fallback_markup


class CustomInputRichMessageContent:
    """Rappresenta InputRichMessageContent per Telegram Bot API 10.3 nei risultati inline."""
    def __init__(self, blocks):
        self.blocks = blocks

    def to_dict(self, recursive=True):
        return {
            "rich_message": {
                "blocks": self.blocks
            }
        }


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce le ricerche inline dei piatti."""
    query = update.inline_query.query
    results = []

    # Se la query è vuota, mostra il menu di ogni mensa in formato Rich Message (API 10.3)
    if not query:
        tz = pytz.timezone('Europe/Rome')
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        meal_type = "Cena" if now.time() >= time(15, 0) else "Pranzo"
        
        # --- VOCE TUTTE (Rich Message) ---
        blocks_all, _, _ = build_canteen_rich_message("all", today, meal_type)
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="TUTTE",
                description="Visualizza il menù di tutte le mense oggi...",
                thumbnail_url=get_asset_url("icons/tutte.png"),
                input_message_content=CustomInputRichMessageContent(blocks_all)
            )
        )
        
        # Ordiniamo le mense alfabeticamente
        sorted_canteens = sorted(CANTEENS.items(), key=lambda x: x[1])
        
        for c_id, c_name in sorted_canteens:
            clean_name = c_name.upper()
            blocks_canteen, _, _ = build_canteen_rich_message(c_id, today, meal_type)
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=clean_name,
                    description="Visualizza il menù di oggi...",
                    thumbnail_url=get_asset_url("icons/mensa.png"), 
                    input_message_content=CustomInputRichMessageContent(blocks_canteen)
                )
            )

        # --- SUGGERIMENTI E ISTRUZIONI DI UTILIZZO IN FORMATO RICH MESSAGE (API 10.3) ---
        instructions = [
            {
                "id": "inst_p",
                "title": "Cerca Piatto",
                "desc": "p:<piatto> (es. p:Arista)",
                "blocks": [
                    {"type": "heading", "size": 1, "text": "CERCA PIATTO"},
                    {
                        "type": "paragraph",
                        "text": "Vuoi sapere in quale mensa e in quali giorni sarà servito un piatto specifico?\nDigita nella chat:\n@cibounipibot p:nome_piatto\n\nEsempio: @cibounipibot p:Arista\n\nIl bot cercherà nei menù di tutte le mense!"
                    },
                    {
                        "type": "buttons",
                        "align": "center",
                        "buttons": [
                            {"text": "PROVA SUBITO", "switch_inline_query_current_chat": "p:"}
                        ]
                    }
                ],
                "thumb": get_asset_url("icons/info.png")
            },
            {
                "id": "inst_i",
                "title": "Informazioni Mense",
                "desc": "i:<mensa> (es. i:Martiri)",
                "blocks": [
                    {"type": "heading", "size": 1, "text": "INFORMAZIONI E ORARI MENSE"},
                    {
                        "type": "paragraph",
                        "text": "Vuoi sapere se una mensa è aperta adesso o quali sono i suoi orari?\nDigita nella chat:\n@cibounipibot i:nome_mensa\n\nEsempio: @cibounipibot i:Martiri\n\nOppure digita solo @cibounipibot i: per visualizzare l'elenco completo di tutte le mense!"
                    },
                    {
                        "type": "buttons",
                        "align": "center",
                        "buttons": [
                            {"text": "PROVA SUBITO", "switch_inline_query_current_chat": "i:"}
                        ]
                    }
                ],
                "thumb": get_asset_url("icons/info.png")
            },
            {
                "id": "inst_t",
                "title": "Tariffe & ISEE",
                "desc": "t: <isee> (es. t:21065)",
                "blocks": [
                    {"type": "heading", "size": 1, "text": "CALCOLO TARIFFE ISEE"},
                    {
                        "type": "paragraph",
                        "text": "Vuoi sapere esattamente quanto paghi a pasto in base al tuo ISEE?\nDigita nella chat:\n@cibounipibot t:tuo_valore_isee\n\nEsempi:\n• @cibounipibot t:15500\n• @cibounipibot t:borsa (se borsista DSU)\n\nOppure digita solo @cibounipibot t: per visualizzare la tabella riassuntiva di tutte le fasce di costo."
                    },
                    {
                        "type": "buttons",
                        "align": "center",
                        "buttons": [
                            {"text": "PROVA SUBITO", "switch_inline_query_current_chat": "t:"}
                        ]
                    }
                ],
                "thumb": get_asset_url("icons/info.png")
            }
        ]

        for inst in instructions:
            results.append(
                InlineQueryResultArticle(
                    id=inst["id"],
                    title=inst["title"],
                    description=inst["desc"],
                    input_message_content=CustomInputRichMessageContent(inst["blocks"]),
                    thumbnail_url=inst["thumb"],
                    thumbnail_width=48, 
                    thumbnail_height=48
                )
            )
            
        # --- AGGIUNTA VOCE INSTAGRAM in FONDO (Rich Message) ---
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="Seguici su Instagram",
                description="Ora puoi scoprire il menù anche tramite il nostro profilo Instagram.",
                thumbnail_url=get_asset_url("icons/instagram.png"),
                input_message_content=CustomInputRichMessageContent([
                    {"type": "heading", "size": 1, "text": "SEGUICI SU INSTAGRAM"},
                    {"type": "paragraph", "text": "Scopri i menù del giorno illustrati nelle storie e nei post del nostro profilo e non scordarti di seguirci per rimanere sempre aggiornato!"},
                    {
                        "type": "buttons",
                        "align": "center",
                        "buttons": [
                            {"text": "APRI INSTAGRAM", "url": "https://instagram.com/cibounipibot"}
                        ]
                    }
                ])
            )
        )

        # --- AGGIUNTA VOCE GITHUB in FONDO (Rich Message) ---
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="Repository GitHub",
                description="Mettici una stella!",
                thumbnail_url=get_asset_url("icons/github.png"),
                input_message_content=CustomInputRichMessageContent([
                    {"type": "heading", "size": 1, "text": "REPOSITORY GITHUB"},
                    {"type": "paragraph", "text": "Il bot è open source! Visita la repository ufficiale su GitHub per vedere il codice sorgente o lasciare una stella al progetto."},
                    {
                        "type": "buttons",
                        "align": "center",
                        "buttons": [
                            {"text": "APRI REPOSITORY", "url": "https://github.com/plumkewe/mense-unipi-bot"}
                        ]
                    }
                ])
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
                
                blocks, _, _ = build_canteen_info_rich_message(canteen)

                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title=f"{c_name} (Informazioni)",
                        description=f"Capienza: {seats} posti",
                        thumbnail_url=get_asset_url("icons/mensa.png"), 
                        input_message_content=CustomInputRichMessageContent(blocks)
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
        
        # Caso 1: Solo "t:" -> Mostra tabella generale in formato Rich Message (API 10.3)
        if not search_term:
            blocks_all_rates, _, _ = build_all_rates_rich_message()
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="TABELLA TARIFFE ISEE",
                    description="Visualizza la tabella riassuntiva di tutte le fasce ISEE...",
                    thumbnail_url=get_asset_url("icons/table.png"),
                    input_message_content=CustomInputRichMessageContent(blocks_all_rates)
                )
            )
            await update.inline_query.answer(results, cache_time=0)
            return
            
        # Caso 2: t:<isee> -> Calcola tariffe specifiche con tabella Rich Message (anche per borsa di studio)
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
                blocks_rate, _, _ = build_rate_rich_message(band, isee_val)
                
                items_ord = [
                    ("pasto_completo", "PASTO COMPLETO"),
                    ("pasto_ridotto_a", "PASTO RIDOTTO A"),
                    ("pasto_ridotto_b", "PASTO RIDOTTO B"),
                    ("pasto_ridotto_c", "PASTO RIDOTTO C")
                ]
                thumb_money = get_asset_url("icons/money.png")
                
                # Ognuno invierà il Rich Message con la tabella
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

                    display_title = label.replace("_", " ").title()
                    
                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=display_title,
                            description=price_text,
                            thumbnail_url=thumb_money,
                            input_message_content=CustomInputRichMessageContent(blocks_rate)
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

    results = []

    today = datetime.now(pytz.timezone('Europe/Rome')).date()
    
    # Ordina le date del menu
    sorted_dates = sorted(MENU.keys())
    
    seen_dishes = set()
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
                             
                             if clean_dish_name in seen_dishes:
                                 continue
                             seen_dishes.add(clean_dish_name)
                             
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
                             
                             # Immagine con il numero di giorni
                             thumb_url = get_asset_url(f"numbers/{days_diff}.png")
                             
                             # ID Univoco per il risultato
                             result_id = str(uuid4())
                             
                             # Costruisci il Rich Message con la tabella di programmazione
                             dish_blocks, _, _ = build_dish_rich_message(clean_dish_name)

                             results.append(
                                 InlineQueryResultArticle(
                                     id=result_id,
                                     title=clean_dish_name,
                                     description=description_text,
                                     thumbnail_url=thumb_url,
                                     input_message_content=CustomInputRichMessageContent(dish_blocks)
                                 )
                             )
                             count += 1
    
    button = None
    if not results:
        button = InlineQueryResultsButton(text="Piatto che non servono!", start_parameter="help")
    await update.inline_query.answer(results, cache_time=5, button=button)

def build_welcome_rich_message(is_group: bool = False):
    """Costruisce il Rich Message di benvenuto senza emoji, con comandi e funzioni inline in collapse e bottone Instagram."""
    if is_group:
        intro_text = "Per consultare i menù e le informazioni utilizza i comandi e le funzioni inline del bot."
    else:
        intro_text = "Per vedere il menù di oggi non ti basta che cliccare su uno dei bottoni presenti in basso."

    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": "CIBOUNIPI BOT"
        },
        {
            "type": "paragraph",
            "text": intro_text
        }
    ]

    # Mostriamo i comandi sia in privato che in gruppo (nei gruppi sono effimeri)
    if is_group:
        commands_text = (
            "• /start - Messaggio di benvenuto\n"
            "• /menu - Menù di oggi\n"
            "• /links - Link utili DSU e contatti\n\n"
            "I comandi nei gruppi sono visibili solo a te."
        )
    else:
        commands_text = (
            "• /start - Messaggio di benvenuto\n"
            "• /menu - Menù di oggi\n"
            "• /links - Link utili DSU e contatti"
        )
    blocks.append({
        "type": "details",
        "summary": "Comandi disponibili",
        "blocks": [
            {
                "type": "paragraph",
                "text": commands_text
            }
        ]
    })

    blocks.append({
        "type": "details",
        "summary": "Funzioni inline",
        "blocks": [
            {
                "type": "paragraph",
                "text": (
                    "• Ricerca piatto: @cibounipibot p:nome piatto\n"
                    "• Menu di oggi: @cibounipibot in chat\n"
                    "• Info e orari: @cibounipibot i:\n"
                    "• Tariffe ISEE: @cibounipibot t:"
                )
            }
        ]
    })

    blocks.append({
        "type": "buttons",
        "align": "center",
        "buttons": [
            {
                "text": "SEGUICI SU INSTAGRAM",
                "url": "https://instagram.com/cibounipibot"
            }
        ]
    })

    if is_group:
        fallback_text = (
            "*CIBOUNIPI BOT*\n\n"
            "Per consultare i menù e le informazioni utilizza i comandi e le funzioni inline del bot.\n\n"
            "> *Comandi disponibili*\n"
            "> • /start - Messaggio di benvenuto\n"
            "> • /menu - Menù di oggi\n"
            "> • /links - Link utili DSU e contatti\n"
            "> I comandi nei gruppi sono visibili solo a te.\n\n"
            "> *Funzioni inline*\n"
            "> • Ricerca piatto: `@cibounipibot p:nome`\n"
            "> • Menu di oggi: `@cibounipibot` in chat\n"
            "> • Info e orari: `@cibounipibot i:`\n"
            "> • Tariffe ISEE: `@cibounipibot t:`"
        )
    else:
        fallback_text = (
            "*CIBOUNIPI BOT*\n\n"
            "Per vedere il menù di oggi non ti basta che cliccare su uno dei bottoni presenti in basso.\n\n"
            "> *Comandi disponibili*\n"
            "> • /start - Messaggio di benvenuto\n"
            "> • /menu - Menù di oggi\n"
            "> • /links - Link utili DSU e contatti\n\n"
            "> *Funzioni inline*\n"
            "> • Ricerca piatto: `@cibounipibot p:nome`\n"
            "> • Menu di oggi: `@cibounipibot` in chat\n"
            "> • Info e orari: `@cibounipibot i:`\n"
            "> • Tariffe ISEE: `@cibounipibot t:`"
        )
    fallback_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("SEGUICI SU INSTAGRAM", url="https://instagram.com/cibounipibot")]
    ])
    return blocks, fallback_text, fallback_markup

async def send_welcome_rich_message(bot, chat_id: int, user_id: int = None, is_group: bool = False):
    """Invia il messaggio di benvenuto come Rich Message (effimero se in gruppo) con fallback standard."""
    blocks, fallback_text, fallback_markup = build_welcome_rich_message(is_group=is_group)
    rich_payload = {
        "chat_id": chat_id,
        "rich_message": {
            "blocks": blocks
        }
    }
    if user_id:
        rich_payload["ephemeral_message_parameters"] = {
            "receiver_user_id": user_id
        }
    try:
        await bot._post("sendRichMessage", data=rich_payload)
    except Exception as e:
        logger.warning(f"Rich welcome message fallito ({e}), invio fallback standard.")
        send_kwargs = {}
        if user_id:
            send_kwargs["api_kwargs"] = {
                "ephemeral_message_parameters": {
                    "receiver_user_id": user_id
                }
            }
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=fallback_text,
                reply_markup=fallback_markup,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                **send_kwargs
            )
        except Exception as e2:
            if is_group and user_id:
                # Non inviare messaggio pubblico nel gruppo: il bot probabilmente non è admin
                logger.warning(f"Fallback welcome effimero fallito ({e2}), messaggio non inviato nel gruppo.")
            else:
                raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /start (effimero e senza bottoni mense se evocato in gruppo)."""
    chat = update.effective_chat
    user = update.effective_user
    is_private = chat.type == "private"
    is_group = chat.type in ("group", "supergroup")
    user_id = user.id if (user and is_group) else None

    # In chat privata: mostra lo sticker con la tastiera persistente dei bottoni mense
    if is_private:
        try:
            await update.message.reply_sticker(
                "CAACAgQAAxkBAAIpKGqiv6MPsEBXcmawt0aBHsU3PrmSAAJwHwACOxwRUYGOMtqXij1vPQQ",
                reply_markup=get_canteen_reply_keyboard()
            )
        except Exception as e:
            logger.warning(f"Invio sticker fallito: {e}")

    # Invia il Rich Message di benvenuto (effimero per l'utente se in gruppo, senza bottoni mense)
    await send_welcome_rich_message(context.bot, chat.id, user_id=user_id, is_group=is_group)

def build_menu_selection_rich_message():
    """Costruisce il Rich Message per la selezione mensa del comando /menu con tabella di apertura e bottoni."""
    sorted_canteens = sorted(CANTEENS.items(), key=lambda x: x[1])

    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": "SELEZIONA UNA MENSA"
        },
        {
            "type": "paragraph",
            "text": "Scegli la mensa per visualizzare il menù di oggi:"
        }
    ]

    tz = pytz.timezone('Europe/Rome')
    today_date = datetime.now(tz).date()

    table_cells = [
        [
            {"text": "MENSA", "is_header": True, "align": "left"},
            {"text": "PRANZO", "is_header": True, "align": "center"},
            {"text": "CENA", "is_header": True, "align": "center"}
        ]
    ]
    for c_id, c_name in sorted_canteens:
        clean_name = c_name.replace("Mensa ", "")
        has_l, has_d = get_canteen_meal_availability(c_id, today_date)
        table_cells.append([
            {"text": clean_name, "align": "left"},
            {"text": "Aperta" if has_l else "Chiusa", "align": "center"},
            {"text": "Aperta" if has_d else "Chiusa", "align": "center"}
        ])

    blocks.append({
        "type": "table",
        "cells": table_cells
    })

    # Bottone TUTTE e bottoni mense
    canteen_buttons = [{"text": "TUTTE", "callback_data": "sel_canteen|all"}]
    for c_id, c_name in sorted_canteens:
        clean_name = c_name.replace("Mensa ", "").upper()
        canteen_buttons.append({"text": clean_name, "callback_data": f"sel_canteen|{c_id}"})

    blocks.append({
        "type": "buttons",
        "align": "center",
        "buttons": canteen_buttons
    })

    fallback_lines = ["*STATO MENSE OGGI*", ""]
    for c_id, c_name in sorted_canteens:
        clean_name = c_name.replace("Mensa ", "")
        has_l, has_d = get_canteen_meal_availability(c_id, today_date)
        l_str = "Aperta" if has_l else "Chiusa"
        d_str = "Aperta" if has_d else "Chiusa"
        fallback_lines.append(f"• *{clean_name}*: Pranzo {l_str} | Cena {d_str}")
    fallback_lines.append("\n*Seleziona una mensa per vedere il menù:*")
    fallback_text = "\n".join(fallback_lines)
    fallback_markup = get_canteen_selection_keyboard()
    return blocks, fallback_text, fallback_markup

async def send_menu_selection_rich_message(bot, chat_id: int, user_id: int = None, is_group: bool = False):
    """Invia la selezione mensa come Rich Message (effimero se in gruppo) con fallback standard."""
    blocks, fallback_text, fallback_markup = build_menu_selection_rich_message()
    rich_payload = {
        "chat_id": chat_id,
        "rich_message": {
            "blocks": blocks
        }
    }
    if user_id:
        rich_payload["ephemeral_message_parameters"] = {
            "receiver_user_id": user_id
        }
    try:
        await bot._post("sendRichMessage", data=rich_payload)
    except Exception as e:
        logger.warning(f"Rich menu selection fallito ({e}), invio fallback standard.")
        send_kwargs = {}
        if user_id:
            send_kwargs["api_kwargs"] = {
                "ephemeral_message_parameters": {
                    "receiver_user_id": user_id
                }
            }
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=fallback_text,
                reply_markup=fallback_markup,
                parse_mode=ParseMode.MARKDOWN,
                **send_kwargs
            )
        except Exception as e2:
            if is_group and user_id:
                logger.warning(f"Fallback menu selection effimero fallito ({e2}), messaggio non inviato nel gruppo.")
            else:
                raise

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /menu. Mostra la selezione mensa come Rich Message (effimero se in gruppo)."""
    chat = update.effective_chat
    user = update.effective_user
    is_group = chat.type in ("group", "supergroup")
    user_id = user.id if (user and is_group) else None
    await send_menu_selection_rich_message(context.bot, chat.id, user_id=user_id, is_group=is_group)

def build_links_rich_message():
    """Costruisce il Rich Message per il comando /links diviso tra i nostri canali e i canali DSU."""
    blocks = [
        {
            "type": "heading",
            "size": 1,
            "text": "LINK UTILI"
        },
        {
            "type": "heading",
            "size": 2,
            "text": "I NOSTRI CANALI"
        },
        {
            "type": "paragraph",
            "text": [
                "• ", {"type": "url", "text": "Assistenza Telegram: @doveunipi", "url": "https://t.me/doveunipi"}, "\n",
                "• ", {"type": "url", "text": "Instagram: @cibounipibot", "url": "https://instagram.com/cibounipibot"}, "\n",
                "• ", {"type": "url", "text": "Canale aggiornamenti: @mensedsu", "url": "https://t.me/mensedsu"}
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "heading",
            "size": 2,
            "text": "CANALI DSU TOSCANA"
        },
        {
            "type": "paragraph",
            "text": [
                "• ", {"type": "url", "text": "Sito DSU Toscana", "url": "https://www.dsu.toscana.it"}, "\n",
                "• ", {"type": "url", "text": "Sportello Studente", "url": "https://sportellostudente.dsu.toscana.it/"}, "\n",
                "• ", {"type": "url", "text": "Instagram DSU", "url": "https://www.instagram.com/dsutoscana/"}, "\n",
                "• ", {"type": "url", "text": "Facebook DSU", "url": "https://www.facebook.com/dsutoscana"}, "\n",
                "• ", {"type": "url", "text": "Canale WhatsApp DSU", "url": "https://www.whatsapp.com/channel/0029Vb5mhtEKrWQsuxlBw73k"}, "\n",
                "• ", {"type": "url", "text": "Canale Telegram DSU", "url": "https://t.me/DSUToscana"}
            ]
        }
    ]

    fallback_text = (
        "*LINK UTILI*\n\n"
        "*I NOSTRI CANALI*\n"
        "• [Assistenza Telegram: @doveunipi](https://t.me/doveunipi)\n"
        "• [Instagram: @cibounipibot](https://instagram.com/cibounipibot)\n"
        "• [Canale aggiornamenti](https://t.me/mensedsu)\n\n"
        "*CANALI DSU TOSCANA*\n"
        "• [Sito DSU Toscana](https://www.dsu.toscana.it)\n"
        "• [Sportello Studente](https://sportellostudente.dsu.toscana.it/)\n"
        "• [Instagram DSU](https://www.instagram.com/dsutoscana/)\n"
        "• [Facebook DSU](https://www.facebook.com/dsutoscana)\n"
        "• [Canale WhatsApp DSU](https://www.whatsapp.com/channel/0029Vb5mhtEKrWQsuxlBw73k)\n"
        "• [Canale Telegram DSU](https://t.me/DSUToscana)"
    )
    fallback_markup = None
    return blocks, fallback_text, fallback_markup

async def send_links_rich_message(bot, chat_id: int, user_id: int = None, is_group: bool = False):
    """Invia il comando /links come Rich Message (effimero se in gruppo) con fallback standard."""
    blocks, fallback_text, fallback_markup = build_links_rich_message()
    rich_payload = {
        "chat_id": chat_id,
        "rich_message": {
            "blocks": blocks
        }
    }
    if user_id:
        rich_payload["ephemeral_message_parameters"] = {
            "receiver_user_id": user_id
        }
    try:
        await bot._post("sendRichMessage", data=rich_payload)
    except Exception as e:
        logger.warning(f"Rich links message fallito ({e}), invio fallback standard.")
        send_kwargs = {}
        if user_id:
            send_kwargs["api_kwargs"] = {
                "ephemeral_message_parameters": {
                    "receiver_user_id": user_id
                }
            }
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=fallback_text,
                reply_markup=fallback_markup,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                **send_kwargs
            )
        except Exception as e2:
            if is_group and user_id:
                logger.warning(f"Fallback links effimero fallito ({e2}), messaggio non inviato nel gruppo.")
            else:
                raise

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /links. Mostra link utili come Rich Message (effimero se in gruppo)."""
    chat = update.effective_chat
    user = update.effective_user
    is_group = chat.type in ("group", "supergroup")
    user_id = user.id if (user and is_group) else None
    await send_links_rich_message(context.bot, chat.id, user_id=user_id, is_group=is_group)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i cl sui bottoni inline."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass 

    data = query.data.split("|")
    action = data[0]

    if action == "rm":
        # Data format: rm|canteen_id|date_str|meal_type
        canteen_id = data[1]
        date_str = data[2]
        meal_type = data[3]
        await edit_canteen_rich_message(query, context.bot, canteen_id, date_str, meal_type)
        return

    if action == "sel_canteen":
        # Data format: sel_canteen|canteen_id
        canteen_id = data[1]
        
        if canteen_id == "reset":
            blocks, fallback_text, fallback_markup = build_menu_selection_rich_message()
            
            # Se il messaggio originale contiene "CIBOUNIPI BOT", è il messaggio di start
            # In questo caso mandiamo un NUOVO messaggio.
            # Altrimenti (siamo già nel flusso menu), modifichiamo il messaggio esistente.
            msg_text = query.message.text or ""
            if "CIBOUNIPI BOT" in msg_text:
                chat = query.message.chat
                is_group = chat.type in ("group", "supergroup")
                rich_payload = {
                    "chat_id": query.message.chat_id,
                    "rich_message": {"blocks": blocks}
                }
                if is_group:
                    rich_payload["ephemeral_message_parameters"] = {
                        "receiver_user_id": query.from_user.id
                    }
                try:
                    await context.bot._post("sendRichMessage", data=rich_payload)
                except Exception:
                    send_kwargs = {}
                    if is_group:
                        send_kwargs["api_kwargs"] = {
                            "ephemeral_message_parameters": {
                                "receiver_user_id": query.from_user.id
                            }
                        }
                    await context.bot.send_message(chat_id=query.message.chat_id, text=fallback_text, reply_markup=fallback_markup, parse_mode=ParseMode.MARKDOWN, **send_kwargs)
            else:
                try:
                    await safe_edit_message(context.bot, query, rich_blocks=blocks)
                except Exception:
                    await safe_edit_message(context.bot, query, text=fallback_text, reply_markup=fallback_markup, parse_mode=ParseMode.MARKDOWN)
            return
            
        # Selezionata una mensa, mostra il menù di oggi come Rich Message
        tz = pytz.timezone('Europe/Rome')
        now = datetime.now(tz)
        current_date = now.strftime("%Y-%m-%d")
        meal_type = "Cena" if now.time() >= time(15, 0) else "Pranzo"
        await edit_canteen_rich_message(query, context.bot, canteen_id, current_date, meal_type)
        return

    if action in ("upd", "upd_rm"):
        dish_name = data[1]
        await edit_dish_rich_message(query, context.bot, dish_name)
        return

def get_canteen_reply_keyboard():
    """Tastiera persistente con i bottoni per ogni mensa (MARTIRI, BETTI, CAMMEO)."""
    buttons = []
    row = []
    sorted_canteens = sorted(CANTEENS.items(), key=lambda x: x[1])
    for c_id, c_name in sorted_canteens:
        clean = c_name.replace("Mensa ", "").upper()
        row.append(KeyboardButton(clean))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, is_persistent=True)

def build_canteen_rich_message(canteen_id: str, date_str: str, meal_type: str):
    """Costruisce la struttura per Telegram Bot API 10.3 (Rich Message con bottoni integrati) e i fallback."""
    is_all = (canteen_id == "all")
    if is_all:
        canteen_name = "TUTTE"
        header_title = "TUTTE LE MENSE"
    else:
        canteen_name = CANTEENS.get(canteen_id, canteen_id.capitalize())
        clean_canteen = canteen_name.replace("Mensa ", "").upper()
        header_title = f"MENSA {clean_canteen}"

    meal_type_clean = meal_type.capitalize()
    
    # Formattazione data leggibile
    date_pretty = date_str
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_pretty = format_date_it(dt)
    except Exception:
        pass

    # Calcolo stato ferie/festività
    is_closed = False
    if not is_all:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            holiday_status = get_holiday_status(canteen_id, date_obj)
            if holiday_status == "closed":
                is_closed = True
            elif holiday_status == "lunch_only" and meal_type_clean.lower() == "cena":
                is_closed = True
            elif holiday_status == "dinner_only" and meal_type_clean.lower() == "pranzo":
                is_closed = True
        except Exception:
            pass

    blocks = []
    # 1. Intestazione (Heading) - Nessuna emoji
    blocks.append({
        "type": "heading",
        "size": 1,
        "text": header_title
    })
    
    # 2. Informazioni data e pasto - Nessuna emoji
    blocks.append({
        "type": "paragraph",
        "text": f"{date_pretty} • {meal_type_clean.upper()}"
    })
    
    # 3. Separatore
    blocks.append({
        "type": "divider"
    })

    # 4. Contenuto menù
    day_menu = MENU.get(date_str)
    meal_menu = day_menu.get(meal_type_clean) if day_menu else None

    if is_closed:
        blocks.append({
            "type": "paragraph",
            "text": "Mensa chiusa per ferie o festività in questo pasto."
        })
    elif not day_menu or not meal_menu:
        blocks.append({
            "type": "paragraph",
            "text": "Nessun piatto disponibile per questa data."
        })
    else:
        has_any_dish = False
        cat_order = ["Salati", "Primi Piatti", "Secondi Piatti", "Contorni", "Insalatone"]
        all_cats = cat_order + [c for c in meal_menu.keys() if c not in cat_order]
        
        for cat in all_cats:
            dishes = meal_menu.get(cat, [])
            if not dishes:
                continue
            filtered = []
            for d in dishes:
                if isinstance(d, dict):
                    avail = d.get("available_at", [])
                    if is_all or not avail or canteen_name in avail:
                        filtered.append(d)
                else:
                    filtered.append(d)
            
            if filtered:
                has_any_dish = True
                clean_cat = cat.upper().replace(" PIATTI", "")
                blocks.append({
                    "type": "heading",
                    "size": 2,
                    "text": clean_cat
                })
                dish_elements = []
                for i, d in enumerate(filtered):
                    if i > 0:
                        dish_elements.append("\n")
                    dish_elements.append("• ")
                    if isinstance(d, dict):
                        d_name = d.get("name", "").strip().capitalize()
                        if is_all:
                            avail = d.get("available_at", [])
                            if avail and len(avail) < len(CANTEENS):
                                short = [c.replace("Mensa ", "") for c in avail]
                                d_name += f" (Solo {', '.join(short)})"
                        d_link = d.get("link")
                        if d_link:
                            dish_elements.append({
                                "type": "url",
                                "text": d_name,
                                "url": d_link
                            })
                        else:
                            dish_elements.append(d_name)
                    else:
                        dish_elements.append(d.strip().capitalize())
                blocks.append({
                    "type": "paragraph",
                    "text": dish_elements
                })

        if not has_any_dish:
            blocks.append({
                "type": "paragraph",
                "text": "Nessun piatto disponibile per questa mensa." if not is_all else "Nessun piatto disponibile per questa data."
            })

    # 5. Bottoni integrati nel messaggio ricco (API 10.3): solo cambio pasto e domani/oggi
    tz = pytz.timezone('Europe/Rome')
    today_date = datetime.now(tz).date()
    try:
        current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        current_date = today_date

    tomorrow_date = today_date + timedelta(days=1)
    today_str = today_date.strftime("%Y-%m-%d")
    tomorrow_str = tomorrow_date.strftime("%Y-%m-%d")
    other_meal = "Cena" if meal_type_clean.lower() == "pranzo" else "Pranzo"
    target_date_str = tomorrow_str if current_date == today_date else today_str
    target_date_label = "DOMANI" if current_date == today_date else "OGGI"

    buttons_row = [
        {
            "text": other_meal.upper(),
            "callback_data": f"rm|{canteen_id}|{date_str}|{other_meal}"
        },
        {
            "text": target_date_label,
            "callback_data": f"rm|{canteen_id}|{target_date_str}|{meal_type_clean}"
        },
        {
            "text": "‹ MENSE",
            "callback_data": "sel_canteen|reset"
        }
    ]

    blocks.append({
        "type": "buttons",
        "align": "center",
        "buttons": buttons_row
    })

    # Fallback tradizionale per client o server senza supporto API 10.3
    fallback_text = get_menu_text(date_str, meal_type_clean, canteen_name)
    fb_row = [
        InlineKeyboardButton(other_meal.upper(), callback_data=f"rm|{canteen_id}|{date_str}|{other_meal}"),
        InlineKeyboardButton(target_date_label, callback_data=f"rm|{canteen_id}|{target_date_str}|{meal_type_clean}"),
        InlineKeyboardButton("‹ MENSE", callback_data="sel_canteen|reset")
    ]
    fallback_markup = InlineKeyboardMarkup([fb_row])

    return blocks, fallback_text, fallback_markup

async def send_canteen_rich_message(bot, chat_id: int, canteen_id: str, date_str: str, meal_type: str, user_id: int = None, is_group: bool = False):
    """Invia il menù come Rich Message (Bot API 10.3) con fallback a messaggio standard (supporta messaggi effimeri nei gruppi)."""
    blocks, fallback_text, fallback_markup = build_canteen_rich_message(canteen_id, date_str, meal_type)
    rich_payload = {
        "chat_id": chat_id,
        "rich_message": {
            "blocks": blocks
        }
    }
    if is_group and user_id:
        rich_payload["ephemeral_message_parameters"] = {
            "receiver_user_id": user_id
        }
    try:
        await bot._post("sendRichMessage", data=rich_payload)
    except Exception as e:
        logger.warning(f"Rich message send fallito ({e}), invio messaggio standard di fallback.")
        send_kwargs = {}
        if is_group and user_id:
            send_kwargs["api_kwargs"] = {
                "ephemeral_message_parameters": {
                    "receiver_user_id": user_id
                }
            }
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=fallback_text,
                reply_markup=fallback_markup,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                **send_kwargs
            )
        except Exception as e2:
            if is_group and user_id:
                logger.warning(f"Fallback menù effimero fallito ({e2}), messaggio non inviato nel gruppo.")
            else:
                raise

async def edit_canteen_rich_message(query, bot, canteen_id: str, date_str: str, meal_type: str):
    """Aggiorna un Rich Message esistente (Bot API 10.3) con fallback a modifica standard."""
    blocks, fallback_text, fallback_markup = build_canteen_rich_message(canteen_id, date_str, meal_type)
    try:
        await safe_edit_message(bot, query, rich_blocks=blocks)
    except Exception as e:
        logger.warning(f"Rich message edit fallito ({e}), provo fallback testuale.")
        try:
            await safe_edit_message(bot, query, text=fallback_text, reply_markup=fallback_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e2:
            logger.warning(f"Fallback edit fallito: {e2}")

async def handle_canteen_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il tap sui pulsanti delle mense (MARTIRI, BETTI, CAMMEO)."""
    text = (update.message.text or "").strip().upper()
    canteen_id = None
    for c_id, c_name in CANTEENS.items():
        clean = c_name.replace("Mensa ", "").upper()
        if clean == text or c_id.upper() == text:
            canteen_id = c_id
            break

    if not canteen_id:
        return

    tz = pytz.timezone('Europe/Rome')
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    meal_type = "Cena" if now.time() >= time(15, 0) else "Pranzo"

    await send_canteen_rich_message(context.bot, update.effective_chat.id, canteen_id, today_str, meal_type)

async def handle_group_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce l'evocazione del bot nei gruppi, rispondendo con messaggi effimeri visibili solo all'utente."""
    if not update.message:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in ("group", "supergroup") or not user:
        return

    text = (update.message.text or update.message.caption or "").strip()
    bot_username = (context.bot.username or "cibounipibot").lower()
    msg_lower = text.lower()

    # Verifica che il messaggio contenga effettivamente una menzione del bot
    if f"@{bot_username}" not in msg_lower and "@cibounipibot" not in msg_lower:
        return

    # Controlla se viene specificata una mensa nel messaggio
    canteen_id = None
    for c_id, c_name in CANTEENS.items():
        clean = c_name.replace("Mensa ", "").lower()
        if clean in msg_lower or c_id.lower() in msg_lower:
            canteen_id = c_id
            break

    if canteen_id:
        tz = pytz.timezone('Europe/Rome')
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        meal_type = "Cena" if now.time() >= time(15, 0) else "Pranzo"
        await send_canteen_rich_message(
            bot=context.bot,
            chat_id=chat.id,
            canteen_id=canteen_id,
            date_str=today_str,
            meal_type=meal_type,
            user_id=user.id,
            is_group=True
        )
    else:
        # Invia il benvenuto effimero dedicato al gruppo (senza comandi e senza bottoni mense)
        await send_welcome_rich_message(
            bot=context.bot,
            chat_id=chat.id,
            user_id=user.id,
            is_group=True
        )

async def post_init(application: Application) -> None:
    """Inizializza i comandi del bot: standard nelle chat private, effimeri nei gruppi."""
    try:
        # Comandi per le chat private
        await application.bot.set_my_commands(
            commands=[
                BotCommand("start", "Messaggio di benvenuto"),
                BotCommand("menu", "Menù di oggi"),
                BotCommand("links", "Link utili DSU e contatti")
            ],
            scope=BotCommandScopeAllPrivateChats()
        )
        # Comandi effimeri per le chat di gruppo (visibili solo all'utente che li usa)
        try:
            await application.bot._post(
                "setMyCommands",
                data={
                    "commands": [
                        {"command": "start", "description": "Messaggio di benvenuto", "is_ephemeral": True},
                        {"command": "menu", "description": "Menù di oggi", "is_ephemeral": True},
                        {"command": "links", "description": "Link utili DSU e contatti", "is_ephemeral": True}
                    ],
                    "scope": {"type": "all_group_chats"}
                }
            )
        except Exception as e_eph:
            logger.warning(f"Comandi effimeri per gruppi non supportati ({e_eph}), rimuovo comandi gruppi.")
            await application.bot.set_my_commands(
                commands=[],
                scope=BotCommandScopeAllGroupChats()
            )
    except Exception as e:
        logger.warning(f"Configurazione set_my_commands fallita: {e}")

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
    canteen_names = [re.escape(c.replace("Mensa ", "").upper()) for c in CANTEENS.values()]
    canteen_pattern = f"^(?i)({'|'.join(canteen_names)})$"
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(canteen_pattern), handle_canteen_text_message))
    
    # Risposta effimera alle menzioni o evocazioni del bot nei gruppi
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & (filters.Entity("mention") | filters.Regex(r"(?i)@cibounipibot")),
        handle_group_mention
    ))

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