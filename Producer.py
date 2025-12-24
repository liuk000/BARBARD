#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# ____    _    ____   ____    _    ____  ____  
#| __ )  / \  |  _ \ | __ )  / \  |  _ \|  _ \ 
#|  _ \ / _ \ | |_) ||  _ \ / _ \ | |_) | | | |
#| |_) / ___ \|  _ < | |_) / ___ \|  _ <| |_| |
#|____/_/   \_\_| \_\|____/_/   \_\_| \_\____/ 



"""
Producer.py: Orchestratore per la generazione di canzoni.
Monitora le trascrizioni pronte, le assegna a dei worker concorrenti
in modo equo e gestisce il ciclo di vita della produzione musicale.
(Versione con percorsi dinamici e portabili, logging stile-immagine,
spinner, CODA LIMITATA, DEBUG e BATCH ATOMICI per massimizzare il throughput)
"""

# --- INIZIO BLOCCO UNIVERSALE DI GESTIONE PERCORSI ---
import os
import sys
import uuid # <-- 1. MODIFICA: Import per ID unici dei job
from pathlib import Path
from dotenv import load_dotenv

# Trova il percorso assoluto della directory in cui si trova questo script.
# Questo rende il progetto portabile e indipendente dalla directory di lavoro corrente.
try:
    PROJECT_ROOT = Path(__file__).parent.resolve()
except NameError:
    # Fallback per ambienti (es. notebook interattivi) dove __file__ non è definito
    PROJECT_ROOT = Path('.').resolve()

# Imposta la directory di lavoro sulla radice del progetto per coerenza.
os.chdir(PROJECT_ROOT)
load_dotenv()
# --- FINE BLOCCO UNIVERSALE ---

import time
import json
import shutil
import subprocess
from multiprocessing import Pool
from datetime import datetime
from filelock import FileLock, Timeout
from colorama import init, Fore, Style

# --- INIZIALIZZAZIONE GLOBALE ---
init(autoreset=True)

# --- CONFIGURAZIONE CON PERCORSI PORTABILI ---
# I percorsi sono ora costruiti a partire da PROJECT_ROOT per essere robusti.
WORK_DIR = PROJECT_ROOT / "WORK_IN_PROGRESS"
TRANSCRIPT_ARCHIVE_DIR = PROJECT_ROOT / "FROM_TABLES" / "Archive" / "Trascrizioni"
FAILED_TRANSCRIPTS_DIR = WORK_DIR / "failed_processing"
TMP_DIR = PROJECT_ROOT / ".tmp_player"
JOBS_TMP_DIR = TMP_DIR / "jobs" # <-- 2. MODIFICA: Directory per i batch temporanei

PLAYLIST_FILE = TMP_DIR / "playlist.queue"
PLAYLIST_LOCK_FILE = TMP_DIR / "playlist.queue.lock"
PRODUCER_LOCK_FILE = TMP_DIR / "producer_instance.lock"
PRODUCER_STATE_FILE = TMP_DIR / "producer_state.json"

# Il percorso dello script da lanciare deve essere assoluto per evitare errori
SONG_GENERATOR_SCRIPT = PROJECT_ROOT / "GenerateSong.py"

MAX_WORKERS= int(os.getenv("MAX_WORKERS", "2"))
MAX_QUEUE_SIZE= int(os.getenv("MAX_QUEUE_SIZE", "2"))

# --- FUNZIONI DI UTILITÀ ---
def get_timestamp():
    return datetime.now().strftime('%H:%M:%S')

def clear_status_line():
    """ Pulisce la riga di stato corrente per evitare sovrapposizioni di output. """
    sys.stdout.write("\r" + " " * 120 + "\r")
    sys.stdout.flush()

def get_queue_size() -> int:
    """ Controlla in modo sicuro la dimensione attuale della playlist. """
    try:
        with FileLock(PLAYLIST_LOCK_FILE, timeout=1):
            if not PLAYLIST_FILE.exists():
                return 0
            lines = PLAYLIST_FILE.read_text(encoding="utf-8").splitlines()
            return len([line for line in lines if line.strip()])
    except Timeout:
        return MAX_QUEUE_SIZE
    except FileNotFoundError:
        return 0

