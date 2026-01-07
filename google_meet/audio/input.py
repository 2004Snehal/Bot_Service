import subprocess
import threading
import time
import logging
import os
import platform
import audioop # ✅ Added for RMS calculation
import io
import wave

# Initialize logger BEFORE imports that might fail
logger = logging.getLogger(__name__)

# Deepgram is optional - only used if bot_callback is provided (which it's not in current setup)
try:
    from deepgram import DeepgramClient
    try:
        # Try SDK v3+ path first
        from deepgram.clients.live import LiveOptions, LiveTranscriptionEvents
    except ImportError:
        try:
            # Try alternate v3+ path
            from deepgram.live import LiveOptions, LiveTranscriptionEvents
        except ImportError:
            # SDK v2 path
            from deepgram import LiveOptions, LiveTranscriptionEvents
    DEEPGRAM_AVAILABLE = True
    logger.info("✅ Deepgram SDK loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ Deepgram SDK not available: {e}")
    DEEPGRAM_AVAILABLE = False
    DeepgramClient = None
    LiveOptions = None
    LiveTranscriptionEvents = None

from .buffer import AudioRingBuffer
from .vad import VAD

class AudioState:
    def __init__(self):
        self.human_speaking = False
        self.last_speech_time = 0.0
        self.silence_start_time = time.time()

