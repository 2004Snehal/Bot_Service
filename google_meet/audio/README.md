# Audio System for Google Meet Bot

This directory contains the real-time audio input/output pipeline for the bot.

## Architecture

The system is designed to run inside the bot process and handle raw PCM audio streams.

### Components

1.  **`buffer.py`**: A circular ring buffer that stores the last 10 seconds of audio.
    *   `write(chunk)`: Adds new audio data.
    *   `read_all()`: Retrieves the full 10s history.
    *   `save_to_wav(path)`: Dumps buffer to disk for debugging.

2.  **`vad.py`**: Voice Activity Detection.
    *   Uses RMS (Root Mean Square) energy to detect if a human is speaking.
    *   Threshold is adjustable (default 0.01).

3.  **`input.py`**: Audio Capture.
    *   On Windows, attaches to the main FFmpeg recording process initiated by `bot.py`.
    *   Uses the `tee` muxer to simultaneously save a `.wav` file to disk and stream raw PCM to `stdout`.
    *   Reads PCM chunks from `stdout`.
    *   Updates `AudioState` (human_speaking, silence_start_time).
    *   Calls `process_audio_chunk` (hook for ASR).

4.  **`output.py`**: Audio Playback.
    *   Manages turn-taking logic.
    *   Plays `reply.wav` only if:
        *   No human is speaking.
        *   Silence has persisted for > 1.5 seconds.
        *   Bot has requested to speak.
    *   Uses `sounddevice` and `soundfile` libraries to play audio to the "CABLE Input" device.

## Setup

### Windows (Development)
You need **FFmpeg** installed and added to PATH.
You also need a Virtual Audio Cable (e.g., VB-Audio Cable).
You need to install Python audio libraries:
```bash
poetry add sounddevice soundfile numpy
```

**Input Command (Capture with Tee):**
```bash
ffmpeg -f dshow -i audio="CABLE Output (VB-Audio Virtual Cable)" -ac 1 -ar 16000 -f tee -map 0:a "[f=wav]out/file.wav|[f=s16le]-"
```

**Output (Playback):**
Playback is handled by Python's `sounddevice` library targeting "CABLE Input (VB-Audio Virtual Cable)".

### AWS / Linux (Production)
For Linux, you will need **PulseAudio** and `module-null-sink`.
Update `input.py` and `output.py` to use `-f pulse` instead of `-f dshow`.

## Usage

The system is initialized in `google_meet/bot.py`.

```python
from google_meet.audio.buffer import AudioRingBuffer
from google_meet.audio.input import AudioInput, AudioState
from google_meet.audio.output import AudioOutput
from google_meet.audio.vad import VAD

# Init
self.audio_state = AudioState()
self.vad = VAD()
self.audio_buffer = AudioRingBuffer(...)
self.audio_in = AudioInput(...)
self.audio_out = AudioOutput(...)

# Start
self.audio_in.start()

# Loop
self.audio_out.play_if_allowed()
```
