#######################

GENERALE

#######################


Descrizione Tecnica del Sistema di Generazione Musicale Automatizzata
Panoramica
Questo progetto implementa una pipeline di elaborazione dati end-to-end, asincrona e multi-processo, progettata per trasformare input audio grezzi in composizioni musicali originali. L'architettura è modellata su un pattern Producer-Consumer disaccoppiato, con componenti specializzati che garantiscono alta disponibilità, scalabilità e resilienza.
Il sistema è suddiviso in tre servizi principali, ognuno eseguito come un processo a lunga durata (daemon-like), che operano in modo concorrente. La comunicazione tra i servizi è gestita tramite un file system condiviso, che agisce come un message broker semplice ma efficace, con meccanismi di locking per garantire l'integrità dei dati.
Componenti dell'Architettura
1. AudioWatchdog.py: Il Servizio di Ingestione (Ingestion Service)
Scopo: Agisce come il punto di ingresso della pipeline. Il suo unico compito è il monitoraggio continuo di una directory di "drop-off" (FROM_TABLES) per l'arrivo di nuovi file audio (.wav).
Logica Operativa:
Polling e Stabilità del File: Utilizza un ciclo di polling per scansionare la directory a intervalli regolari. Fondamentalmente, implementa un controllo di stabilità del file (verificando che os.stat().st_size non cambi per un breve periodo) per garantire che vengano processati solo file la cui scrittura è terminata, prevenendo letture parziali e corruzione dei dati.
Trascrizione: Per ogni file stabile, invia una richiesta all'API OpenAI Whisper per la trascrizione audio-testo.
Smistamento (Dispatching):
Se la trascrizione ha successo, il testo viene salvato in una struttura di directory di staging (WORK_IN_PROGRESS/{table_id}/), preparando il materiale per la fase successiva. Il {table_id} è derivato da un prefisso numerico nel nome del file originale (es. 5-nomefile.wav).
Gestione Trascrizioni Corte: Se la trascrizione risulta più corta di una soglia minima configurabile (MIN_CHARS_TRANSCRIPTION), viene considerata di scarso valore. Per ottimizzare i costi e le risorse, il file audio originale viene archiviato in una directory apposita (short_transcriptions), bypassando il resto della pipeline.
Archiviazione e Resilienza: Il file audio originale viene sempre archiviato per evitare ri-processamenti. Un blocco try...except gestisce i fallimenti dell'API Whisper, spostando i file audio problematici in una directory di quarantena (transcription_errors) per analisi manuale. Questo garantisce che un file corrotto o un errore API non blocchino l'intera pipeline di ingestione.
2. Producer.py: Il Core di Elaborazione (Processing Core)
Questo è il componente più complesso dell'architettura, che implementa un pattern Manager-Worker utilizzando multiprocessing.Pool per massimizzare la concorrenza e sfruttare appieno le CPU multi-core.
Scopo: Orchestrare la trasformazione delle trascrizioni testuali in brani musicali completi, applicando una logica di scheduling equo e a prova di race condition.
Logica del Manager (ProducerManager):
Stato Persistente: Mantiene uno stato (producer_state.json) che traccia il numero di canzoni create per ogni "tavolo". Questo stato sopravvive ai riavvii ed è fondamentale per la logica di fair scheduling.
Fair Scheduling & Assegnazione Atomica dei Batch: Il cuore del manager è il suo ciclo di assegnazione dei lavori. Per garantire equità e robustezza, segue questi passaggi:
Scansione dei Candidati: Scansiona la directory di staging (WORK_IN_PROGRESS) per identificare tutti i "tavoli" che hanno file di trascrizione pronti e per i quali non c'è già un lavoro attivo.
Applicazione dell'Equità: Tra i tavoli candidati, seleziona quello con il minor numero di creazioni registrate nello stato persistente (min(..., key=lambda t: self.creation_counts.get(t, 0))). Questo previene la "starvation" dei tavoli meno attivi, garantendo che tutti abbiano la possibilità di essere processati.
Creazione del Batch Atomico: Una volta scelto il tavolo, il manager crea una directory di job unica e temporanea (es. .tmp_player/jobs/1_153005_a4b1c8).
Spostamento Atomico: Sposta immediatamente tutti i file di testo pronti per quel tavolo dalla directory di staging (WORK_IN_PROGRESS/1) alla nuova directory del job. Questa operazione di spostamento è atomica e fondamentale: elimina la race condition per cui un ciclo di assegnazione molto rapido potrebbe vedere gli stessi file e lanciare più worker per lo stesso identico lavoro. Una volta spostati, i file non sono più visibili nella directory di staging.
Dispatching al Worker: Lancia un worker asincrono (pool.apply_async) passandogli il percorso della directory del job isolata.
Gestione della Coda (Backpressure): Monitora la dimensione della playlist finale (playlist.queue). Se questa raggiunge la soglia massima (MAX_QUEUE_SIZE), il manager smette di assegnare nuovi lavori, applicando una forma di backpressure per evitare di sovraccaricare il servizio di riproduzione.
Logica del Worker (create_song_worker):
Isolamento: Ogni worker opera in un processo isolato, lavorando esclusivamente sui file contenuti nella directory del job che gli è stata passata.
Esecuzione di Sottoprocessi: Lancia GenerateSong.py come un sottoprocesso (subprocess.Popen) con il flag -u (unbuffered). Questo permette al manager di catturare l'output (stdout) in tempo reale, fornendo un logging granulare e il monitoraggio "live" dello stato di generazione tramite messaggi MILESTONE:.
GenerateSong.py (L'Unità di Lavoro AI):
NLP Pipeline: Esegue una pipeline sequenziale di chiamate alle API OpenAI: prima a un modello di riassunto (es. gpt-3.5-turbo) per condensare il testo, poi a un modello di generazione testi più potente (es. gpt-4o) per creare i lyrics basati sul riassunto.
Music Generation API Call: Invia i lyrics a un'API di generazione musicale di terze parti (es. KieAI/Suno).
Polling Robusto: Implementa un ciclo di polling con tentativi massimi e backoff esponenziale per interrogare lo stato del job musicale, gestendo in modo resiliente errori di rete temporanei e stati di fallimento specifici dell'API.
Gestione Risultati e Pulizia: Se la generazione ha successo, il worker aggiunge i metadati della canzone (un oggetto JSON) alla coda di riproduzione (playlist.queue), archivia le trascrizioni usate e rimuove la directory del job temporaneo. In caso di fallimento, l'intera directory del job viene spostata in quarantena (failed_processing) per l'analisi post-mortem.
3. Riproduzione.py: Il Servizio di Output (Playback Service)
Scopo: Agire come il consumatore finale della pipeline, garantendo un flusso musicale continuo e senza interruzioni con un'interfaccia a dashboard.
Logica Operativa:
Pattern Consumatore FIFO: Implementa un consumatore First-In, First-Out. Monitora costantemente la playlist.queue e processa le canzoni nell'ordine in cui sono state prodotte.
Locking Atomico: Utilizza filelock per tutte le operazioni di lettura/scrittura sulla playlist.queue. Questo garantisce operazioni atomiche e previene race condition tra il Producer (che scrive) e il DJ (che legge), preservando l'integrità della coda.
Comunicazione Inter-Processo (IPC): Utilizza mpv come motore di riproduzione, controllandolo tramite socket IPC UNIX. Questo approccio avanzato permette un controllo granulare del player (volume, pausa, seek, ottenimento durata/posizione) direttamente da Python, senza dover parsare l'output del terminale.
Crossfade Avanzato: Quando una nuova canzone è pronta mentre un'altra è in riproduzione, il servizio orchestra un crossfade fluido. Lancia una seconda istanza di mpv su un socket IPC separato con volume a zero, quindi esegue un ciclo di fade-out sul player principale e fade-in su quello nuovo, manipolando i rispettivi volumi tramite comandi IPC. Al termine, il vecchio processo mpv viene terminato.
Dashboard UI: Fornisce un output a terminale ricco e dinamico, che mostra una barra di progresso, il tempo di riproduzione, il tavolo di origine e altre informazioni sulla canzone corrente, offrendo un'eccellente osservabilità.


#######################

AudioWatchdog.py: 

#######################


Il Servizio di Ingestione (Ingestion Service)

Scopo: 

Agisce come il punto di ingresso del sistema. 
Il suo unico compito è il monitoraggio continuo 
di una directory di "drop-off" (FROM_TABLES) 
per nuovi file audio (.wav).

Logica Operativa:

Utilizza un ciclo di polling (time.sleep) 
per scansionare la directory a intervalli regolari.

Implementa un controllo di stabilità del file 
(verificando che os.stat().st_size 
non cambi per un breve periodo) 
per garantire che vengano processati 
solo file la cui scrittura è terminata, 
prevenendo letture parziali.

Per ogni file valido, invia una richiesta 
all'API OpenAI Whisper 
per la trascrizione audio-testo asincrona.

Smistamento (Dispatching): 

In base a un prefisso numerico nel nome del file 
(es. 5-nomefile.wav), 
il testo trascritto viene salvato 
in una struttura di directory di staging 
(WORK_IN_PROGRESS/{table_id}/), 
preparando il materiale per la fase successiva.

Il file audio originale viene archiviato 
per evitare ri-processamenti.

Resilienza: 

Un blocco try...except 
gestisce i fallimenti dell'API Whisper, 
spostando i file audio problematici 
in una directory di quarantena (transcription_errors) 
per analisi manuale, 
garantendo che un file corrotto 
non blocchi la pipeline.


#######################

Producer.py:

#######################

Questo è il componente più complesso, 
che implementa un pattern Manager-Worker 
utilizzando il modulo multiprocessing.
Pool per massimizzare la concorrenza 
e sfruttare appieno le CPU multi-core.

Scopo: 
Orchestare la trasformazione delle trascrizioni 
testuali in brani musicali completi, 
applicando una logica di scheduling equo.

Logica del Manager:

Stato Persistente: 

Mantiene uno stato persistente 
(producer_state.json)
che traccia il numero di canzoni 
create per ogni "tavolo" (sorgente). 
Questo è fondamentale 
per la logica di fair scheduling.

Fair Scheduling (Equità): 

3In ogni ciclo, il Manager 
scansiona la directory di staging 
(WORK_IN_PROGRESS). 
Tra tutti i tavoli con materiale pronto 
e senza un lavoro già attivo, 
seleziona quello con il minor numero 
di creazioni registrate. 
Questo previene la "starvation" 
dei tavoli meno attivi.

Gestione della Concorrenza: 

Lancia lavori asincroni (pool.apply_async) 
fino a un limite configurabile 
(MAX_WORKERS), 
riempiendo il pool 
per massimizzare il throughput.

Prevenzione Race Condition: 
La logica di scheduling 
esclude esplicitamente i tavoli 
per cui un job è già stato inviato al pool 
ma non è ancora terminato, 
prevenendo che più worker 
vengano lanciati per lo stesso set di dati.

Logica del Worker (create_song_worker):

Ogni worker opera in un processo isolato.
Concatena tutte le trascrizioni 
disponibili per il tavolo assegnato.

Esecuzione di Sottoprocessi: 

Lancia GenerateSong.py come un sottoprocesso 
(subprocess.Popen) con il flag -u (unbuffered) 
per lo streaming dell'output in tempo reale. 
Questo permette un logging granulare 
e il monitoraggio "live" dello stato di generazione.



#######################

GenerateSong.py

#######################

NLP Pipeline: 

Esegue una pipeline sequenziale 
di chiamate alle API OpenAI: 
prima a un modello di riassunto 
(es. gpt-3.5-turbo), 
poi a un modello di generazione 
testi più potente (gpt-4o) per creare i lyrics.

Music Generation API Call: 

Invia i lyrics a un'API di generazione 
musicale di terze parti (KieAI/Suno).

Polling Robusto: 

Implementa un ciclo di polling con retry 
e backoff esponenziale 
per interrogare lo stato del job 
di generazione musicale, 
gestendo in modo resiliente 
errori di rete temporanei 
(ConnectionResetError) 
e stati di fallimento specifici dell'API 
(es. GENERATE_AUDIO_FAILED).

Gestione Risultati: 

Il worker archivia 
le trascrizioni usate 
o le mette in quarantena 
in caso di fallimento, 
e infine aggiunge i metadati 
della canzone completata 
(un oggetto JSON) 
a una coda di riproduzione 
basata su file (playlist.queue).


#######################

Riproduzione.py: 

#######################


Il Servizio di Output (Playback Service)

Scopo: 

Agire come il consumatore 
finale della pipeline, 
garantendo un flusso musicale 
continuo e senza interruzioni.

Logica Operativa: 
Pattern Consumatore FIFO: 

Implementa un semplice 
ma robusto consumatore First-In, First-Out. 
Monitora costantemente la playlist.queue.

Comunicazione Inter-Processo (IPC): 

Utilizza mpv come motore di riproduzione, 
controllandolo tramite socket IPC UNIX. 
Questo permette un controllo 
granulare e avanzato del player 
(volume, pausa, seek, ecc.) da Python.

Crossfade Avanzato: 

Quando una nuova canzone è pronta 
mentre un'altra è in riproduzione, 
il servizio orchestra un crossfade fluido. 

Lancia una seconda istanza di mpv 
su un socket IPC separato, 
ne imposta il volume a zero, 
e poi esegue un ciclo 
di fade-out sul player principale 
e fade-in su quello nuovo, 
decrementando e incrementando 
i rispettivi volumi tramite comandi IPC. 

Al termine, il vecchio processo mpv 
viene terminato.

Locking: 

Utilizza filelock per tutte le operazioni 
di lettura/scrittura sulla playlist.queue, 
garantendo operazioni atomiche 
e prevenendo race condition 
tra il Producer che scrive e il DJ che legge.
