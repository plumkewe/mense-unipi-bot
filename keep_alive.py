from flask import Flask
from threading import Thread
import requests
import time
import os
import logging
import random

app = Flask('')

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return "I'm alive"

def run():
    # Render assegna una porta tramite variabile d'ambiente PORT.
    # Se non c'è, usa la 8080 come default o fallback.
    port = int(os.environ.get("PORT", 8080))
    # Importante: host='0.0.0.0' per essere raggiungibile dall'esterno su Render
    app.run(host='0.0.0.0', port=port)

def ping_self():
    """
    Funzione che pinga il server ogni 14 minuti circa per evitare 
    che vada in sleep (su Render free tier).
    """
    logger.info(f"Avvio ping periodico (attesa iniziale).")

    while True:
        # Attesa intelligente: 14 minuti + un po' di jitter casuale
        # Render va in sleep dopo 15 min. 14 min = 840 sec.
        sleep_time = 840 + random.randint(0, 30)
        time.sleep(sleep_time)
        try:
            # Recupera l'URL dinamicamente ad ogni ciclo nel caso cambi o non sia ancora settato
            current_url = os.environ.get("RENDER_EXTERNAL_URL")
            if not current_url:
                 current_url = "http://127.0.0.1:8080"
            
            response = requests.get(current_url)
            logger.info(f"Ping inviato a {current_url}: Status {response.status_code}")
        except Exception as e:
            logger.error(f"Errore durante il ping: {e}")

def keep_alive():
    # Avvia il server Flask in un thread separato
    t_server = Thread(target=run)
    t_server.daemon = True
    t_server.start()
    
    # Avvia il pinger in un altro thread
    t_pinger = Thread(target=ping_self)
    t_pinger.daemon = True
    t_pinger.start()
