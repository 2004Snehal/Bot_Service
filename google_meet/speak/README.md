# Pipecat Speak Module

Optional voice assistant integration using the Pipecat framework.

## Overview

This module provides streaming voice capabilities:
- **LLM**: Groq streaming responses (llama-3.3-70b-versatile)
- **TTS**: Deepgram streaming text-to-speech
- **Audio Output**: Direct to virtual microphone (no external microservices)

## Architecture

```
Meeting Transcript
    ↓
PipecatSpeakHandler
    ├── Groq LLM (streaming)
    ├── Deepgram TTS (streaming)
    └── Audio Output → Virtual Mic → Meeting
```

## Requirements

### Environment Variables
```bash
GROQ_API_KEY=your_groq_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
```

### Dependencies
Install with:
```bash
pip install -r google_meet/speak/requirements_voice.txt
```

Or build Docker with voice support:
```bash
docker build --build-arg ENABLE_VOICE=true -t bot-with-voice .
```

## Usage

### Command Line
```bash
python app.py "https://meet.google.com/xxx-xxxx-xxx" --speak true
```

### Docker
```bash
docker run bot-with-voice \
  -e GROQ_API_KEY=xxx \
  -e DEEPGRAM_API_KEY=xxx \
  "https://meet.google.com/xxx-xxxx-xxx" \
  --speak true
```

## How It Works

1. **Transcript Capture**: Meeting audio → Deepgram STT → Text
2. **Context Building**: Recent messages + system prompt
3. **LLM Streaming**: Text → Groq → Streaming response
4. **TTS Streaming**: LLM text → Deepgram → Streaming audio
5. **Audio Output**: Audio chunks → Virtual mic → Meeting

## Performance

### Without Speak (--speak false)
- **Image Size**: ~500MB
- **Memory**: ~300MB
- **Use Case**: Recording + transcription only

### With Speak (--speak true)
- **Image Size**: ~800MB
- **Memory**: ~600MB
- **Use Case**: Interactive voice assistant

## Files

- `__init__.py` - Module exports
- `pipecat_handler.py` - Main Pipecat integration
- `requirements_voice.txt` - Voice-specific dependencies
- `README.md` - This file

## Configuration

### System Prompt
Set via `--bot-name` or `SYSTEM_PROMPT` env variable:
```bash
export SYSTEM_PROMPT="You are a helpful meeting assistant. Be concise."
```

### LLM Model
Default: `llama-3.3-70b-versatile`

Modify in bot.py initialization:
```python
self.speak_handler = PipecatSpeakHandler(
    model="mixtral-8x7b-32768"  # Change model here
)
```

## Troubleshooting

### Import Error
```
ImportError: Pipecat not installed
```
**Solution**: Install voice dependencies or build with `ENABLE_VOICE=true`

### API Key Missing
```
❌ Speak mode requires GROQ_API_KEY and DEEPGRAM_API_KEY
```
**Solution**: Set environment variables

### Audio Not Playing
- Check PulseAudio configuration (Linux)
- Verify virtual cable setup (Windows)
- Check logs for TTS errors

## Development

### Testing Locally
```bash
# Install dependencies
pip install -r requirements-socket.txt
pip install -r google_meet/speak/requirements_voice.txt

# Run with speak enabled
python app.py "https://meet.google.com/test" --speak true
```

### Debugging
Enable verbose logging:
```python
import logging
logging.getLogger('pipecat').setLevel(logging.DEBUG)
```

## Limitations

- Requires both Groq and Deepgram API keys
- Adds ~300MB to Docker image
- Increases memory usage by ~300MB
- Not compatible with Socket TTS microservice (mutually exclusive)

## Future Enhancements

- [ ] Support for multiple LLM providers
- [ ] Voice activity detection (VAD) integration
- [ ] Real-time audio interruption handling
- [ ] WebRTC transport for lower latency
- [ ] Custom TTS voices per bot instance