# --- LOGICA DEL WORKER ---
# <-- 3. MODIFICA: La firma della funzione ora accetta job_dir invece di calcolarlo -->
def create_song_worker(job_dir: Path, table_number: int, creations_count: int) -> tuple[int, bool]:
    """
    Funzione eseguita da ogni processo worker.
    Lavora su una directory di job temporanea e isolata.
    """
    clear_status_line()
    print(f"{Fore.CYAN}{get_timestamp()} [ {table_number} ] Equità: {creations_count}. COMPONGO (Job: {job_dir.name})!{Style.RESET_ALL}")
    
    # Il worker ora opera sulla directory di job che gli è stata passata
    transcript_files = sorted(list(job_dir.glob("*.txt")))

    try:
        if not transcript_files:
            clear_status_line()
            print(f"{Fore.RED}{get_timestamp()} [ {table_number} ] ERRORE: Nessun file di trascrizione trovato nel job dir {job_dir}.{Style.RESET_ALL}")
            return table_number, False

        concatenated_text = "\n---\n".join([p.read_text(encoding="utf-8") for p in transcript_files])
        clear_status_line()
        print(f"{Fore.MAGENTA}{get_timestamp()} [ {table_number} ] Avviato. Trovati [{len(transcript_files)}] file. Genero riassunto & lyrics...{Style.RESET_ALL}")

        command = [sys.executable, "-u", str(SONG_GENERATOR_SCRIPT), str(table_number)]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT
        )
        process.stdin.write(concatenated_text)
        process.stdin.close()
        
        song_data_json = ""
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if not line: continue
            clear_status_line()
            if line.startswith("MILESTONE:"):
                message = line.replace("MILESTONE: ", "").strip()
                color = Fore.YELLOW + Style.BRIGHT if "INVIO ALL'API" in message else Style.DIM
                print(f"{color}{get_timestamp()} [ {table_number} ] {message}{Style.RESET_ALL}")
            elif line.startswith("{"):
                song_data_json = line
            else:
                print(f"{Style.DIM}{line}{Style.RESET_ALL}")
        
        stderr_output = process.stderr.read()
        return_code = process.wait()

        if return_code != 0:
            clear_status_line()
            print(f"{Fore.RED}{Style.BRIGHT}{get_timestamp()} [ {table_number} ] ERRORE! '{SONG_GENERATOR_SCRIPT.name}' ha fallito (codice {return_code}).{Style.RESET_ALL}")
            print(f"{Fore.RED}{stderr_output.strip()}", file=sys.stderr)
            # Sposta l'intera cartella del job fallito per l'analisi
            error_dir = FAILED_TRANSCRIPTS_DIR / f"failed_job_{job_dir.name}"
            shutil.move(str(job_dir), str(error_dir))
            return table_number, False

        if not song_data_json:
            clear_status_line()
            print(f"{Fore.RED}{Style.BRIGHT}{get_timestamp()} [ {table_number} ] ERRORE! Script terminato senza output JSON.{Style.RESET_ALL}")
            return table_number, False
        
        with FileLock(PLAYLIST_LOCK_FILE):
            with open(PLAYLIST_FILE, "a", encoding="utf-8") as f:
                f.write(song_data_json + "\n")
        
        archive_sub_dir = TRANSCRIPT_ARCHIVE_DIR / str(table_number)
        archive_sub_dir.mkdir(parents=True, exist_ok=True)
        for txt_file in transcript_files: # I file sono ancora in job_dir
            shutil.move(str(txt_file), str(archive_sub_dir / txt_file.name))
        
        clear_status_line()
        print(f"{Fore.GREEN}{Style.BRIGHT}{get_timestamp()} [ {table_number} ] PRODUZIONE COMPLETATA! Canzone inviata alla playlist.{Style.RESET_ALL}")
        
        # <-- 4. MODIFICA: Pulisce la cartella del job temporaneo dopo il successo -->
        shutil.rmtree(job_dir)
        return table_number, True
    
    except Exception as e:
        clear_status_line()
        print(f"{Fore.RED}{Style.BRIGHT}{get_timestamp()} [ {table_number} ] ERRORE CRITICO nel worker: {e}{Style.RESET_ALL}", file=sys.stderr)
        # Sposta l'intera cartella del job fallito per analisi anche in caso di eccezione
        if job_dir.exists():
            error_dir = FAILED_TRANSCRIPTS_DIR / f"crashed_job_{job_dir.name}"
            shutil.move(str(job_dir), str(error_dir))
        return table_number, False

