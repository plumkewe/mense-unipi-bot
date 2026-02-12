import os
import json
import logging
import pytz

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

from datetime import datetime, timedelta
from uuid import uuid4
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, InlineQueryHandler
from keep_alive import keep_alive # Import per ping e web server

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

# --- FIX APSCHEDULER TIMEZONE ---
def patch_apscheduler():
    try:
        import apscheduler.util
        import pytz as pz
        
        orig_astimezone = apscheduler.util.astimezone
        def patched_astimezone(obj):
            try:
                return orig_astimezone(obj)
            except TypeError:
                if obj is None:
                    return pz.UTC
                return orig_astimezone(pz.timezone(str(obj)))
        apscheduler.util.astimezone = patched_astimezone
    except Exception:
        pass

patch_apscheduler()

def get_menu_text(date_str, meal_type):
    """Recupera il testo del menù per una data e un tipo di pasto specifici."""
    day_menu = MENU.get(date_str)
    
    # Intestazione Data Decorativa
    header = ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Usa format_date_it se disponibile, altrimenti fai una format base
        # Nota: format_date_it deve essere definita nel modulo
        date_pretty = format_date_it(dt)
        # Stile "antico/decorativo" con caratteri speciali ai lati
        header = f"꧁   {date_pretty}   ꧂\n\n"
    except Exception:
        header = f"꧁   {date_str}   ꧂\n\n"

    if not day_menu:
        return f"{header}Nessun menù disponibile per questa data."

    meal_menu = day_menu.get(meal_type)
    
    # A volte potrebbe esserci la data ma non il tipo di pasto
    if not meal_menu:
         return f"{header}Nessun menù disponibile per il {meal_type.lower()}."
    
    text = header
    
    # Itera sulle categorie (es. Primi Piatti, Secondi Piatti)
    # L'ordine delle categorie dipende dal JSON, ma di solito è meglio averne uno fisso se possibile,
    # altrimenti iteriamo quello che c'è.
    for category, dishes in meal_menu.items():
        if dishes: # Mostra la categoria solo se ci sono piatti
            # Rimuove "PIATTI" dal nome della categoria per accorciare i titoli
            clean_category = category.upper().replace(" PIATTI", "")
            
            # Titoli semplificati: *CATEGORIA*
            text += f"*{clean_category}*\n"
            for dish in dishes:
                if isinstance(dish, dict):
                    name = dish.get("name", "").strip().capitalize()
                    link = dish.get("link")
                    if link:
                        text += f"- {name} [↗]({link})\n"
                    else:
                        text += f"- {name}\n"
                else:
                    text += f"- {dish.capitalize()}\n"
            text += "\n"
            
    return text

