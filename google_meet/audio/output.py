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
        
        # Real-time PCM streaming for Pipecat (no file queue)
        self.stream_active = False
        self.stream_lock = threading.Lock()
        self.pcm_buffer = []  # Buffer for incoming PCM frames
        self.stream_sample_rate = int(os.getenv("PIPECAT_SAMPLE_RATE", "16000"))  # Default 16kHz
        self.stream_channels = 1  # Mono
        self.stream_process = None
        self.stream_thread = None

        # Output tuning
        try:
            self.output_gain = float(os.getenv("OUTPUT_GAIN", "1.0"))
        except Exception:
            self.output_gain = 1.0
        
        self.current_sink = None
        self.current_source = None
        
        self._log_available_devices()
        
        if self.speak_mode:
            logger.info(f"🎤 AudioOutput in SPEAK MODE (Pipecat PCM streaming @ {self.stream_sample_rate}Hz)")
            # Register callback with Pipecat to receive PCM frames
            if self.speak_handler:
                self.speak_handler.audio_output_callback = self.receive_pipecat_pcm
        else:
            logger.info("🔇 AudioOutput in LEGACY MODE (Socket/Microservice)")

    def _log_available_devices(self):
        pass

    def request_speak(self):
        """Flag that bot has something to say."""
        self.bot_wants_to_speak = True

    def receive_pipecat_pcm(self, pcm_data: bytes, sample_rate: int = None):
        """
        Callback from Pipecat - receives raw PCM audio frames for streaming.
        Streams directly to audio output without saving to disk.
        
        Args:
            pcm_data: Raw PCM audio bytes (S16LE format expected)
            sample_rate: Sample rate of the audio (if different from default)
        """
        if not pcm_data:
            return
            
        # Update sample rate if provided
        if sample_rate and sample_rate != self.stream_sample_rate:
            logger.warning(f"⚠️ Sample rate mismatch! Expected {self.stream_sample_rate}, got {sample_rate}")
            self.stream_sample_rate = sample_rate
        
        with self.stream_lock:
            # Start streaming on first frame
            if not self.stream_active:
                logger.info(f"🎵 Starting PCM stream @ {self.stream_sample_rate}Hz, {len(pcm_data)} bytes")
                self.stream_active = True
                self.bot_wants_to_speak = True
                self._speech_start_ms = int(time.time() * 1000)
                
                # Start playback thread
                self.stream_thread = threading.Thread(target=self._stream_pcm_playback, daemon=True)
                self.stream_thread.start()
            
            # Add frame to buffer
            self.pcm_buffer.append(pcm_data)
    
    def _stream_pcm_playback(self):
        """Stream PCM audio directly to output device as frames arrive."""
        logger.info("🚀 PCM streaming thread started")
        
        # Wait for silence before starting playback
        logger.info("⏳ Waiting for silence to start Pipecat stream...")
        while True:
            if not self.audio_state.human_speaking:
                now = time.time()
                silence_duration = 0
                if self.audio_state.silence_start_time:
                    silence_duration = now - self.audio_state.silence_start_time
                
                if silence_duration > 1.0:  # Shorter wait for streaming
                    break
            
            time.sleep(0.05)
        
        self.is_playing = True
        
        try:
            if platform.system().lower().startswith("linux"):
                self._stream_pcm_linux()
            else:
                self._stream_pcm_windows()
        except Exception as e:
            logger.error(f"❌ PCM streaming failed: {e}", exc_info=True)
        finally:
            self.is_playing = False
            with self.stream_lock:
                self.stream_active = False
                self.pcm_buffer.clear()
            logger.info("✅ PCM streaming finished")
    
    def _stream_pcm_linux(self):
        """Stream PCM to PulseAudio on Linux."""
        try:
            # Set up PulseAudio
            subprocess.run(["pactl", "set-sink-mute", "BotMic", "0"], check=False)
            subprocess.run(["pactl", "set-sink-volume", "BotMic", "100%"], check=False)
            
            # Start pacat process
            cmd = [
                "pacat",
                "--format=s16le",
                f"--rate={self.stream_sample_rate}",
                f"--channels={self.stream_channels}",
                "--device=BotMic",
                "--latency-msec=50"  # Lower latency for streaming
            ]
            
            logger.info(f"🚀 Starting pacat: {' '.join(cmd)}")
            self.stream_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Set default source
            try:
                sources_output = subprocess.run(
                    ["pactl", "list", "short", "sources"],
                    capture_output=True,
                    text=True
                ).stdout
                
                desired_source = None
                if "BotMic.monitor" in sources_output:
                    desired_source = "BotMic.monitor"
                elif "MeetOutput.monitor" in sources_output:
                    desired_source = "MeetOutput.monitor"
                    
                if desired_source:
                    subprocess.run(["pactl", "set-default-source", desired_source], check=False)
                    logger.info(f"🎙️ Default source set to: {desired_source}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to adjust default source: {e}")
            
            logger.info(f"📡 Streaming PCM: rate={self.stream_sample_rate}Hz, channels={self.stream_channels}")
            
            # Stream frames as they arrive
            frames_sent = 0
            while True:
                # Get next frame from buffer
                pcm_frame = None
                with self.stream_lock:
                    if self.pcm_buffer:
                        pcm_frame = self.pcm_buffer.pop(0)
                    elif not self.stream_active:
                        # No more frames and stream ended
                        break
                
                if pcm_frame:
                    try:
                        # Apply output gain if needed
                        if self.output_gain != 1.0:
                            # Convert to numpy for gain
                            audio_array = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32)
                            audio_array = audio_array / 32768.0  # Normalize to -1.0 to 1.0
                            audio_array = np.clip(audio_array * self.output_gain, -1.0, 1.0)
                            pcm_frame = (audio_array * 32767).astype(np.int16).tobytes()
                        
                        self.stream_process.stdin.write(pcm_frame)
                        self.stream_process.stdin.flush()
                        frames_sent += 1
                        
                        # Check for interruption
                        if self.stop_requested:
                            logger.info(f"🛑 Streaming interrupted after {frames_sent} frames")
                            break
                            
                    except BrokenPipeError:
                        logger.error("❌ pacat process died unexpectedly")
                        break
                else:
                    # Wait for more frames
                    time.sleep(0.01)
            
            logger.info(f"📊 Streamed {frames_sent} PCM frames to pacat")
            
        finally:
            if self.stream_process:
                try:
                    self.stream_process.stdin.close()
                    self.stream_process.wait(timeout=2)
                except Exception:
                    self.stream_process.kill()
                self.stream_process = None
    
    def _stream_pcm_windows(self):
        """Stream PCM to sounddevice on Windows."""
        try:
            # Find output device
            device_id = None
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if self.device_name in dev['name'] and dev['max_output_channels'] > 0:
                    device_id = i
                    break
            
            if device_id is None:
                logger.warning(f"Device '{self.device_name}' not found. Using default.")
            else:
                logger.info(f"Streaming to device: {devices[device_id]['name']} (ID: {device_id})")
            
            logger.info(f"📡 Streaming PCM: rate={self.stream_sample_rate}Hz, channels={self.stream_channels}")
            
            blocksize = 2048
            
            with sd.OutputStream(
                samplerate=self.stream_sample_rate,
                channels=self.stream_channels,
                device=device_id,
                blocksize=blocksize,
                dtype='int16'
            ) as stream:
                frames_sent = 0
                
                while True:
                    # Get next frame from buffer
                    pcm_frame = None
                    with self.stream_lock:
                        if self.pcm_buffer:
                            pcm_frame = self.pcm_buffer.pop(0)
                        elif not self.stream_active:
                            break
                    
                    if pcm_frame:
                        # Convert bytes to numpy array
                        audio_array = np.frombuffer(pcm_frame, dtype=np.int16)
                        
                        # Apply gain if needed
                        if self.output_gain != 1.0:
                            audio_float = audio_array.astype(np.float32) / 32768.0
                            audio_float = np.clip(audio_float * self.output_gain, -1.0, 1.0)
                            audio_array = (audio_float * 32767).astype(np.int16)
                        
                        # Ensure stereo if needed
                        if self.stream_channels == 1 and len(audio_array.shape) == 1:
                            audio_array = np.column_stack((audio_array, audio_array))
                        
                        stream.write(audio_array)
                        frames_sent += 1
                        
                        # Check for interruption
                        if self.stop_requested:
                            logger.info(f"🛑 Streaming interrupted after {frames_sent} frames")
                            break
                    else:
                        # Wait for more frames
                        time.sleep(0.01)
                
                logger.info(f"📊 Streamed {frames_sent} PCM frames to sounddevice")
                
        except Exception as e:
            logger.error(f"❌ Windows PCM streaming error: {e}", exc_info=True)

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
        
        # Stop PCM streaming
        with self.stream_lock:
            if self.stream_active:
                self.stream_active = False
                logger.info("🛑 Stopping PCM stream")

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