# --- GESTORE PRINCIPALE (MANAGER) ---

class ProducerManager:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.active_jobs = {}
        self.creation_counts = self._load_state()
        self.spinner_chars = ['-', '\\', '|', '/']
        self.spinner_index = 0
        
        clear_status_line()
        print(f"{Fore.CYAN}{get_timestamp()} [PRODUCER] Manager avviato. Workers: {max_workers}, Coda max: {MAX_QUEUE_SIZE}.{Style.RESET_ALL}")

    def _load_state(self) -> dict:
        default_counts = {str(i): 0 for i in range(1, 6)}
        if not PRODUCER_STATE_FILE.exists():
            return default_counts
        try:
            with PRODUCER_STATE_FILE.open('r') as f:
                counts = json.load(f)
                for i in range(1, 6):
                    if str(i) not in counts:
                        counts[str(i)] = 0
                return counts
        except (json.JSONDecodeError, IOError):
            clear_status_line()
            print(f"{Fore.RED}{get_timestamp()} [PRODUCER] ERRORE: File di stato corrotto. Ricomincio da zero.{Style.RESET_ALL}", file=sys.stderr)
            return default_counts

    def _save_state(self):
        with PRODUCER_STATE_FILE.open('w') as f:
            json.dump(self.creation_counts, f, indent=2)

    def run(self):
        """Ciclo principale del manager."""
        # <-- 5. MODIFICA: Assicura che anche la directory dei job venga creata -->
        for d in [TMP_DIR, WORK_DIR, TRANSCRIPT_ARCHIVE_DIR, FAILED_TRANSCRIPTS_DIR, JOBS_TMP_DIR]:
            d.mkdir(parents=True, exist_ok=True)
            
        with Pool(processes=self.max_workers) as pool:
            try:
                while True:
                    self.cleanup_finished_jobs()
                    self.assign_new_jobs_fairly(pool)
                    self.print_status_with_spinner()
                    time.sleep(0.2)
            except KeyboardInterrupt:
                clear_status_line()
                print(f"\n{Fore.YELLOW}{get_timestamp()} [PRODUCER] Terminazione richiesta... Attendo fine lavori...{Style.RESET_ALL}")
                pool.close()
                pool.join()
        
        clear_status_line()
        print(f"{Fore.CYAN}{get_timestamp()} [PRODUCER] Lavori terminati. Uscita pulita.{Style.RESET_ALL}")

    def cleanup_finished_jobs(self):
        completed_jobs = {job for job in self.active_jobs if job.ready()}
        if not completed_jobs: return

        for job in completed_jobs:
            table = self.active_jobs.pop(job)
            try:
                _, success = job.get()
                if success:
                    # Assicuriamoci di aggiornare dinamicamente il dizionario se un tavolo non esiste
                    if str(table) not in self.creation_counts:
                         self.creation_counts[str(table)] = 0
                    self.creation_counts[str(table)] += 1
                    self._save_state()
            except Exception as e:
                clear_status_line()
                print(f"{Fore.RED}{Style.BRIGHT}{get_timestamp()} [PRODUCER] ERRORE CRITICO ottenendo risultato per tavolo #{table}: {e}{Style.RESET_ALL}", file=sys.stderr)

    # <-- 6. MODIFICA: Logica di assegnazione completamente riscritta con Batch Atomici -->
    def assign_new_jobs_fairly(self, pool):
        """Assegna nuovi lavori usando batch atomici per massimizzare il throughput."""
        if get_queue_size() >= MAX_QUEUE_SIZE or len(self.active_jobs) >= self.max_workers:
            return

        while len(self.active_jobs) < self.max_workers:
            # Scansiona le directory con file .txt pronti
            ready_dirs = [d for d in WORK_DIR.iterdir() if d.is_dir() and d.name.isdigit() and any(d.glob('*.txt'))]
            candidate_tables = [d.name for d in ready_dirs]
            
            if not candidate_tables:
                break # Nessun lavoro da assegnare

            # Logica di equità: scegli il tavolo con meno creazioni tra quelli con lavoro pronto
            table_to_process_str = min(candidate_tables, key=lambda t: self.creation_counts.get(t, 0))
            table_to_process = int(table_to_process_str)
            creations = self.creation_counts.get(table_to_process_str, 0)

            # --- INIZIO LOGICA DEL BATCH ATOMICO ---
            source_dir = WORK_DIR / table_to_process_str
            # Rilegge i file per sicurezza, per evitare race conditions
            files_to_process = list(source_dir.glob('*.txt'))
            
            if not files_to_process:
                continue # I file sono spariti tra la scansione e ora, riprova il ciclo

            # 1. Crea una directory di job unica
            job_id = f"{table_to_process_str}_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"
            job_dir = JOBS_TMP_DIR / job_id
            job_dir.mkdir()

            # 2. Sposta i file in modo atomico nel batch
            for txt_file in files_to_process:
                try:
                    shutil.move(str(txt_file), str(job_dir / txt_file.name))
                except FileNotFoundError:
                    # Il file è stato preso da un altro processo? Ignora e vai avanti.
                    pass
            # --- FINE LOGICA DEL BATCH ATOMICO ---

            # 3. Lancia il worker passandogli il percorso del job
            job_obj = pool.apply_async(create_song_worker, args=(job_dir, table_to_process, creations))
            self.active_jobs[job_obj] = table_to_process


    def print_status_with_spinner(self):
        active_list = sorted(list(self.active_jobs.values())) if self.active_jobs else 'Nessuno'
        current_queue_size = get_queue_size()
        
        status_msg = f"Slot liberi: {self.max_workers - len(self.active_jobs)}/{self.max_workers} | Coda: {current_queue_size}/{MAX_QUEUE_SIZE} | In Lavorazione: {active_list}"
        
        if current_queue_size >= MAX_QUEUE_SIZE:
             status_msg += f" {Fore.YELLOW}(IN PAUSA){Style.RESET_ALL}"
        
        spinner_char = self.spinner_chars[self.spinner_index]
        line_with_spinner = f"\r{Fore.WHITE}{Style.BRIGHT}[GENERAZIONE] {status_msg} {spinner_char}{Style.RESET_ALL}   "
        
        sys.stdout.write(line_with_spinner)
        sys.stdout.flush()
        self.spinner_index = (self.spinner_index + 1) % len(self.spinner_chars)

# --- PUNTO DI INGRESSO DELLO SCRIPT ---
if __name__ == "__main__":
    print(f"{Fore.BLUE}{Style.BRIGHT}--- Parametri di Configurazione Caricati ---{Style.RESET_ALL}")
    print(f"{Fore.BLUE}  - MAX_WORKERS    : {MAX_WORKERS}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}  - MAX_QUEUE_SIZE : {MAX_QUEUE_SIZE}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}{Style.BRIGHT}-------------------------------------------{Style.RESET_ALL}\n")

    try:
        with FileLock(PRODUCER_LOCK_FILE, timeout=0):
            manager = ProducerManager(max_workers=MAX_WORKERS)
            manager.run()
    except Timeout:
        clear_status_line()
        print(f"{Fore.RED}Un'altra istanza del Producer è già in esecuzione.", file=sys.stderr)
    except Exception as e:
        clear_status_line()
        print(f"\n{Fore.RED}ERRORE FATALE nel Producer Manager: {e}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)