class AudioInput:
    def __init__(self, buffer: AudioRingBuffer, audio_state: AudioState, vad: VAD, system_prompt: str, bot_callback=None, device_name: str = "audio=Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)"):
        self.buffer = buffer
        self.audio_state = audio_state
        self.vad = vad
        self.system_prompt = system_prompt
        self.bot_callback = bot_callback
        self.device_name = device_name
        self.process = None
        self.running = False
        self.thread = None
        self.dg_thread = None  # Thread for Deepgram connection
        
        # Deepgram & ASR Buffer
        self.deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
        self.deepgram_client = None
        self.dg_connection = None
        self._dg_connected = False
        
        if self.deepgram_api_key:
            try:
                self.deepgram_client = DeepgramClient(api_key=self.deepgram_api_key)
                logger.info("✅ Deepgram client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to init Deepgram: {e}")
        else:
            logger.warning("⚠️ DEEPGRAM_API_KEY not found in environment variables")
        
        self.asr_buffer = bytearray()
        self.silence_timeout_ms = 400 # 400ms silence triggers ASR
        self.last_speech_time = 0.0

    def attach_process(self, process):
        """Attach to an existing FFmpeg process."""
        self.process = process

    def _on_message(self, *args, **kwargs):
        """Callback for Deepgram Streaming results."""
        try:
            # In v3, the result is passed as the first argument or in kwargs
            message = kwargs.get("result") if "result" in kwargs else (args[1] if len(args) > 1 else None)
            if not message:
                return
            
            # Access the transcript from the v3 response structure
            channel = getattr(message, "channel", None)
            if channel:
                alternatives = getattr(channel, "alternatives", [])
                if alternatives and len(alternatives) > 0:
                    sentence = getattr(alternatives[0], "transcript", "")
                    if len(sentence) == 0:
                        return
                    
                    is_final = getattr(message, "is_final", False)
                    
                    if is_final:
                        logger.info(f"📝 [Deepgram Final]: {sentence}")
                        if self.bot_callback:
                            self.bot_callback(sentence)
                    else:
                        # Optional: Log interim results for debugging
                        logger.debug(f"   [Interim]: {sentence}")
                
        except Exception as e:
            logger.error(f"Error processing Deepgram message: {e}")

    def _on_error(self, *args, **kwargs):
        error = kwargs.get("error") if "error" in kwargs else (args[1] if len(args) > 1 else "Unknown error")
        logger.error(f"Deepgram Error: {error}")
        # Mark as disconnected so reader loop knows
        self._dg_connected = False

    def _deepgram_connection_thread(self):
        """Run Deepgram WebSocket connection in a separate thread with auto-reconnect."""
        retry_delay = 2  # seconds
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        # Keep reconnecting as long as we're running
        while self.running:
            try:
                logger.info(f"🔌 Deepgram connecting... (failures: {consecutive_failures})")
                
                # v3 API: Use listen.live.v("1")
                options = LiveOptions(
                    model="nova-2",
                    language="en",
                    smart_format=True,
                    encoding="linear16",
                    channels=1,
                    sample_rate=24000,
                    interim_results=True,
                    vad_events=True,
                    punctuate=True
                )
                
                connection = self.deepgram_client.listen.live.v("1")
                
                # Register event handlers
                connection.on(LiveTranscriptionEvents.Transcript, self._on_message)
                connection.on(LiveTranscriptionEvents.Error, self._on_error)
                connection.on(LiveTranscriptionEvents.Open, lambda *args, **kwargs: logger.info("✅ Deepgram WebSocket Connected!"))
                connection.on(LiveTranscriptionEvents.Close, lambda *args, **kwargs: logger.info("🔌 Deepgram WebSocket Closed"))
                
                if connection.start(options):
                    self.dg_connection = connection
                    self._dg_connected = True
                    consecutive_failures = 0  # Reset on successful connection
                    retry_delay = 2  # Reset delay
                    
                    logger.info("✅ Deepgram listener active")
                    
                    # Keep thread alive while connection is active
                    while self._dg_connected and self.running:
                        time.sleep(0.5)
                else:
                    logger.error("Failed to start Deepgram connection")
                    consecutive_failures += 1
                    
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Deepgram connection error: {e}")
                
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(f"❌ Deepgram failed {max_consecutive_failures} times, giving up")
                    break
                    
            finally:
                self._dg_connected = False
                self.dg_connection = None
            
            # Wait before reconnecting (if still running)
            if self.running:
                logger.info(f"⏳ Reconnecting Deepgram in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 30)  # Gradual backoff, max 30s

    def start(self):
        """Start reader thread (assumes process is already attached or spawns one)."""
        if self.running:
            return

        self.running = True
        
        # Initialize Deepgram Streaming Connection ONLY if bot_callback is provided
        # When bot_callback=None, we only use this for VAD monitoring
        if self.deepgram_client and self.bot_callback:
            logger.info("🔌 Starting Deepgram Streaming connection...")
            self.dg_thread = threading.Thread(target=self._deepgram_connection_thread, daemon=True)
            self.dg_thread.start()
            
            # Wait a moment for connection to establish
            time.sleep(1)
        else:
            if not self.bot_callback:
                logger.info("⏩ Skipping Deepgram STT (bot_callback=None, VAD-only mode)")
            else:
                logger.warning("⚠️ Deepgram client not available")

        if not self.process:
            # FFmpeg command to capture audio
            if platform.system().lower().startswith("linux"):
                command = [
                    "ffmpeg",
                    "-y",
                    "-f", "pulse",
                    "-i", "MeetOutput.monitor",
                    "-ac", "1",
                    "-ar", str(self.buffer.sample_rate),
                    "-f", "s16le",
                    "-bufsize", "4096",
                    "-"
                ]
            else:
                # Windows dshow
                command = [
                    "ffmpeg",
                    "-y", 
                    "-f", "dshow",
                    "-i", self.device_name,
                    "-ac", "1",
                    "-ar", str(self.buffer.sample_rate),
                    "-f", "s16le",
                    "-bufsize", "4096", 
                    "-"
                ]
            
            logger.info(f"Starting Audio Input with command: {' '.join(command)}")

            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, # Hide ffmpeg logs
                    bufsize=4096
                )
            except Exception as e:
                logger.error(f"Failed to start audio input: {e}")
                self.running = False
                return

        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.process:
            self.process.terminate()
            self.process = None

    def _reader_loop(self):
        """Read chunks → buffer.write() → VAD → process_audio_chunk."""
        chunk_size = 4096 # Adjust based on latency needs
        
        # Debug counter to avoid spamming logs
        debug_counter = 0
        
        while self.running and self.process:
            try:
                chunk = self.process.stdout.read(chunk_size)
                if not chunk:
                    break
                
                # ✅ DEBUG: Check audio levels every ~2 seconds (assuming 16k rate, 4k chunk ~ 0.12s)
                debug_counter += 1
                rms = 0  # Initialize rms for later use
                if debug_counter % 20 == 0:
                    try:
                        rms = audioop.rms(chunk, 2)
                        norm = rms / 32767.0
                        logger.info(f"[VAD Level] RMS={rms}, Norm={norm:.6f}, Thresh={self.vad.threshold}")
                    except Exception:
                        pass

                # 1. Write to Ring Buffer
                self.buffer.write(chunk)
                
                # 2. Run VAD
                is_speech = self.vad.is_speaking(chunk)
                now = time.time()
                
                # 3. Update State (VAD only - no transcription)
                if is_speech:
                    # Log when speech is first detected
                    if not self.audio_state.human_speaking:
                        logger.debug("🗣️ Speech detected (VAD)")
                    
                    self.audio_state.human_speaking = True
                    self.audio_state.last_speech_time = now
                    self.audio_state.silence_start_time = None
                    
                else:
                    if self.audio_state.silence_start_time is None:
                         self.audio_state.silence_start_time = now
                    
                    # If silence > 0.5s (short pause), we can consider human stopped speaking
                    if now - self.audio_state.last_speech_time > 0.5:
                        if self.audio_state.human_speaking:
                            logger.debug("🔇 Silence detected (VAD)")
                        self.audio_state.human_speaking = False

            except Exception as e:
                logger.error(f"Error in audio reader loop: {e}")
                break

    def _run_asr_and_clear(self):
        """Legacy REST ASR - Not used in Streaming mode."""
        pass

    def process_audio_chunk(self, chunk_bytes, system_prompt):
        """
        Hook for future ASR/LLM processing.
        Currently returns 'dummy'.
        """
        return "dummy"
