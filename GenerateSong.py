#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# ____    _    ____   ____    _    ____  ____  
#| __ )  / \  |  _ \ | __ )  / \  |  _ \|  _ \ 
#|  _ \ / _ \ | |_) ||  _ \ / _ \ | |_) | | | |
#| |_) / ___ \|  _ < | |_) / ___ \|  _ <| |_| |
#|____/_/   \_\_| \_\|____/_/   \_\_| \_\____/ 



"""
GenerateSong.py: Riceve testo via stdin, genera un riassunto e dei testi
con OpenAI, e poi una canzone con l'API KieAI.
(Versione con percorsi dinamici e portabili)
"""


# --- INIZIO BLOCCO UNIVERSALE DI GESTIONE PERCORSI ---
import os
import sys
from pathlib import Path

# Trova il percorso assoluto della directory in cui si trova questo script.
# Questo rende il progetto portabile e indipendente dalla directory di lavoro corrente.
try:
    PROJECT_ROOT = Path(__file__).parent.resolve()
except NameError:
    # Fallback per ambienti (es. notebook interattivi) dove __file__ non è definito
    PROJECT_ROOT = Path('.').resolve()

# Imposta la directory di lavoro sulla radice del progetto per coerenza.
# Questo garantisce che percorsi relativi come "SONGS" o "FROM_TABLES"
# vengano sempre risolti correttamente.
os.chdir(PROJECT_ROOT)
# --- FINE BLOCCO UNIVERSALE ---

import json
import time
import random
import requests
from datetime import datetime
from typing import Tuple, Optional

try:
    from dotenv import load_dotenv
    # Carica il file .env specificando il percorso assoluto, rendendo l'operazione più robusta
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
except ImportError:
    print("AVVISO: Libreria python-dotenv non trovata. Continuo con le variabili di sistema.", file=sys.stderr)

# --- CONFIGURAZIONE CON PERCORSI PORTABILI ---
OUTPUT_DIR = PROJECT_ROOT / "SONGS"
ARCHIVE_BASE_DIR = PROJECT_ROOT / "FROM_TABLES" / "Archive"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KIEAI_API_KEY = os.getenv("KIEAI_API_KEY")

# --- PARAMETRI DI GENERAZIONE (dal .env) ---
MUSIC_MODEL = os.getenv("MODEL", "V4_5")
CALLBACK_URL = os.getenv("CALLBACK_URL", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 10))
MAX_POLL_ATTEMPTS = int(os.getenv("MAX_POLL_ATTEMPTS", "80"))
IS_INSTRUMENTAL = os.getenv("INSTRUMENTAL", "False").lower() in ("true", "1", "yes")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gpt-3.5-turbo")
SUMMARY_MAX_TOKENS = int(os.getenv("MAX_TOKENS_SUMMARY", "150"))
SUMMARY_TEMPERATURE = float(os.getenv("TEMPERATURE_SUMMARY", "0.5"))
LYRICS_MODEL = os.getenv("LYRICS_MODEL", "gpt-4o")
SUMMARY_SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "Riassumi la conversazione seguente in modo conciso, catturandone l'argomento e l'umore.")
LYRICS_MASTER_PROMPT = os.getenv("STILE_LYRICS", "Sei un cantautore. Usa il riassunto seguente per scrivere il testo completo di una canzone, con strofe e ritornello.")

def load_env_list(prefix: str) -> list[str]:
    """Carica variabili d'ambiente che iniziano con un dato prefisso in una lista."""
    return [v for k, v in os.environ.items() if k.startswith(prefix) and v.strip()]

STYLE_OPTIONS = load_env_list("DEFAULT_STYLE")

# --- FUNZIONI DI LOGGING ---
def log_error(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.stderr.flush()

def log_debug(msg: str):
    print(f"DEBUG: {msg}", file=sys.stderr)
    sys.stderr.flush()

def log_milestone(msg: str):
    """Stampa un messaggio di stato formattato per essere catturato dal processo padre."""
    print(f"MILESTONE: {msg}", file=sys.stdout)
    sys.stdout.flush()

# --- INIZIALIZZAZIONE CLIENTS ---
try:
    import openai
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    log_error(f"Impossibile inizializzare client OpenAI: {e}")
    sys.exit(1)

# --- LOGICA PRINCIPALE ---

def choose_random_style() -> str:
    """Sceglie uno stile musicale casuale dalla lista caricata dal .env."""
    if not STYLE_OPTIONS:
        return "epic cinematic" # Fallback
    return random.choice(STYLE_OPTIONS)

def generate_lyrics(text: str) -> Optional[Tuple[str, str]]:
    """Genera prima un riassunto e poi i testi della canzone usando OpenAI."""
    log_milestone("Genero riassunto & lyrics...")
    try:
        # 1. Genera riassunto
        summary_response = openai_client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=SUMMARY_TEMPERATURE
        )
        summary = summary_response.choices[0].message.content.strip()

        # 2. Genera testi basati sul riassunto
        final_lyrics_prompt = f"{LYRICS_MASTER_PROMPT}\n\n---\n\n{summary}"
        lyrics_response = openai_client.chat.completions.create(
            model=LYRICS_MODEL,
            messages=[{"role": "user", "content": final_lyrics_prompt}]
        )
        lyrics = lyrics_response.choices[0].message.content.strip()
        log_milestone("Testo della canzone ricevuto da OpenAI")
        return lyrics, summary
    except Exception as e:
        log_error(f"Errore durante la generazione del testo con OpenAI: {e}")
        return None

