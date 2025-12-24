#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Questo script genera un brano musicale partendo da un file di testo contenente i lyrics.
Cerca automaticamente nella directory corrente un file che corrisponda al pattern 'n-Lyrics.txt',
scegliendo quello con il numero 'n' più basso. Usa uno stile musicale casuale definito
nelle variabili d'ambiente e chiama un'API per generare e scaricare l'audio.
Dopo l'elaborazione, il file di testo originale viene spostato nella directory PROCESSED_LYRICS.
"""

import os
import sys
import json
import time
import random
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

# --- CONFIGURAZIONE ---
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("DEBUG: Variabili d'ambiente caricate da .env", file=sys.stderr)
except ImportError:
    print("AVVISO: Libreria python-dotenv non trovata. Continuo con le variabili di sistema.", file=sys.stderr)

# Directory di output e di archivio
OUTPUT_DIR = Path("SONGS")
PROCESSED_DIR = Path("PROCESSED_LYRICS")

# Credenziali e configurazione API musicale
KIEAI_API_KEY = os.getenv("KIEAI_API_KEY")
MUSIC_MODEL = os.getenv("MODEL", "V4_5")
CALLBACK_URL = os.getenv("CALLBACK_URL", "")
IS_INSTRUMENTAL = os.getenv("INSTRUMENTAL", "False").lower() in ("true", "1", "yes")

# Configurazione del processo di polling
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 10))
MAX_POLL_ATTEMPTS = int(os.getenv("MAX_POLL_ATTEMPTS", "80"))

# --- FUNZIONI DI UTILITÀ ---

def log_error(msg: str):
    """Stampa un messaggio di errore sullo standard error."""
    print(f"ERROR: {msg}", file=sys.stderr)

def log_milestone(msg: str):
    """Stampa un messaggio di stato importante sullo standard output."""
    print(f"MILESTONE: {msg}", file=sys.stdout)
    sys.stdout.flush()

def load_env_list(prefix: str) -> list[str]:
    """Carica una lista di valori dalle variabili d'ambiente che iniziano con un dato prefisso."""
    return [v for k, v in os.environ.items() if k.startswith(prefix) and v.strip()]

# Carica gli stili musicali dalle variabili d'ambiente (es. DEFAULT_STYLE_1, DEFAULT_STYLE_2)
STYLE_OPTIONS = load_env_list("DEFAULT_STYLE")

def choose_random_style() -> str:
    """Sceglie uno stile musicale casuale dalla lista caricata. Se la lista è vuota, usa un default."""
    if not STYLE_OPTIONS:
        return "epic cinematic"
    return random.choice(STYLE_OPTIONS)

def find_and_select_lyrics_file() -> Optional[Tuple[Path, str]]:
    """
    Scansiona la directory corrente per file 'n-Lyrics.txt', li ordina
    numericamente e restituisce il percorso e il numero del primo file trovato.
    """
    potential_files = Path('.').glob('*-Lyrics.txt')
    valid_files = []
    for p in potential_files:
        try:
            # Estrae il numero dal nome del file (es. "12" da "12-Lyrics.txt")
            number_str = p.stem.split('-')[0]
            number = int(number_str)
            valid_files.append((number, p))
        except (ValueError, IndexError):
            print(f"AVVISO: Ignoro il file '{p.name}' perché non segue il formato n-Lyrics.txt", file=sys.stderr)
            continue

    if not valid_files:
        return None

    # Ordina i file in base al numero estratto (crescente)
    valid_files.sort(key=lambda item: item[0])

    # Prende il primo file (quello con il numero più basso)
    selected_number, selected_path = valid_files[0]

    return selected_path, str(selected_number)


