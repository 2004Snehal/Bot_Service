<div align="center">
  <img src="https://i.postimg.cc/FRLZLSSF/Banner.png" alt="Meeting Bots Control Panel Banner" />
  <h1>CueMeet Meeting Bots - Google Meeting Bot</h1>
</div>

---

## Links to CueMeet Repositories

You can explore all our repositories for additional tools and integrations:

<ul>
  <li><a href="https://github.com/CueMeet/cuemeet-documentation" target="_blank">CueMeet Docs</a></li>
  <li><a href="https://github.com/CueMeet/Meeting-Bots-Control-Panel" target="_blank">CueMeet Control Panel</a></li>
  <li><a href="https://github.com/CueMeet/cuemeet-google-bot" target="_blank">Google Meet Bot</a></li>
    <li><a href="https://github.com/CueMeet/cuemeet-teams-bot" target="_blank">Ms Teams Bot</a></li>
    <li><a href="https://github.com/CueMeet/cuemeet-zoom-bot" target="_blank">Zoom Meet Bot</a></li>
</ul>

---

## 📚 Documentation

Detailed documentation is available in the [docs](https://cuemeet.github.io/cuemeet-documentation/docs/google-bot) directory:

---

## 🧠 Architecture & AI Pipeline

This bot features an advanced real-time audio pipeline:

1.  **Audio Input**: Captures system audio via FFmpeg and Virtual Audio Cable.
2.  **VAD & STT**: Uses Voice Activity Detection to trigger Deepgram ASR for real-time transcription.
3.  **Memory & Summarization**: 
    *   Maintains a sliding window of the last 10 messages.
    *   Uses **Groq (Llama 3)** to continuously summarize the conversation context.
4.  **Intelligent TTS**: 
    *   Instead of generating replies locally, the bot sends the full context (System Prompt, Summary, Recent Messages) to an external **Intelligent TTS Microservice**.
    *   The microservice is responsible for generating the appropriate verbal response and returning the audio.

### Environment Variables
Ensure your `.env` file includes:
```bash
# Required for Transcription
DEEPGRAM_API_KEY=your_key

# Required for Voice/LLM
GROQ_API_KEY=your_key

# Bot Configuration
BOT_NAME="CueMeet Assistant"
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
  Made with ❤️ by CueCard.ai team
</div>