def generate_music(lyrics: str, style: str) -> Optional[Path]:
    """Invia i testi all'API musicale, esegue il polling e scarica il file audio."""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {KIEAI_API_KEY}", "Content-Type": "application/json"})
    payload = {
        "prompt": lyrics,
        "customMode": True,
        "model": MUSIC_MODEL,
        "style": style,
        "instrumental": IS_INSTRUMENTAL,
        "callBackUrl": CALLBACK_URL
    }
    
    # Stampa i dettagli per il log del processo padre e poi invia la richiesta
    print(f"Modello: {MUSIC_MODEL}, Stile: {style}") # Catturato da Producer.py
    log_milestone("INVIO ALL'API")
    
    try:
        resp = session.post("https://kieai.erweima.ai/api/v1/generate", json=payload)
        resp.raise_for_status()
        data = resp.json().get("data")
        if data is None:
            log_error(f"La risposta dell'API musicale non contiene il campo 'data'. Risposta: {resp.json()}")
            return None
    except requests.exceptions.RequestException as e:
        log_error(f"Errore nella richiesta iniziale all'API musicale: {e}")
        return None
    
    task_id = data.get("taskId")
    if not task_id:
        log_error("Nessun taskId ricevuto dall'API musicale.")
        return None
    
    log_milestone(f"Richiesta accettata. Task ID: {task_id}. Inizio polling...")
    status = data.get("status", "PENDING")
    
    MAX_POLLING_NETWORK_ERRORS = 3
    network_error_count = 0
    for attempt in range(MAX_POLL_ATTEMPTS):
        if status in ("FAILURE", "SENSITIVE_WORD_ERROR", "GENERATE_AUDIO_FAILED"):
            log_error(f"La generazione musicale è fallita. Stato API: {status}")
            return None
        if status == "SUCCESS":
            log_milestone("API musicale ha terminato la generazione con successo")
            break
            
        time.sleep(POLL_INTERVAL)
        
        try:
            r = session.get(f"https://kieai.erweima.ai/api/v1/generate/record-info?taskId={task_id}")
            r.raise_for_status()
            data = r.json().get("data", {})
            status = data.get("status", "UNKNOWN")
            network_error_count = 0 # Reset su successo
        except requests.exceptions.RequestException as e:
            network_error_count += 1
            log_debug(f"Errore di rete durante il polling (tentativo {network_error_count}/{MAX_POLLING_NETWORK_ERRORS}): {e}")
            if network_error_count >= MAX_POLLING_NETWORK_ERRORS:
                log_error(f"Troppi errori di rete consecutivi durante il polling. Interrompo.")
                return None
            # Backoff esponenziale per non sovraccaricare l'API
            wait_time = POLL_INTERVAL * (2 ** (network_error_count - 1))
            time.sleep(wait_time)
            continue
    else: # Questo `else` si attiva solo se il loop `for` finisce senza `break`
        log_error(f"Timeout durante la generazione della musica. Ultimo stato noto: {status}")
        return None
    
    try:
        # Cerca l'URL audio in più punti per robustezza
        audio_url = data.get("response", {}).get("sunoData", [{}])[0].get("audioUrl") or data.get("audio_url")
        if not audio_url:
            log_error(f"Nessun URL audio trovato nella risposta finale dell'API. Dati ricevuti: {data}")
            return None
            
        log_milestone("Download del file audio generato")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        random_suffix = ''.join(random.choices('0123456789abcdef', k=4))
        mp3_filepath = OUTPUT_DIR / f"{timestamp}_{random_suffix}.mp3"
        
        with requests.get(audio_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(mp3_filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        log_milestone("COMPLETATO!")
        return mp3_filepath
    except Exception as e:
        log_error(f"Errore critico durante il download o il salvataggio del file audio: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        log_error("Uso: python GenerateSong.py <table_number>")
        sys.exit(1)
        
    table_number = sys.argv[1]
    concatenated_text = sys.stdin.read()
    
    if not concatenated_text.strip():
        log_error("Input da stdin vuoto. Impossibile procedere.")
        sys.exit(1)
    
    # Assicura che la directory di output esista
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    result = generate_lyrics(concatenated_text)
    if not result:
        sys.exit(1)
    lyrics, summary = result
    
    # Archivia il riassunto
    archive_summary_dir = ARCHIVE_BASE_DIR / table_number
    archive_summary_dir.mkdir(parents=True, exist_ok=True)
    summary_filename = f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    (archive_summary_dir / summary_filename).write_text(summary, encoding="utf-8")
    
    # Genera la musica
    style = choose_random_style()
    music_path = generate_music(lyrics, style)
    if not music_path:
        sys.exit(1)

    # Salva i metadati (testo, stile, trascrizione completa) accanto al file audio
    music_path.with_suffix('.style.txt').write_text(style, encoding="utf-8")
    music_path.with_suffix('.lyrics.txt').write_text(lyrics, encoding="utf-8")
    music_path.with_suffix('.full-transcript.txt').write_text(concatenated_text, encoding="utf-8")
    
    # Stampa il JSON finale che il processo Producer catturerà
    output_data = {
        "path": str(music_path.resolve()), # .resolve() garantisce un percorso assoluto
        "table": table_number,
        "style": style
    }
    print(json.dumps(output_data))

if __name__ == "__main__":
    main()