# FILTRO AUDIO
# Filtro preliminare. Verifica se un frame audio ha abbastanza energia per essere potenzialmente interessante. Se il valore supera la soglia (in questo caso 300), il frame viene poi passato al VAD per una valutazione più approfondita.
ENERGY_THRESHOLD=400

# AGGRESSIVITA'
# Aggressività del riconoscimento vocale: Una modalità più aggressiva (valore più alto) richiede un segnale più chiaro per riconoscere il parlato, mentre modalità meno aggressive sono più permissive.
# 0: Molto poco aggressivo (più permissivo, potrebbe rilevare anche rumori deboli come parlato) | 3: Molto aggressivo (richiede una maggiore chiarezza del segnale per considerarlo parlato)
VAD_MODE=3

# AVETE FINITO DI PARLARE?
# Soglia di silenzio minima per valutare se può considerare la conveersazione chiusa
SILENCE_THRESHOLD_SECONDS=5

#ADESSO BASTA
# Il tempo massimo (in secondi) per la registrazione.
MAX_RECORD_SECONDS=60

# Durata minima (in secondi) che una registrazione deve avere per essere considerata valida e processata ulteriormente. 
DURATA_MINIMA=10