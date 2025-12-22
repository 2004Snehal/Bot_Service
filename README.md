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
DEEPGRAM_API_KEY=your_key
GROQ_API_KEY=your_key
TTS_MICROSERVICE_URL=http://localhost:8000/generate-audio
```

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

## 🐳 Docker Setup (Linux/Production)

For production deployment, the bot runs in Docker with a fully virtualized audio stack using PulseAudio.

### Quick Start
```bash
# Build the image
docker build -t cuemeet-bot .

# Run with a meeting link
docker run --rm -v "$(pwd)/out:/app/out" --shm-size=2g cuemeet-bot "https://meet.google.com/xxx-yyyy-zzz"
```

### Audio Architecture (Docker)
The Docker container creates two virtual audio devices:
- **MeetOutput**: Chrome plays meeting audio here → FFmpeg records it → Bot hears
- **BotMic → VirtualMic**: Bot plays audio here → Chrome uses as microphone → Meeting hears

This prevents audio feedback loops.

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