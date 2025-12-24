# start_system.py (Versione dedicata ESCLUSIVAMENTE alla pulizia)


import sys
import shutil
from pathlib import Path
from colorama import init, Fore

# Inizializza colorama per avere output colorato
init(autoreset=True)

class Colors:
    CLEANUP = Fore.YELLOW
    ERROR = Fore.RED

# --- CONFIGURAZIONE DEI PERCORSI ---
PROJECT_ROOT = Path(__file__).parent
FROM_TABLES_DIR = PROJECT_ROOT / "FROM_TABLES"
ARCHIVE_DIR = FROM_TABLES_DIR / "Archive"
WORK_IN_PROGRESS_DIR = PROJECT_ROOT / "WORK_IN_PROGRESS"
TMP_PLAYER_DIR = PROJECT_ROOT / ".tmp_player"
LOGS_DIR = PROJECT_ROOT / "LOGS"
SONGS_DIR = PROJECT_ROOT / "SONGS" # Aggiunta per pulire anche le canzoni vecchie

def log(message, color=Colors.CLEANUP):
    """Funzione per stampare messaggi colorati."""
    print(f"{color}{message}{Fore.RESET}")

def cleanup_routine():
    """Esegue tutte le operazioni di pulizia per uno stato 'vanilla'."""
    log("--- Inizio Routine di Pulizia 'Vanilla' ---")

    # 1. Cancella i file N-Lyrics.txt
    log("1. Cancellazione vecchi file *-Lyrics.txt...")
    for f_path in PROJECT_ROOT.glob("*-Lyrics.txt"):
        try: f_path.unlink(); log(f"   - Rimosso: {f_path.name}")
        except OSError as e: log(f"   - Errore: {e}", Colors.ERROR)

    # 2. Svuota WORK_IN_PROGRESS, .tmp_player, SONGS
    for dir_to_clean in [WORK_IN_PROGRESS_DIR, TMP_PLAYER_DIR, SONGS_DIR]:
        log(f"2. Pulizia di {dir_to_clean.name}...")
        if dir_to_clean.exists():
            try: shutil.rmtree(dir_to_clean)
            except OSError as e: log(f"   - Errore: {e}", Colors.ERROR)
        dir_to_clean.mkdir(exist_ok=True)
        log(f"   - Cartella {dir_to_clean.name} ricreata.")

    # 3. Archivia file audio orfani in FROM_TABLES
    log("3. Archiviazione file audio orfani...")
    if FROM_TABLES_DIR.exists():
        wav_files = list(FROM_TABLES_DIR.glob("*.wav"))
        if wav_files:
            orphan_dir = ARCHIVE_DIR / "orphaned_at_startup"
            orphan_dir.mkdir(parents=True, exist_ok=True)
            for f_path in wav_files:
                try: shutil.move(str(f_path), str(orphan_dir)); log(f"   - Archiviato: {f_path.name}")
                except OSError as e: log(f"   - Errore: {e}", Colors.ERROR)
        else:
            log("   - Nessun file audio orfano.")

    # 4. Tronca i file di log
    log("4. Pulizia dei file di log...")
    LOGS_DIR.mkdir(exist_ok=True)
    for log_file_name in ["Transcription_Log.txt", "generator.log"]:
        log_file = LOGS_DIR / log_file_name
        if log_file.exists():
            try: log_file.write_text(''); log(f"   - File '{log_file_name}' svuotato.")
            except OSError as e: log(f"   - Errore: {e}", Colors.ERROR)

    log("--- Routine di Pulizia Completata ---")


if __name__ == "__main__":
    cleanup_routine()
    print("\nAmbiente pulito. Lo script di pulizia ha terminato.")
    # Lo script ora finisce qui. Non lancia altri processi.