def get_keyboard(date_str, meal_type):
    """Crea la tastiera inline con i pulsanti di navigazione."""
    
    # Bottone per cambiare pasto (Pranzo <-> Cena)
    other_meal = "Cena" if meal_type == "Pranzo" else "Pranzo"
    # callback_data format: action|date|meal
    toggle_button = InlineKeyboardButton(other_meal.upper(), callback_data=f"toggle|{date_str}|{other_meal}")
    
    # Bottoni navigazione
    try:
        current_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        # Fallback se la data è corrotta, torniamo a oggi
        current_date_obj = datetime.now()

    prev_date = (current_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (current_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    today_date = datetime.now().strftime("%Y-%m-%d")

    # ○: oggi, con il pasto corrente
    nav_buttons = [
        InlineKeyboardButton("◀", callback_data=f"nav|{prev_date}|{meal_type}"),
        InlineKeyboardButton("○", callback_data=f"nav|{today_date}|{meal_type}"),
        InlineKeyboardButton("▶", callback_data=f"nav|{next_date}|{meal_type}"),
    ]
    
    keyboard = [
        nav_buttons,
        [toggle_button]
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
    today = datetime.now().date()
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
                 all_dishes = []
                 for cat_dishes in day_menu[meal].values():
                     for d in cat_dishes:
                         if isinstance(d, dict):
                             all_dishes.append(d.get("name", "").strip().upper())
                         else:
                             all_dishes.append(d.strip().upper())
                 
                 if target_clean in all_dishes:
                     occurrences.append({
                         "date": menu_date,
                         "diff": days_diff,
                         "meal": "P" if meal == "Pranzo" else "C"
                     })
    
    if not occurrences:
        return f"*{target_clean}*\nNessuna occorrenza futura trovata."

    # Costruisci il messaggio
    # Header: nome piatto in caps e bold
    text_lines = [f"*{target_clean}*"]
    
    # Lista formattata monospaced
    # MAR 17 MARZO   33 GG   P
    
    list_lines = []
    
    # Helper per formattazione data lista
    days_short = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    months_it = ["", "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO", "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"]

    for occ in occurrences:
        d = occ["date"]
        wd = days_short[d.weekday()]
        day_month = f"{d.day} {months_it[d.month]}"
        diff_str = f"{occ['diff']} GG"
        meal_flag = occ["meal"]
        
        # Allineamento
        # MAR (3 chars) + 1 space -> 4
        # 17 MARZO (approx 12 chars) -> 13
        # 33 GG (approx 6 chars) -> 7
        # P -> 1
        
        # Uso ljust per padding
        line = f"{wd:<3} {day_month:<13} {diff_str:<6} {meal_flag}"
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

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce le ricerche inline dei piatti."""
    query = update.inline_query.query
    results = []

    # Se la query è vuota, mostra il risultato "MENU DI OGGI"
    if not query:
        today = datetime.now().strftime("%Y-%m-%d")
        meal_type = "Pranzo"
        text = get_menu_text(today, meal_type)
        reply_markup = get_keyboard(today, meal_type)
        
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="MENU DI OGGI",
                description="Visualizza il menu di oggi...",
                thumbnail_url="https://img.icons8.com/color/48/restaurant-menu.png", 
                input_message_content=InputTextMessageContent(text, parse_mode=ParseMode.MARKDOWN),
                reply_markup=reply_markup
            )
        )
        await update.inline_query.answer(results, cache_time=0)
        return
    
    # Intercetta solo le query che iniziano con "p:"
    if not query.lower().startswith("p:"):
        return

    search_term = query[2:].strip().lower() # Rimuove "p:"
    # if len(search_term) < 3: # Opzionale: lunghezza minima
    #     return

    results = []
    today = datetime.now().date()
    
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
                             
                             # Immagine con il numero di giorni (Bold tramite ui-avatars)
                             thumb_url = f"https://ui-avatars.com/api/?background=007bff&color=ffffff&bold=true&name={days_diff}&length={len(str(days_diff))}&size=100"
                             
                             # ID Univoco per il risultato
                             result_id = str(uuid4())
                             
                             # Costruisci il messaggio con la lista di tutte le occorrenze future
                             content_text = get_dish_schedule(clean_dish_name)
                             reply_markup = get_update_keyboard(clean_dish_name)

                             results.append(
                                 InlineQueryResultArticle(
                                     id=result_id,
                                     title=clean_dish_name,
                                     description=f"{date_fmt}",
                                     thumbnail_url=thumb_url,
                                     input_message_content=InputTextMessageContent(content_text, parse_mode=ParseMode.MARKDOWN),
                                     reply_markup=reply_markup
                                 )
                             )
                             count += 1
    
    await update.inline_query.answer(results, cache_time=5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /start."""
    user = update.effective_user.first_name
    text = (
        f"*{user}, benvenuto su MARTIRI BOT!*\n\n"
        "Questo bot ti permette di consultare il menù della mensa Martiri in modo rapido e veloce.\n\n"
        "*Ricerca Inline*\n"
        "In qualsiasi chat, digita:\n"
        "`@cibounipibot p:nome piatto`\n"
        "_(es. @cibounipibot p:Peposo)_\n\n"
        "*Comandi*\n"
        "/menu - Mostra il menù di oggi\n"
        "/help - Guida all'uso\n\n"
        "*Feedback*\n"
        "Hai suggerimenti o vuoi segnalare un bug?\n"
        "Scrivi a: `lyubomyr.malay@gmail.com`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /menu. Mostra il menù di oggi."""
    today = datetime.now().strftime("%Y-%m-%d")
    meal_type = "Pranzo"
    text = get_menu_text(today, meal_type)
    reply_markup = get_keyboard(today, meal_type)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce il comando /help."""
    text = (
        "*GUIDA ALL'USO*\n\n"
        "*Comandi Principali*\n"
        "/start - Avvia il bot e mostra il benvenuto\n"
        "/menu - Mostra il menù del giorno\n"
        "/help - Mostra questo messaggio\n\n"
        "*1. Ricerca Piatto*\n"
        "Puoi cercare quando verrà servito un piatto direttamente in qualsiasi chat.\n"
        "Digita il nome del bot seguito da `p:` e il nome del piatto:\n\n"
        "Esempio:\n"
        "`@cibounipibot p:Pollo`\n\n"
        "*Output:*\n"
        "Una lista con tutte le date future in cui quel piatto sarà disponibile.\n"
        "Cliccando sul risultato invierai un messaggio con il calendario dettagliato.\n\n"
        "*Navigazione Menù*\n"
        "Nel messaggio del menù (/menu), usa i pulsanti:\n"
        "◀ ▶ : Cambia giorno\n"
        "○ : Torna a oggi\n"
        "PRANZO / CENA : Cambia il pasto visualizzato\n\n"
        "*Feedback e Supporto*\n"
        "Hai suggerimenti o vuoi segnalare un bug?\n"
        "Invia una mail: `lyubomyr.malay@gmail.com`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i click sui bottoni inline."""
    query = update.callback_query
    await query.answer() # Importante per fermare l'animazione di caricamento sul client

    data = query.data.split("|")
    action = data[0]

    if action == "upd":
        dish_name = data[1]
        text = get_dish_schedule(dish_name)
        # La tastiera rimane la stessa (o rigenerata)
        reply_markup = get_update_keyboard(dish_name)
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass # Ignora se il messaggio non è cambiato
        return

    date_str = data[1]
    meal_type = data[2]

    text = get_menu_text(date_str, meal_type)
    reply_markup = get_keyboard(date_str, meal_type)

    # Modifica il messaggio esistente
    # A volte telegram da errore se il contenuto è identico, lo gestiamo col try-except
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Non è stato possibile aggiornare il messaggio (forse identico?): {e}")

def main() -> None:
    """Avvia il bot."""
    # Avvia il server web in background per Render
    keep_alive()

    # Recupera il token dalle variabili d'ambiente (GitHub Secrets)
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        logger.error("Errore: La variabile d'ambiente BOT_TOKEN non è impostata.")
        print("Per favore imposta la variabile d'ambiente BOT_TOKEN.")
        return

    # Risoluzione problema timezone per APScheduler (usato internamente da python-telegram-bot)
    # Disabilitiamo il job_queue se non serve per evitare problemi con APScheduler
    application = Application.builder().token(token).job_queue(None).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(InlineQueryHandler(inline_query))

    # Avvia il bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)
        
if __name__ == "__main__":
    main()
