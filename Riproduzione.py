#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ____    _    ____   ____    _    ____  ____  
#| __ )  / \  |  _ \ | __ )  / \  |  _ \|  _ \ 
#|  _ \ / _ \ | |_) ||  _ \ / _ \ | |_) | | | |
#| |_) / ___ \|  _ < | |_) / ___ \|  _ <| |_| |
#|____/_/   \_\_| \_\|____/_/   \_\_| \_\____/ 



"""
Riproduzione.py: Riproduce le canzoni generate in ordine FIFO,
con un'interfaccia a dashboard e crossfade.
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
os.chdir(PROJECT_ROOT)
# --- FINE BLOCCO UNIVERSALE ---

import time
import json
import logging
import subprocess
import socket
import threading
from datetime import datetime
from filelock import FileLock, Timeout
from colorama import init, Fore, Style

# --- INIZIALIZZAZIONE GLOBALE ---
init(autoreset=True)

# --- CONFIGURAZIONE CON PERCORSI PORTABILI ---
PLAYER_VOLUME = 80
CROSSFADE_SECONDS = 8
# Le directory temporanee e i file di lock sono ora relativi a PROJECT_ROOT.
TMP_DIR = PROJECT_ROOT / ".tmp_player"
PLAYLIST_FILE = TMP_DIR / "playlist.queue"
PLAYER_LOCK_FILE = TMP_DIR / "player_instance.lock"
PLAYLIST_LOCK_FILE = TMP_DIR / "playlist.queue.lock"
MPV_SOCKET_MAIN = TMP_DIR / "main.sock"
MPV_SOCKET_NEXT = TMP_DIR / "next.sock"

# --- LOGGING SU FILE ---
# Assicura che la directory dei log esista prima di configurare il logging
TMP_DIR.mkdir(exist_ok=True)
LOG_FILE = TMP_DIR / "player.log"
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    filename=LOG_FILE,
    filemode='w'
)

# --- COLORI E FORMATTAZIONE ---
SEPARATOR = "----------------------------------------------------------------------"
TAVOLO_COLOR = Fore.YELLOW + Style.BRIGHT
FRESHNESS_COLOR = Fore.MAGENTA
STYLE_COLOR = Fore.LIGHTBLACK_EX
EMPTY_COLOR = Fore.RED

def get_timestamp():
    return datetime.now().strftime('%H:%M:%S')

class DJPlayer:
    def __init__(self):
        self.current_process = None
        self.monitor_thread = None
        self.stop_monitor_event = threading.Event()
        self.has_printed_empty_playlist_msg = False
        self._setup_environment()
        print(f"{get_timestamp()} {Fore.CYAN}DJ Semplice (FIFO) con Stile Dashboard avviato.")
        logging.info("DJ Semplice (FIFO) avviato.")

    def _setup_environment(self):
        """Prepara le directory e pulisce i socket residui."""
        TMP_DIR.mkdir(exist_ok=True)
        PLAYLIST_FILE.touch(exist_ok=True)
        MPV_SOCKET_MAIN.unlink(missing_ok=True)
        MPV_SOCKET_NEXT.unlink(missing_ok=True)

    @staticmethod
    def _calculate_freshness(song_path: Path) -> str:
        """Calcola la 'freschezza' di una canzone dal suo timestamp nel nome file."""
        try:
            parts = song_path.stem.split('_')
            timestamp_str = f"{parts[0]}_{parts[1]}"
            creation_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
            delta_seconds = (datetime.now() - creation_time).total_seconds()
            if delta_seconds < 60: return f"~{int(delta_seconds)}s"
            if delta_seconds < 3600: return f"~{round(delta_seconds / 60)}m"
            return f"~{round(delta_seconds / 3600, 1)}h"
        except (IndexError, ValueError):
            return "N/A"

    def _get_next_song_from_queue(self) -> dict | None:
        """Consuma la *prima* canzone dalla coda (FIFO) in modo sicuro."""
        playlist_lock = FileLock(PLAYLIST_LOCK_FILE)
        while True:
            try:
                with playlist_lock.acquire(timeout=1):
                    if not PLAYLIST_FILE.exists():
                        lines = []
                    else:
                        lines = PLAYLIST_FILE.read_text(encoding="utf-8").splitlines()
                        lines = [line for line in lines if line.strip()] # Pulisce righe vuote

                    if not lines:
                        if not self.has_printed_empty_playlist_msg:
                            print(f"{get_timestamp()} {EMPTY_COLOR}PLAYLIST VUOTA. In attesa di nuove canzoni...")
                            self.has_printed_empty_playlist_msg = True
                    else:
                        self.has_printed_empty_playlist_msg = False
                        song_line_to_process = lines.pop(0) # Prendi e rimuovi la prima riga
                        
                        # Riscrive il file con le righe rimanenti
                        PLAYLIST_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                        
                        try:
                            song_data = json.loads(song_line_to_process)
                            # Converte la stringa del percorso in un oggetto Path
                            # Essendo un percorso assoluto, non serve risolverlo di nuovo.
                            song_data['path'] = Path(song_data['path'])
                            if not song_data['path'].is_file():
                                print(f"{Fore.RED}File non trovato: {song_data['path']}. Scarto la canzone.")
                                logging.warning(f"File canzone non trovato, scartato: {song_data['path']}")
                                continue # Cerca la prossima canzone
                            return song_data
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"{Fore.RED}Scartata riga non valida dalla playlist: {song_line_to_process}. Errore: {e}")
                            logging.error(f"Riga playlist non valida scartata: {e}")
            except Timeout:
                pass # Se il lock è occupato, semplicemente riprova dopo una pausa
            time.sleep(2)

    def _send_mpv_command(self, socket_path, command):
        """Invia un comando JSON al socket IPC di mpv."""
        if not socket_path.exists(): return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(str(socket_path))
                s.sendall(json.dumps(command).encode('utf-8') + b'\n')
            return True
        except (ConnectionRefusedError, FileNotFoundError): return False

    def _get_mpv_property(self, socket_path, prop):
        """Ottiene una proprietà (es. 'duration') dal socket IPC di mpv."""
        if not socket_path.exists(): return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0) # Evita blocchi infiniti
                s.connect(str(socket_path))
                s.sendall(json.dumps({"command": ["get_property", prop]}).encode('utf-8') + b'\n')
                response_data = s.recv(1024)
                if not response_data: return None
                response = json.loads(response_data.decode('utf-8'))
            return response.get("data") if response.get("error") == "success" else None
        except (json.JSONDecodeError, socket.timeout, ConnectionRefusedError, FileNotFoundError): return None

    def _start_mpv_instance(self, song_path, volume, socket_path, table_number):
        """Avvia una nuova istanza di mpv per una canzone."""
        if not song_path.is_file(): return None
        command = ["mpv", "--really-quiet", "--no-video", f"--volume={volume}", f"--input-ipc-server={socket_path}", str(song_path)]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1) # Attende che mpv si avvii e crei il socket
        if process.poll() is not None: return None # Controlla se è crashato all'avvio
        return process

    def _perform_crossfade(self, next_song_data):
        """Esegue un crossfade tra la canzone corrente e la successiva."""
        next_song_path = next_song_data['path']
        table_number = next_song_data['table']
        print(f"\n{get_timestamp()} {Fore.BLUE}CROSSFADE... Verso '{next_song_path.name}' (Tavolo {table_number})")
        logging.info(f"Inizio crossfade verso '{next_song_path.name}'")
        self.stop_monitor_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive(): self.monitor_thread.join()
        
        next_process = self._start_mpv_instance(next_song_path, 0, MPV_SOCKET_NEXT, table_number)
        if not next_process: return self.current_process # Se il nuovo player non parte, continua col vecchio
        
        steps, sleep_interval = 20, CROSSFADE_SECONDS / 20
        for i in range(steps + 1):
            current_volume = int(PLAYER_VOLUME * (1 - (i / steps)))
            next_volume = int(PLAYER_VOLUME * (i / steps))
            self._send_mpv_command(MPV_SOCKET_MAIN, {"command": ["set_property", "volume", current_volume]})
            self._send_mpv_command(MPV_SOCKET_NEXT, {"command": ["set_property", "volume", next_volume]})
            time.sleep(sleep_interval)
            
        if self.current_process: self.current_process.kill()
        MPV_SOCKET_MAIN.unlink(missing_ok=True)
        os.rename(MPV_SOCKET_NEXT, MPV_SOCKET_MAIN)
        return next_process

    def _monitor_playback(self, process, socket_path, song_data):
        """Monitora la riproduzione, stampa la barra di progresso e le informazioni."""
        time.sleep(1)
        duration = self._get_mpv_property(socket_path, "duration")
        freshness = self._calculate_freshness(song_data['path'])
        
        durata_str = f"| {int(duration)//60:02d}:{int(duration)%60:02d}" if duration else ""
        print(f"{get_timestamp()} {TAVOLO_COLOR}TAVOLO-{song_data['table']} > PLAY: {song_data['path'].name} {durata_str} | {FRESHNESS_COLOR}FRESH: {freshness}")
        print(f"{STYLE_COLOR}Stile: {song_data.get('style', 'N/A')}")
        
        while not self.stop_monitor_event.is_set() and process.poll() is None:
            pos = self._get_mpv_property(socket_path, "time-pos")
            if pos is not None and duration is not None and duration > 0:
                percent = int((pos / duration) * 100)
                bar_len = 30
                filled_len = int(bar_len * percent / 100)
                bar = '█' * filled_len + '-' * (bar_len - filled_len)
                pos_m, pos_s = divmod(int(pos), 60)
                dur_m, dur_s = divmod(int(duration), 60)
                sys.stdout.write(f"\r{Fore.GREEN}PLAYING: |{bar}| {percent}% | Tavolo #{song_data.get('table', 'N/A')} | ({pos_m:02d}:{pos_s:02d} / {dur_m:02d}:{dur_s:02d})")
                sys.stdout.flush()
            time.sleep(1)
        
        sys.stdout.write("\r" + " " * 120 + "\r") # Pulisce la riga
        print(f"{get_timestamp()} {Fore.GREEN}FINISHED! Looking for next song...")
        print(f"{STYLE_COLOR}{SEPARATOR}{Style.RESET_ALL}\n")
        logging.info("Riproduzione terminata.")

    def run(self):
        """Ciclo principale del player."""
        try:
            while True:
                song_data = self._get_next_song_from_queue()
                if not song_data: continue # Torna a controllare la coda
                
                is_playing = self.current_process and self.current_process.poll() is None
                if is_playing:
                    new_process = self._perform_crossfade(song_data)
                else:
                    new_process = self._start_mpv_instance(song_data['path'], PLAYER_VOLUME, MPV_SOCKET_MAIN, song_data['table'])
                
                if not new_process:
                    self.current_process = None
                    logging.error(f"Impossibile avviare la riproduzione per {song_data['path']}")
                    time.sleep(5)
                    continue

                self.current_process = new_process
                self.stop_monitor_event.clear()
                self.monitor_thread = threading.Thread(target=self._monitor_playback, args=(self.current_process, MPV_SOCKET_MAIN, song_data), daemon=True)
                self.monitor_thread.start()
                
                self.current_process.wait() # Attende la fine del processo mpv
                self.stop_monitor_event.set()
                if self.monitor_thread and self.monitor_thread.is_alive():
                    self.monitor_thread.join()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Esegue la pulizia finale alla terminazione."""
        print(f"\n{get_timestamp()} {Fore.BLUE}Eseguo pulizia finale...")
        if self.current_process and self.current_process.poll() is None:
            self.current_process.kill()
        # Comando più robusto per terminare tutte le istanze di mpv legate al progetto
        subprocess.run(["pkill", "-f", f"mpv.*{TMP_DIR.name}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"{get_timestamp()} {Fore.GREEN}Pulizia completata.")

if __name__ == "__main__":
    player = None
    try:
        # Usa un file lock per garantire che solo un'istanza del player sia in esecuzione
        with FileLock(PLAYER_LOCK_FILE, timeout=0):
            player = DJPlayer()
            player.run()
    except KeyboardInterrupt:
        print(f"\n{get_timestamp()} {Fore.YELLOW}Terminazione richiesta dall'utente...")
    except Timeout:
        print(f"{Fore.RED}Un'altra istanza del Player è già in esecuzione."); sys.exit(1)
    except Exception as e:
        logging.critical(f"Errore fatale nel player: {e}", exc_info=True)
        print(f"\n{get_timestamp()} {Fore.RED}ERRORE FATALE: {e}")
    finally:
        if player:
            player.cleanup()