BARBARD is an end-to-end, asynchronous, multi-process data processing pipeline designed to transform raw audio input (conversations) into original musical compositions using AI.

#################
Features
#################

Automatic Audio Ingestion: Monitors a specific folder for new .wav files and handles file stability checks to ensure data integrity.

AI Transcription: Utilizes OpenAI Whisper to convert raw audio into text.

Song Generation: Creates lyrics based on the transcriptions (via GPT-4o) and generates full musical tracks (via Suno/KieAI API).

Producer-Consumer Architecture: A resilient system built with queues, atomic locking mechanisms, and multi-process management to handle high concurrency.

Smart Playback: FIFO playback engine with automatic crossfading managed via mpv IPC sockets.

#################
System Requirements
#################

Python 3.8+

mpv (Media Player): This is required for the playback service and must be installed at the system level.

Ubuntu/Debian: sudo apt install mpv

macOS: brew install mpv

Windows: Install mpv and ensure it is added to your system PATH.

#################
Installation
#################

Clone the repository:

code
Bash
download
content_copy
expand_less
git clone https://github.com/liuk000/BARBARD.git
cd BARBARD

Install Python dependencies:

code
Bash
download
content_copy
expand_less
pip install -r requirements.txt

Configure the environment:

Rename the provided example file .env.example to .env.

Open .env and enter your API Keys (OpenAI and KieAI/Suno) and customize configuration parameters.

Usage Setup:

The system monitors the FROM_TABLES folder (created automatically on first run).

Note: Audio files placed here must have a numeric prefix (e.g., 5-recording.wav) to identify the source "table" or ID.

#################
Execution
#################

The system consists of 3 distinct services that must run concurrently. You should open 3 separate terminal windows:

Ingestion Service (Watchdog):
Monitors for files and handles transcription.

code
Bash
download
content_copy
expand_less
python AudioWatchdog.py

Processing Core (Producer):
Manages the job queue and orchestrates AI workers.

code
Bash
download
content_copy
expand_less
python Producer.py

Playback Service (DJ):
Plays the generated songs with a dashboard interface.

code
Bash
download
content_copy
expand_less
python Riproduzione.py

#################
Architecture Overview
#################

AudioWatchdog.py: The entry point. It watches the input folder, handles file locking to prevent partial reads, calls the Whisper API, and stages the text for processing.

Producer.py: The core manager. It assigns jobs to worker processes using a fair scheduling algorithm to ensure no source is starved. It manages the GenerateSong.py subprocesses.

GenerateSong.py: The worker unit. It takes the text, summarizes it, generates lyrics, and calls the Music Generation API. It handles polling and error retries.

Riproduzione.py: The consumer. It reads the playlist queue safely and controls the mpv player via UNIX IPC sockets to perform smooth crossfades between tracks.

#################
License
#################

MIT License