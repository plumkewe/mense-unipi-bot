import os
import glob
from instagrapi import Client
from pathlib import Path
import datetime as dt

def main():
    # Credentials dal GitHub Secrets
    USERNAME = os.environ.get("IG_USERNAME")
    PASSWORD = os.environ.get("IG_PASSWORD")

    if not USERNAME or not PASSWORD:
        print("Errore: credenziali IG_USERNAME o IG_PASSWORD non impostate.")
        return

    # Inizializza e Accedi
    cl = Client()
    try:
        cl.login(USERNAME, PASSWORD)
        print("Login ad Instagram effettuato con successo!")
    except Exception as e:
        print(f"Errore durante il login: {e}")
        return

    # Cartella target
    posts_dir = Path("posts")
    if not posts_dir.exists():
        print(f"La cartella {posts_dir} non esiste. Non c'è nulla da pubblicare.")
        return

    oggi_iso = dt.date.today().strftime("%Y%m%d")
    oggi_ita = dt.date.today().strftime("%d.%m.%Y")
    didascalia = f"🍽️ Menu Mensa Martiri del {oggi_ita}\n\nSwipe per vedere il pranzo e la cena! 👉\n\n#unipi #mensaunipi #pisa #cibounipi"

    # Prendi SOLO le immagini di OGGI per evitare ri-pubblicazioni di ieri
    # usando il prefisso YYYYMMDD
    pranzo_files = sorted(list(posts_dir.glob(f"{oggi_iso}_pranzo_martiri.png")))
    cena_files = sorted(list(posts_dir.glob(f"{oggi_iso}_cena_martiri.png")))

    album_paths = []
    
    if pranzo_files:
        album_paths.append(pranzo_files[-1])
    else:
        print("Nessun menu Pranzo trovato per oggi.")

    if cena_files:
        album_paths.append(cena_files[-1])
    else:
        print("Nessun menu Cena trovato per oggi.")

    if not album_paths:
        print("Nessuna immagine di oggi da pubblicare. Potrebbe essere chiusa o già pubblicata/rinominata.")
        return

    # Evitiamo di ripubblicare se esiste già un segnale che oggi è stato pubblicato (es. file di lock)
    lock_file = posts_dir / f"{oggi_iso}_published.lock"
    if lock_file.exists():
        print(f"I menu di oggi ({oggi_ita}) sono GIA' stati pubblicati! (Trovato file lock)")
        return

    if len(album_paths) == 1:
        # Pubblica singola foto
        print(f"Pubblico singola foto: {album_paths[0]}")
        cl.photo_upload(album_paths[0], didascalia)
    else:
        # Pubblica album (Pranzo -> Cena)
        print(f"Pubblico Carousel (Album) con foto: {[p.name for p in album_paths]}")
        cl.album_upload(album_paths, didascalia)
        
    print("Pubblicazione completata!")

    # Crea un file di lock per impedire post duplicati 
    # se la GitHub action dovesse essere lanciata una seconda volta nello stesso giorno
    with open(lock_file, "w") as f:
        f.write("Pubblicato con successo.")
        
if __name__ == "__main__":
    main()
