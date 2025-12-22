import time
import logging
import subprocess
import os
import requests
import json
import tempfile
import uuid
import sounddevice as sd
import soundfile as sf
import numpy as np
import platform
import threading
from typing import Optional
from .input import AudioState

logger = logging.getLogger(__name__)

class AudioOutput:
    def __init__(
        self, 
        audio_state: AudioState, 
        wav_path: str = None, 
        device_name: str = "CABLE Input (VB-Audio Virtual Cable)", 
        on_interruption=None, 
        on_bot_speech=None,
        speak_handler=None  # Optional PipecatSpeakHandler
    ):
        self.audio_state = audio_state
        self.wav_path = wav_path
        # Allow runtime override for output device on Windows
        env_dev = os.getenv("OUTPUT_DEVICE_NAME")
        self.device_name = env_dev if env_dev else device_name
        self.on_interruption = on_interruption
        self.on_bot_speech = on_bot_speech
        self.bot_wants_to_speak = False
        self.last_play_time = 0
        self.is_playing = False
        
        # Pipecat integration
        self.speak_handler = speak_handler
        self.speak_mode = speak_handler is not None
        
        # Playback control
        self.stop_requested = False
        self.pause_requested = False
        self.current_audio_data = None
        self.current_sample_rate = None
        self.playback_position = 0
        self.current_transcript = None
        self._speech_start_ms = None
        
        # WAV file queue for Pipecat (receives complete WAV files)
        self.wav_queue = []
        self.wav_queue_lock = threading.Lock()
        self.processing_wav = False

        # Output tuning
        try:
            self.output_gain = float(os.getenv("OUTPUT_GAIN", "1.0"))
        except Exception:
            self.output_gain = 1.0
        
        self.current_sink = None
        self.current_source = None
        
        self._log_available_devices()
        
        if self.speak_mode:
            logger.info("🎤 AudioOutput in SPEAK MODE (Pipecat integration - WAV file mode)")
            # Register callback with Pipecat to receive WAV files
            if self.speak_handler:
                self.speak_handler.audio_output_callback = self.receive_pipecat_audio
        else:
            logger.info("🔇 AudioOutput in LEGACY MODE (Socket/Microservice)")

    def _log_available_devices(self):
        pass

    def request_speak(self):
        """Flag that bot has something to say."""
        self.bot_wants_to_speak = True

    def receive_pipecat_audio(self, audio_data: bytes):
        """
        Callback from Pipecat - receives complete WAV file as bytes.
        Queue it for playback.
        """
        logger.info(f"📥 Received audio from Pipecat: {len(audio_data)} bytes")
        
        # Save to temp file
        temp_dir = tempfile.gettempdir()
        filename = f"pipecat_audio_{uuid.uuid4()}.wav"
        filepath = os.path.join(temp_dir, filename)
        
        try:
            with open(filepath, "wb") as f:
                f.write(audio_data)
            
            logger.info(f"💾 Saved Pipecat audio to: {filepath}")
            
            # Add to queue
            with self.wav_queue_lock:
                self.wav_queue.append(filepath)
            
            # Signal that bot wants to speak
            self.bot_wants_to_speak = True
            
            # Start processing queue if not already processing
            if not self.processing_wav:
                threading.Thread(target=self._process_wav_queue, daemon=True).start()
                
        except Exception as e:
            logger.error(f"❌ Failed to save Pipecat audio: {e}")

    def _process_wav_queue(self):
        """Process queued WAV files from Pipecat."""
        self.processing_wav = True
        
        while True:
            # Get next file from queue
            with self.wav_queue_lock:
                if not self.wav_queue:
                    self.processing_wav = False
                    break
                filepath = self.wav_queue.pop(0)
            
            # Wait for silence before playing
            logger.info("⏳ Waiting for silence to play Pipecat audio...")
            while True:
                if not self.audio_state.human_speaking:
                    now = time.time()
                    silence_duration = 0
                    if self.audio_state.silence_start_time:
                        silence_duration = now - self.audio_state.silence_start_time
                    
                    if silence_duration > 1.5:
                        break
                
                time.sleep(0.1)
            
            # Play the file
            logger.info(f"▶️ Playing Pipecat audio: {filepath}")
            self.wav_path = filepath
            self.is_playing = True
            
            try:
                self._play_audio()
            finally:
                self.is_playing = False
                # Clean up temp file
                try:
                    os.remove(filepath)
                    logger.info(f"🗑️ Cleaned up: {filepath}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp file: {e}")

    def send_context_to_tts(self, bot_id, system_prompt, summary, recent_messages, user_message, force_tts=False):
        """
        Route to either Pipecat (speak mode) or microservice (legacy mode).
        
        Args:
            bot_id: Unique identifier for this bot session
            system_prompt: The bot's personality/role definition
            summary: LLM-generated summary of the conversation so far
            recent_messages: List of last N messages for context
            user_message: The latest transcribed user speech (from Deepgram)
            force_tts: If True, microservice MUST generate audio response
        """
        if self.speak_mode:
            # Use Pipecat for streaming LLM + TTS
            logger.info("🎤 Routing to Pipecat speak handler...")
            self._handle_with_pipecat(user_message)
        else:
            # Use legacy microservice
            logger.info("🎙️ Starting single-step microservice flow (Audio Only)...")
            audio_file, transcript = self._call_generate_audio(
                bot_id, system_prompt, summary, recent_messages, user_message, force_tts
            )
            
            if audio_file:
                self.wav_path = audio_file
                self.current_transcript = transcript
                self.bot_wants_to_speak = True
            else:
                logger.info("🔇 Bot decided not to speak or error occurred.")
    
    def _handle_with_pipecat(self, user_message: str):
        """Handle transcript processing with Pipecat."""
        if not self.speak_handler:
            logger.error("Speak handler not initialized!")
            return
        
        # Send transcript to Pipecat - it handles LLM + TTS streaming
        # Audio will come back via receive_pipecat_audio callback
        self.speak_handler.process_transcript(user_message)
        
        logger.info("✅ Transcript sent to Pipecat for processing")

    def _call_generate_audio(self, bot_id, system_prompt, summary, recent_messages, user_message, force_tts=False):
        """
        ENDPOINT: POST /generate-audio
        
        Request:
        {
            "bot_id": "123",
            "system_prompt": "...",
            "summary_memory": "...",
            "recent_messages": [...],
            "user_message": "...",
            "voice": "default",
            "force_tts": false
        }
        
        Response:
            - 200 OK + audio/wav body (PCM S16LE, mono, 16kHz) + x-transcript header
            - 204 No Content = Don't speak
        """
        url = os.getenv("TTS_MICROSERVICE_URL", "http://localhost:8000/generate-audio")
        
        payload = {
            "bot_id": bot_id,
            "system_prompt": system_prompt,
            "summary_memory": summary,
            "recent_messages": recent_messages,
            "user_message": user_message,
            "voice": "default",
            "force_tts": force_tts
        }
        
        logger.info("=" * 60)
        logger.info("📤 POST /generate-audio")
        logger.info("=" * 60)
        logger.info(f"   URL: {url}")
        logger.info("=" * 60)
        
        try:
            response = requests.post(
                url, 
                json=payload, 
                timeout=30,
                headers={"Content-Type": "application/json"}
            )
            
            logger.info(f"📥 TTS Response: Status {response.status_code}")
            
            if response.status_code == 204:
                logger.info("   Microservice decided NOT to speak (204 No Content).")
                return None, None
            
            if response.status_code == 200:
                logger.info(f"   Response Content-Type: {response.headers.get('Content-Type', 'unknown')}")
                logger.info(f"   Response Size: {len(response.content)} bytes")
                
                transcript = response.headers.get("x-transcript", "")
                logger.info(f"   📝 Transcript Header: {transcript[:100]}...")

                temp_dir = tempfile.gettempdir()
                filename = f"bot_reply_{uuid.uuid4()}.wav"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(response.content)
                    
                logger.info(f"   ✅ Audio saved to: {filepath}")
                return filepath, transcript
            
            logger.error(f"   ❌ Microservice error: {response.status_code}")
            logger.error(f"   Response: {response.text[:500]}")
            return None, None
                
        except requests.exceptions.ConnectionError as e:
            logger.error(f"   ❌ Microservice not reachable: {e}")
            logger.error("   Cannot generate audio - microservice is required")
            return None, None
            
        except requests.exceptions.Timeout:
            logger.error("   ❌ Microservice timeout (30s)")
            return None, None
            
        except Exception as e:
            logger.error(f"   ❌ TTS Generation failed: {e}")
            return None, None

    def stop(self):
        """Stop playback immediately."""
        self.stop_requested = True
        self.is_playing = False

    def pause(self):
        """Pause playback to be resumed later."""
        self.pause_requested = True
        self.is_playing = False

    def resume(self):
        """Resume playback from paused position."""
        if self.current_audio_data is not None:
            self.stop_requested = False
            self.pause_requested = False
            self.is_playing = True
            logger.info("Resuming playback...")
            self._play_audio(resume=True)

    def play_filler(self, filler_name="ack_right.wav"):
        """Play a filler audio immediately (blocking for simplicity or short duration).
        
        Available fillers:
            urgent_checking.wav - "Okay, let me check that first."
            urgent_one_sec.wav - "One second, let me address that."
            urgent_clarifying.wav - "Hold on, I'll clarify that right now."
            defer_noted.wav - "Noted. I'll get to that in a moment."
            defer_pin_that.wav - "Let's pin that, I'll answer it after this."
            defer_after_this.wav - "Good point, I'll cover that next."
            ack_right.wav - "Right."
            ack_yeah.wav - "Yeah."
            ack_cool.wav - "That's cool."
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filler_path = os.path.join(base_dir, "assets", "fillers", filler_name)
        
        if not os.path.exists(filler_path):
            logger.warning(f"Filler file not found: {filler_path}")
            return
        
        if platform.system().lower().startswith("linux"):
            try:
                logger.info(f"Playing filler via paplay: {filler_path}")
                subprocess.run(["paplay", "--device=BotMic", filler_path], check=False)
            except Exception as e:
                logger.error(f"Failed to play filler via paplay: {e}")
            return

        try:
            data, fs = sf.read(filler_path)
            device_id = None
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if self.device_name in dev['name'] and dev['max_output_channels'] > 0:
                    device_id = i
                    break
            
            if len(data.shape) == 1:
                data = np.column_stack((data, data))
                
            logger.info(f"Playing filler: {filler_path}")
            sd.play(data, fs, device=device_id)
            sd.wait()
        except Exception as e:
            logger.error(f"Failed to play filler: {e}")

    def play_if_allowed(self):
        """
        If:
            - audio_state.human_speaking == False
            - silence > 1.5 seconds
            - bot wants to speak
        Then play reply.wav via sounddevice.
        """
        if self.is_playing:
            return

        if not self.bot_wants_to_speak:
            return

        if self.audio_state.human_speaking:
            return

        now = time.time()
        silence_duration = 0
        if self.audio_state.silence_start_time:
            silence_duration = now - self.audio_state.silence_start_time
        
        if silence_duration > 1.5:
            logger.info(f"Silence detected ({silence_duration:.1f}s). Bot starting playback.")
            self.is_playing = True
            try:
                self._play_audio()
            finally:
                self.is_playing = False
            self.last_play_time = time.time()

    def _play_audio(self, resume=False):
        """Play the WAV file to the virtual microphone."""
        if not self.wav_path and not resume:
            logger.warning("No audio file to play (wav_path is None)")
            return
            
        if not resume and not os.path.exists(self.wav_path):
            logger.error(f"Audio file not found: {self.wav_path}")
            return

        if not resume:
            try:
                data, fs = sf.read(self.wav_path)
                duration = len(data) / fs
                max_amp = np.max(np.abs(data)) if len(data) > 0 else 0
                logger.info(f"🎵 Audio Analysis: {self.wav_path}")
                logger.info(f"   Sample Rate: {fs} Hz")
                logger.info(f"   Channels: {data.shape[1] if len(data.shape) > 1 else 1}")
                logger.info(f"   Duration: {duration:.2f} seconds")
                logger.info(f"   Max Amplitude: {max_amp:.4f}")
                
                if max_amp < 0.01:
                    logger.warning("⚠️ Audio appears to be silent or very quiet!")
                
                self.current_audio_data = data
                self.current_sample_rate = fs
                self.playback_position = 0
                
                self._speech_start_ms = int(time.time() * 1000)
            except Exception as e:
                logger.error(f"Failed to analyze audio file: {e}")
                return

        try:
            if platform.system().lower().startswith("linux"):
                try:
                    subprocess.run(["pactl", "set-sink-mute", "BotMic", "0"], check=False)
                    subprocess.run(["pactl", "set-sink-volume", "BotMic", "100%"], check=False)
                except Exception:
                    pass

                logger.info(f"Playing via pacat (streaming)...")
                self.stop_requested = False
                self.pause_requested = False
                
                data = self.current_audio_data
                fs = self.current_sample_rate
                channels = data.shape[1] if len(data.shape) > 1 else 1
                
                try:
                    cmd = ["pacat", "--format=s16le", f"--rate={fs}", f"--channels={channels}", "--device=BotMic", "--latency-msec=100"]
                    
                    logger.info(f"🚀 Starting pacat: {' '.join(cmd)}")
                    self.paplay_process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                    # Ensure Chrome/Meet records from our sink monitor (default source)
                    try:
                        sources_output = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True).stdout
                        desired_source = None
                        if "BotMic.monitor" in sources_output:
                            desired_source = "BotMic.monitor"
                        elif "MeetOutput.monitor" in sources_output:
                            desired_source = "MeetOutput.monitor"
                        if desired_source:
                            subprocess.run(["pactl", "set-default-source", desired_source], check=False)
                            logger.info(f"🎙️ Default source set to: {desired_source}")
                        logger.info(f"📡 Output route: sink=BotMic, source={desired_source or 'unchanged'}, rate={fs}, channels={channels}, gain={self.output_gain}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to adjust default source: {e}")
                    
                    chunk_size = int(fs * 0.1)
                    total_samples = len(data)
                    
                    # Apply output gain if configured
                    if self.output_gain != 1.0:
                        try:
                            data = np.clip(data * self.output_gain, -1.0, 1.0)
                            logger.info(f"🔊 Applied output gain: {self.output_gain}")
                        except Exception as e:
                            logger.warning(f"Failed to apply gain: {e}")
                    
                    while self.playback_position < total_samples:
                        if self.stop_requested:
                            logger.info("🛑 Playback stopped by request.")
                            if self.current_transcript:
                                percent_played = (self.playback_position / total_samples) * 100
                                interruption_msg = f"[INTERRUPTED: Bot spoke {percent_played:.1f}% of: '{self.current_transcript}']"
                                logger.info(f"🛑 {interruption_msg}")
                                if self.on_interruption:
                                    self.on_interruption(interruption_msg)
                            
                            self.playback_position = 0
                            break
                            
                        if self.pause_requested:
                            logger.info("⏸️ Playback paused by request.")
                            break
                            
                        end_idx = min(self.playback_position + chunk_size, total_samples)
                        chunk = data[self.playback_position : end_idx]
                        
                        chunk = np.clip(chunk, -1.0, 1.0)
                        chunk_int16 = (chunk * 32767).astype(np.int16)
                        
                        try:
                            self.paplay_process.stdin.write(chunk_int16.tobytes())
                            self.paplay_process.stdin.flush()
                        except BrokenPipeError:
                            logger.error("pacat process died unexpectedly")
                            break
                            
                        self.playback_position = end_idx
                        
                    if self.paplay_process:
                        self.paplay_process.stdin.close()
                        self.paplay_process.wait()
                        self.paplay_process = None
                        
                    if self.playback_position >= total_samples:
                        logger.info("✅ Playback finished (pacat).")
                        if self.on_bot_speech and self.current_transcript:
                            end_ms = int(time.time() * 1000)
                            self.on_bot_speech(self.current_transcript, self._speech_start_ms, end_ms)
                        self.bot_wants_to_speak = False
                        self.current_transcript = None
                        self.playback_position = 0

                except Exception as e:
                    logger.error(f"pacat streaming failed: {e}")
                    if self.paplay_process:
                        self.paplay_process.kill()
                return

            # Windows / Local Logic (sounddevice)
            data = self.current_audio_data
            fs = self.current_sample_rate
            
            device_id = None
            devices = sd.query_devices()
            logger.info("🔎 Enumerating output devices...")
            for i, dev in enumerate(devices):
                if self.device_name in dev['name'] and dev['max_output_channels'] > 0:
                    device_id = i
                    break
            
            if device_id is None:
                logger.warning(f"Device '{self.device_name}' not found. Playing to default device.")
            else:
                logger.info(f"Playing to device: {devices[device_id]['name']} (ID: {device_id})")
            logger.info(f"📡 Output route: device={self.device_name}, rate={fs}, channels={data.shape[1] if len(data.shape)>1 else 1}, gain={self.output_gain}")

            if len(data.shape) == 1:
                data = np.column_stack((data, data))

            # Apply output gain
            if self.output_gain != 1.0:
                data = np.clip(data * self.output_gain, -1.0, 1.0)

            blocksize = 2048
            channels = data.shape[1]
            
            self.stop_requested = False
            self.pause_requested = False
            
            total_samples = len(data)
            
            with sd.OutputStream(samplerate=fs, channels=channels, device=device_id, blocksize=blocksize) as stream:
                while self.playback_position < len(data):
                    if self.stop_requested:
                        logger.info("Playback stopped by request.")
                        if self.current_transcript:
                            percent_played = (self.playback_position / total_samples) * 100
                            interruption_msg = f"[INTERRUPTED: Bot spoke {percent_played:.1f}% of: '{self.current_transcript}']"
                            logger.info(f"🛑 {interruption_msg}")
                            
                            if self.on_interruption:
                                self.on_interruption(interruption_msg)
                        
                        self.playback_position = 0
                        break
                    
                    if self.pause_requested:
                        logger.info("Playback paused by request.")
                        break
                    
                    end_idx = min(self.playback_position + blocksize, len(data))
                    chunk = data[self.playback_position : end_idx]
                    stream.write(chunk)
                    self.playback_position = end_idx
            
            if self.playback_position >= len(data):
                logger.info("✅ Playback finished.")
                if self.on_bot_speech and self.current_transcript:
                    end_ms = int(time.time() * 1000)
                    self.on_bot_speech(self.current_transcript, self._speech_start_ms, end_ms)
                self.bot_wants_to_speak = False
                self.current_transcript = None

        except Exception as e:
            logger.error(f"Playback failed: {e}")