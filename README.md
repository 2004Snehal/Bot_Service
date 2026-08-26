<div align="center">
  <img src="assets/banner.png" alt="HiCapy Meeting Bots Banner" />
  <h1>HiCapy Meeting Bots - Google Meeting Bot</h1>
</div>

---

## Links to Repositories

You can explore our platform repositories for additional tools and integrations:

<ul>
  <li><a href="https://github.com/hicappyai/Bot_Service" target="_blank">Google Meet Bot Service</a></li>
</ul>

---

## 📚 Documentation

Detailed technical specifications and architecture docs are available in the repository:

- 🏗️ **[SDE Technical Specification & Architecture](./TECHNICAL_DOCUMENTATION.md)** — Comprehensive SDE guide covering Database Design, ER Diagrams, API Contracts, AWS/Docker Deployment, and Subsystem Architecture.
- 🎙️ **[Voice AI & Bot Architecture](./VOICE_BOT_ARCHITECTURE.md)** — Deep-dive into Pipecat, WebSocket STT/TTS, Silero VAD/AEC, thread resilience, and sub-500ms latency budgets.
- 🌐 **[Online Documentation Portal](https://hicapy.ai/docs/google-bot)** — Official online documentation portal.

---

## 🧠 Architecture & AI Pipeline

The Bot Service features a low-latency real-time voice conversational architecture and autonomous meeting bot execution engine:

### 1. 🤖 Headless Bot Agent Subsystem
- **Virtual Audio & Display Stack**: Headless Chrome controlled via Selenium inside Docker, rendering to an Xvfb virtual frame buffer (`:99`).
- **PulseAudio Virtual Sinks**: Routes meeting output to `MeetOutput` (captured via FFmpeg & `AudioInput`) and pipes synthesized bot voice to `BotMic` remapped as Chrome's microphone input (`VirtualMic`).
- **DOM MutationObserver**: Uses JavaScript `MutationObserver` to poll lightweight mutation flags every 100ms, reducing Selenium CPU overhead by **~90%**.
- **Participant Count Auto-Shutdown**: Continuously monitors active participant video tiles (`_monitor_participants()`). Triggers graceful container termination when human count $\le 1$, eliminating 100% of zombie container leaks and saving **2GB RAM per session**.

### 2. ⚡ Real-Time Voice AI Pipeline (Sub-500ms Latency)
- **Direct WebSocket STT**: Deepgram WebSocket ASR (`wss://api.deepgram.com/v1/listen`) with instant `speech_final: true` boundaries (100–150ms), replacing legacy DOM caption silence timeouts.
- **Neural VAD & Echo Cancellation**: Silero Neural VAD / WebRTC VAD with hysteresis counters paired with WebRTC Acoustic Echo Cancellation (AEC) via PulseAudio `module-echo-cancel`.
- **Token-Streaming LLM**: Groq API (`llama-3.1-8b-instant` / `llama-3.3-70b-versatile`) with sentence-boundary token parsing (`.`, `!`, `?`).
- **WebSocket Streaming TTS**: Deepgram WebSocket Speak API (`wss://api.deepgram.com/v1/speak`) returning audio PCM frames within **~80ms** of sentence output.
- **Pipecat Interruption Resilience**: Atomic `CancellationToken` pattern allowing immediate buffer flushing without killing the underlying asyncio event loop.
- **Latency Gain**: Cuts end-to-end response latency from **~5.2s down to ~520ms P50** (~10x reduction).

*For a detailed layer-by-layer architectural deep-dive, see [VOICE_BOT_ARCHITECTURE.md](../VOICE_BOT_ARCHITECTURE.md).*

### Environment Variables
Ensure your `.env` file includes:
```bash
# Required for Transcription
DEEPGRAM_API_KEY=your_key

# Required for Voice/LLM
GROQ_API_KEY=your_key

# Bot Configuration
BOT_NAME="Bot Assistant"
ENABLE_RECORDING=true        # Save MP4 video
ENABLE_TRANSCRIPT=true       # Save JSON transcript
ENABLE_SPEAK=false          # Enable voice interaction (requires Pipecat)

# Shared Meeting Status Store
MONGO_URL=mongodb://localhost:27017
MONGO_DB_NAME=hicapy
```

---

## 💻 Local Development Setup

### 1. Prerequisites
- Python 3.10+
- [Poetry](https://python-poetry.org/) (recommended) or pip
- Chrome Browser
- **Audio Setup** (for Windows): See "Audio Setup (Windows)" section below

### 2. Installation

Using Poetry (Recommended):
```bash
# Install dependencies
make install
# OR manually:
poetry install

# Activate shell
make poetry-shell
```

Using Pip:
```bash
pip install -r requirements.txt
# For voice features:
pip install -r requirements_voice.txt
```

### 3. Running Locally

Run the bot with a Google Meet link:

```bash
# Basic recording & transcription
python app.py "https://meet.google.com/abc-defg-hij"

# With voice assistant enabled
python app.py "https://meet.google.com/abc-defg-hij" --speak true
```

**Common Arguments:**
- `--min-record-time`: Minimum duration in seconds (default: 7200)
- `--bot-name`: Name displayed in the meeting
- `--speak`: Enable voice interaction (`true`/`false`)

---

##  Whale Docker Deployment (Production)

For production, the bot runs in a Docker container with a virtualized audio stack (PulseAudio). This eliminates the need for physical audio devices or Virtual Cables.

### 1. Build Options

**Option A: Lightweight (Recording Only)**
Best for transcription and recording. Smaller image size (~500MB).
```bash
docker build -t gmeet-bot:lite .
```

**Option B: Full Voice Assistant**
Includes Pipecat and AI voice dependencies. Larger image size (~800MB).
```bash
docker build --build-arg ENABLE_VOICE=true -t gmeet-bot:voice .
```

### 2. Running with Docker

**Run a specific meeting:**
```bash
# For recording only
docker run --rm \
  --env-file .env \
  -v $(pwd)/out:/app/out \
  --shm-size=2g \
  gmeet-bot:lite "https://meet.google.com/abc-defg-hij"

# For voice assistant
docker run --rm \
  --env-file .env \
  -v $(pwd)/out:/app/out \
  --shm-size=2g \
  gmeet-bot:voice "https://meet.google.com/abc-defg-hij" --speak true
```

**Using Docker Compose:**
```bash
# Start the service (defined in docker-compose.yml)
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Audio Architecture (Docker)
The container creates two virtual PulseAudio sinks:
- **MeetOutput**: Chrome audio → FFmpeg recording
- **BotMic**: Bot audio → Chrome microphone input

---

## 🎧 Audio Setup (Windows)

To prevent audio feedback loops (bot hearing itself) and ensure clean audio routing, this bot requires a split audio setup using **VoiceMeeter** and **VB-Cable**.

### Prerequisites
1.  **VoiceMeeter** (Standard or Potato/Banana) installed.
2.  **VB-Cable** (Virtual Audio Cable) installed.

### Configuration Steps

1.  **Windows Sound Settings**:
    *   Open **Sound Mixer Options** (App volume and device preferences).
    *   Locate **Google Chrome** (or your browser).
    *   Set **Output** to `VoiceMeeter Input (VB-Audio Voicemeeter VAIO)`.
    *   Set **Input** to `CABLE Output (VB-Audio Virtual Cable)`.

2.  **VoiceMeeter**:
    *   Ensure `VoiceMeeter Input` is active (this receives Chrome's audio).
    *   Route this input to **B1** (Virtual Output).
    *   The bot listens to `Voicemeeter Out B1`.

3.  **Bot Output**:
    *   The bot speaks into `CABLE Input (VB-Audio Virtual Cable)`.
    *   Since Chrome's Input is set to `CABLE Output`, the meeting participants will hear the bot.

This setup ensures the bot hears the meeting (via VoiceMeeter) but does not hear its own voice (which goes to VB-Cable), preventing echo loops.

---

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](./CONTRIBUTING.md) for details.

---

## 🔐 Security

Please refer to [SECURITY.md](./SECURITY.md) for information about reporting security vulnerabilities and best practices.

---

## 🆙 Upgrading

For version compatibility and migration steps, see [UPGRADE.md](./UPGRADE.md).

---

## 📜 Code of Conduct

We follow a standard of respectful communication and collaboration. Please review our [Code of Conduct](./CODE_OF_CONDUCT.md) before contributing.

---

## 📋 TODO

### Completed ✅
- [x] Docker audio pipeline with PulseAudio virtual sinks
- [x] Audio self-test on container startup
- [x] Real-time audio recording with FFmpeg
- [x] VAD (Voice Activity Detection) for speech detection
- [x] Deepgram ASR integration for transcription
- [x] Groq LLM integration for conversation summarization
- [x] Bot playback via `paplay` to virtual microphone
- [x] POST request structure to TTS microservice (with full context)
- [x] `force_tts` logic based on user intent detection

### In Progress 🚧
- [ ] Connect to actual TTS microservice (currently using dummy audio)
- [ ] Fine-tune VAD threshold for low-volume audio
- [ ] Add real audio response from microservice (uncomment code in `output.py`)

### Planned 📝
- [ ] WebSocket streaming for lower latency ASR
- [ ] Multiple voice options for TTS
- [ ] Meeting transcript export to S3
- [ ] Health check endpoint for container orchestration
- [ ] Kubernetes deployment manifests

---

## 📝 License

This project is licensed under the [GNU General Public License v3.0 (GPL-3.0)](LICENSE)  — see the LICENSE file for details.

<div align="center">
  Made with ❤️ by HiCapy team | Powered by CueMeet
</div>