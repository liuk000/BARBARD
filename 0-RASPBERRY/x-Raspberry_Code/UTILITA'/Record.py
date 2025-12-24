import pyaudio
import wave
import time
import os

# Parametri di registrazione ottimizzati per il tuo hardware
FORMAT = pyaudio.paInt16      # Il tuo microfono supporta solo 16 bit
CHANNELS = 1                  # Mono
RATE = 48000                  # Alta frequenza di campionamento
CHUNK = 4096                  # Buffer grande per ridurre gli errori
RECORD_SECONDS = 5            # Durata della registrazione
WAVE_OUTPUT_FILENAME = "optimized_recording.wav"

def record_audio_with_arecord():
    try:
        # Utilizziamo il formato S16_LE che il tuo microfono supporta
        cmd = f"arecord -D hw:2,0 -f S16_LE -c1 -r48000 -d {RECORD_SECONDS} {WAVE_OUTPUT_FILENAME}"
        print(f"Esecuzione comando per registrazione ottimizzata: {cmd}")
        os.system(cmd)
        print(f"Registrazione completata! File salvato come {WAVE_OUTPUT_FILENAME}")
        return True
    except Exception as e:
        print(f"Errore durante la registrazione con arecord: {e}")
        return False

# Esegui la registrazione
record_audio_with_arecord()