def generate_music(lyrics: str, style: str) -> Optional[Path]:
    """
    Invia i lyrics all'API musicale, attende il completamento e scarica l'audio.
    (La logica interna di questa funzione rimane invariata)
    """
    if not KIEAI_API_KEY:
        log_error("La variabile d'ambiente KIEAI_API_KEY non è impostata.")
        return None

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {KIEAI_API_KEY}", "Content-Type": "application/json"})
    
    payload = {"prompt": lyrics, "customMode": True, "model": MUSIC_MODEL, "style": style, "instrumental": IS_INSTRUMENTAL, "callBackUrl": CALLBACK_URL}
    
    print(f"Modello: {MUSIC_MODEL}, Stile: {style}")
    log_milestone("INVIO RICHIESTA ALL'API MUSICALE")
    
    try:
        resp = session.post("https://kieai.erweima.ai/api/v1/generate", json=payload); resp.raise_for_status()
        data = resp.json().get("data")
        if data is None: log_error(f"La risposta API non contiene 'data'. Risposta: {resp.json()}"); return None
    except requests.exceptions.RequestException as e:
        log_error(f"Errore richiesta iniziale API: {e}"); return None
    
    task_id = data.get("taskId")
    if not task_id: log_error("Nessun taskId ricevuto."); return None
    
    log_milestone(f"Richiesta accettata. Task ID: {task_id}. Inizio polling...")
    status = data.get("status", "PENDING")
    
    # Logica di polling (invariata)
    for _ in range(MAX_POLL_ATTEMPTS):
        if status in ("FAILURE", "SENSITIVE_WORD_ERROR", "GENERATE_AUDIO_FAILED"): log_error(f"Generazione fallita, stato API: {status}"); return None
        if status == "SUCCESS": log_milestone("API ha terminato la generazione."); break
        time.sleep(POLL_INTERVAL)
        try:
            r = session.get(f"https://kieai.erweima.ai/api/v1/generate/record-info?taskId={task_id}"); r.raise_for_status()
            data = r.json().get("data", {}); status = data.get("status", "UNKNOWN")
        except requests.exceptions.RequestException: continue # Semplificato per brevità
    else:
        log_error(f"Timeout generazione musica. Stato finale: {status}"); return None
    
    # Download del file audio (invariato)
    try:
        audio_url = data.get("response", {}).get("sunoData", [{}])[0].get("audioUrl") or data.get("audio_url")
        if not audio_url: log_error(f"Nessun URL audio trovato. Dati: {data}"); return None
        log_milestone(f"Download del file audio da: {audio_url}")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S'); random_suffix = ''.join(random.choices('0123456789abcdef', k=4))
        mp3_filepath = OUTPUT_DIR / f"{timestamp}_{random_suffix}.mp3"
        with requests.get(audio_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(mp3_filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
        log_milestone("DOWNLOAD COMPLETATO!")
        return mp3_filepath
    except Exception as e:
        log_error(f"Errore durante download/salvataggio: {e}"); return None

def main():
    """Funzione principale dello script."""
    # 1. Trova automaticamente il prossimo file di testo da elaborare
    result = find_and_select_lyrics_file()
    if result is None:
        log_milestone("Nessun file 'n-Lyrics.txt' da elaborare trovato nella directory corrente.")
        sys.exit(0)
    
    lyrics_filename, file_number = result
    log_milestone(f"File candidato trovato: '{lyrics_filename.name}'")
        
    # 2. Leggi il contenuto del file
    try:
        lyrics = lyrics_filename.read_text(encoding="utf-8").strip()
        if not lyrics:
            log_error(f"Il file di testo '{lyrics_filename}' è vuoto. Lo sposto negli elaborati.")
            PROCESSED_DIR.mkdir(exist_ok=True)
            lyrics_filename.rename(PROCESSED_DIR / lyrics_filename.name)
            sys.exit(1)
    except Exception as e:
        log_error(f"Impossibile leggere il file di testo '{lyrics_filename}': {e}")
        sys.exit(1)

    # 3. Prepara l'ambiente di output e scegli lo stile
    OUTPUT_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)
    style = choose_random_style()
    
    log_milestone(f"Inizio generazione musicale dal file '{lyrics_filename.name}' con stile '{style}'")
    
    # 4. Genera la musica
    music_path = generate_music(lyrics, style)
    if not music_path:
        log_error("La generazione musicale non è andata a buon fine. Il file di testo non verrà spostato.")
        sys.exit(1)

    # 5. Salva i file di metadati associati
    music_path.with_suffix('.style.txt').write_text(style, encoding="utf-8")
    music_path.with_suffix('.lyrics.txt').write_text(lyrics, encoding="utf-8")
    
    # 6. Sposta il file di testo originale per evitare di riprocessarlo
    try:
        destination = PROCESSED_DIR / lyrics_filename.name
        lyrics_filename.rename(destination)
        log_milestone(f"File di testo elaborato '{lyrics_filename.name}' spostato in '{destination}'")
    except Exception as e:
        log_error(f"ATTENZIONE: Impossibile spostare il file '{lyrics_filename.name}'. Errore: {e}")

    # 7. Stampa l'output JSON finale per il processo chiamante
    output_data = {
        "path": str(music_path.resolve()),
        "source_file_number": file_number,
        "style": style
    }
    print(json.dumps(output_data))
    log_milestone("Processo terminato con successo.")


if __name__ == "__main__":
    main()