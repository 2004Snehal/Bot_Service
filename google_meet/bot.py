import os
import sys
import time
import json
import uuid
import logging
import requests
import platform
import subprocess
import soundfile as sf
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone
from threading import Event
from groq import Groq
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from .utils import create_tar_archive, audio_file_path
from .random_mouse import random_mouse_movements
from .audio.buffer import AudioRingBuffer
from .audio.input import AudioInput, AudioState
from .audio.output import AudioOutput
from .audio.vad import VAD
from .transcript import TranscriptExtractor

from monitoring import init_highlight, _send_failure_notification
from config import Settings


class JoinGoogleMeet:
    def __init__(
        self, 
        meetlink, 
        start_time_utc, 
        end_time_utc, 
        min_record_time=3600, 
        bot_name="Google Bot", 
        max_waiting_time=1800, 
        project_settings: Settings = None, 
        logger: logging = None, 
        system_prompt: str = None,
        enable_speak: bool = False  # New parameter for Pipecat voice
    ):
        self.meetlink = meetlink
        self.start_time_utc = start_time_utc
        self.end_time_utc = end_time_utc
        self.min_record_time = min_record_time
        self.bot_name = bot_name
        self.browser = None
        self.recording_started = False
        self.recording_start_time = None
        self.stop_event = Event()
        self.recording_process = None
        self.screen_recording_process = None
        self.file_recording_process = None
        self.recording_paused = False
        self.recording_segment_index = 1
        self.enable_speak = enable_speak
        self.id = str(uuid.uuid4())
        
        # S3 configuration (using IAM roles - no credentials needed)
        self.s3_bucket = os.getenv("S3_BUCKET_NAME")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.s3_client = None
        if self.s3_bucket:
            try:
                self.s3_client = boto3.client('s3', region_name=self.aws_region)
            except Exception as e:
                if logger:
                    logger.warning(f"Failed to initialize S3 client: {e}")
        
        # Temp directory for recording (will be uploaded to S3 and deleted)
        # Use /tmp/cuemeet by default to avoid polluting project directory
        self.temp_dir = "/tmp/cuemeet"
        os.makedirs(self.temp_dir, exist_ok=True)

        self.user_id = os.getenv("USER_ID")
        self.meeting_id = os.getenv("MEETING_ID")
        # Temp paths for recording (will be uploaded to S3)
        self.output_file = os.path.join(self.temp_dir, self.id)
        self.transcript_path = os.path.join(self.temp_dir, f"{self.meeting_id or self.id}_transcript.json")
        self.recording_path = os.path.join(self.temp_dir, f"{self.meeting_id or self.id}_recording.mp4")
        
        self.enable_recording = os.getenv("ENABLE_RECORDING", "False").lower() == "true"
        self.enable_transcript = os.getenv("ENABLE_TRANSCRIPT", "False").lower() == "true"
        self.event_start_time = None
        self.need_retry = False
        
        self.system_prompt = system_prompt or os.getenv("SYSTEM_PROMPT") or f"You are a helpful meeting assistant named {self.bot_name}. You are in a Google Meet call. Be concise and helpful."
        self.thread_start_time = None
        self.max_waiting_time = max_waiting_time
        self.session_ended = False
        self.project_settings = project_settings
        self.logger = logger
        try:
            # Suppress noisy binary frame debug logs from websocket libraries when enabled
            suppress_binary = os.getenv("SUPPRESS_BINARY_LOGS", "true").lower() == "true"
            if suppress_binary:
                for name in [
                    "websockets", "websockets.client", "websockets.protocol",
                    "websocket", "deepgram", "asyncio", "urllib3"
                ]:
                    logging.getLogger(name).setLevel(logging.WARNING)
                self.logger.info("🔇 Suppressed verbose websocket/deepgram debug logs")
        except Exception:
            pass
        
        # Connection pool size is now set at module level (top of file)

        self.highlight = init_highlight(self.project_settings.HIGHLIGHT_PROJECT_ID, self.project_settings.ENVIRONMENT_NAME, "google-meet-bot")

        self.groq_client = None
        if os.getenv("GROQ_API_KEY"):
            try:
                self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            except Exception as e:
                self.logger.error(f"Failed to init Groq: {e}")
        
        self.recent_messages = []
        self.conversation_summary = "Meeting just started."

        self.audio_state = AudioState()
        self.vad = VAD()
        self.audio_buffer = AudioRingBuffer(max_seconds=10, sample_rate=16000, bytes_per_sample=2, channels=1)
        
        # Initialize Pipecat speak handler if enabled
        self.speak_handler = None
        if self.enable_speak:
            try:
                from .speak import PipecatSpeakHandler
                
                groq_api_key = os.getenv("GROQ_API_KEY")
                deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
                
                if not groq_api_key or not deepgram_api_key:
                    self.logger.error("❌ Speak mode requires GROQ_API_KEY and DEEPGRAM_API_KEY")
                    self.enable_speak = False
                else:
                    self.speak_handler = PipecatSpeakHandler(
                        system_prompt=self.system_prompt,
                        groq_api_key=groq_api_key,
                        deepgram_api_key=deepgram_api_key,
                        audio_output_callback=self._handle_pipecat_audio
                    )
                    self.speak_handler.start()
                    self.logger.info("✅ Pipecat speak handler initialized and started")
            except ImportError as e:
                self.logger.error(f"❌ Failed to load Pipecat (install requirements_voice.txt): {e}")
                self.enable_speak = False
            except Exception as e:
                self.logger.error(f"❌ Failed to initialize speak handler: {e}")
                self.enable_speak = False
        
        # Initialize AudioInput for VAD in all modes
        # In speak mode, we still run the input reader to update AudioState (human_speaking/silence)
        self.audio_in = AudioInput(
            buffer=self.audio_buffer,
            audio_state=self.audio_state,
            vad=self.vad,
            system_prompt=self.system_prompt,
            bot_callback=None,
            device_name=os.getenv("AUDIO_INPUT_DEVICE_NAME", "audio=CABLE Output (VB-Audio Virtual Cable)")
        )
        self.logger.info("🕒 AudioInput prepared for VAD (will start after join)")
        
        self.audio_out = AudioOutput(
            audio_state=self.audio_state,
            wav_path=None,
            device_name=os.getenv("OUTPUT_DEVICE_NAME", "CABLE Input (VB-Audio Virtual Cable)"),
            on_interruption=self._handle_interruption_event,
            on_bot_speech=self._handle_bot_speech_event,
            speak_handler=self.speak_handler  # Pass speak handler to AudioOutput
        )

        # Force PulseAudio default recording source so Chrome/Meet captures our streamed audio
        try:
            if platform.system().lower().startswith("linux"):
                os.environ["PULSE_SOURCE"] = os.environ.get("PULSE_SOURCE", "BotMic.monitor")
                self.logger.info(f"🎙️ PULSE_SOURCE set to: {os.environ['PULSE_SOURCE']}")
        except Exception as e:
            self.logger.warning(f"⚠️ Could not set PULSE_SOURCE env: {e}")
        
        # Socket TTS removed - using Pipecat for voice
        self.transcript_extractor: TranscriptExtractor = None

    def _handle_interruption_event(self, msg):
        self.logger.info(f"🧠 Memory Update: {msg}")
        self.recent_messages.append(f"System: {msg}")
        if len(self.recent_messages) > 10:
            self.recent_messages.pop(0)

    def _handle_bot_speech_event(self, transcript: str, start_ms: int, end_ms: int):
        if self.transcript_extractor and transcript:
            self.transcript_extractor.add_bot_utterance(
                text=transcript,
                start_ms=start_ms,
                end_ms=end_ms
            )
            self.logger.info(f"📝 Bot speech logged to transcript: {transcript[:50]}...")
    
    def _handle_pipecat_audio(self, audio_data: bytes):
        """
        Callback for Pipecat audio data.
        Supports both raw PCM chunks and complete WAV files.
        """
        try:
            if not audio_data:
                return
            if len(audio_data) >= 4 and audio_data[:4] == b"RIFF":
                self.logger.info(f"📥 Pipecat WAV received: {len(audio_data)} bytes")
                self.audio_out.receive_pipecat_audio(audio_data)
            else:
                self.logger.info(f"🎵 Pipecat PCM chunk: {len(audio_data)} bytes")
                # If chunk-mode is in use and output supports streaming
                if hasattr(self.audio_out, "push_audio_chunk"):
                    self.audio_out.push_audio_chunk(audio_data)
                else:
                    # Fallback: wrap PCM into temporary WAV header for playback
                    import wave, io
                    buf = io.BytesIO()
                    with wave.open(buf, 'wb') as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(16000)
                        w.writeframes(audio_data)
                    self.audio_out.receive_pipecat_audio(buf.getvalue())
        except Exception as e:
            self.logger.error(f"Error handling Pipecat audio: {e}")

    def bot_handle_user_message(self, text):
        import threading
        threading.Thread(target=self._process_user_message, args=(text,)).start()

    def _process_user_message(self, text):
        self.logger.info(f"🎤 Bot heard (Deepgram transcription): {text}")
        # Intent logic removed; handled by socket

        if not hasattr(self, '_total_message_count'):
            self._total_message_count = 0
        self._total_message_count += 1
        
        self.recent_messages.append(f"User: {text}")
        if len(self.recent_messages) > 10:
            self.recent_messages.pop(0)
        
        should_update_summary = (self._total_message_count <= 10 or self._total_message_count % 10 == 0)
        
        if should_update_summary and self.groq_client:
            try:
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are a meeting summarizer. Keep it concise."},
                        {"role": "user", "content": f"Update Summary: {self.conversation_summary}\nMessages: {self.recent_messages}"}
                    ],
                    model="llama-3.1-8b-instant",
                )
                self.conversation_summary = chat_completion.choices[0].message.content
            except Exception as e:
                self.logger.error(f"Groq Error: {e}")
        
        # If Pipecat speak mode is enabled, send the message to the handler
        if self.enable_speak and self.speak_handler:
            self.logger.info(f"🗣️ Sending to Pipecat: {text}")
            self.speak_handler.process_transcript(text)
        
        # Old HTTP TTS call removed - handled by Socket Bridge
        # self.audio_out.send_context_to_tts(...)



    def setup_browser(self):
        options = Options()
        profile_path = os.path.abspath(os.path.join(os.getcwd(), f"CueMeetProfile_{self.id}"))
        options.add_argument(f"user-data-dir={profile_path}")
        ext_path = os.path.abspath(os.path.join(os.getcwd(), "transcript_extension"))
        options.add_argument(f"--load-extension={ext_path}")
    
        if platform.system().lower().startswith("linux"):
            pass 
        else:
            options.add_argument("--window-position=-2000,0")
            options.binary_location = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--disable-features=AudioServiceOutOfProcess")
        
        options.add_argument("--log-level=3")
        options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 2,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 2,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True
        })

        os.environ['WDM_LOG'] = '0'
        logging.getLogger('WDM').setLevel(logging.NOTSET)
        
        # Connection pool size is set at module level (top of file)
        
        try:
            browser_service = Service(ChromeDriverManager().install())
            self.browser = webdriver.Chrome(service=browser_service, options=options)
            self.logger.info("Browser launched successfully.")
        except Exception as e:
            self.logger.error(f"Failed to launch the browser: {e}")
            self.end_session()

    def navigate_to_meeting(self):
        self.logger.info(f"Navigating to Google Meet link: {self.meetlink}")
        try:
            self.browser.get(self.meetlink)
            self.logger.info("Successfully navigated to the Google Meet link.")
        except Exception as e:
            self.logger.error(f"Failed to navigate to the meeting link: {e}")
            self.end_session()
        
        random_mouse_movements(self, duration_seconds=10)

        try:
            modals = self.browser.find_elements(By.XPATH, '//button[@jsname="IbE0S"]')
            if modals:
                modals[0].click()
                self.logger.info("Closed the initial modal dialog successfully.")
            else:
                self.logger.info("No modal dialog found to close.")
        except Exception as e:
            self.logger.error(f"Failed to navigate to or interact with the meeting link: {e}")

    def join_meeting(self):
        self.logger.info("Attempting to disable microphone and camera.")
        try:
            self.logger.info(f"Current URL: {self.browser.current_url}")
            body_text = self.browser.find_element(By.TAG_NAME, "body").text
            if "Return to home screen" in body_text:
                self.logger.error("Bot is on the 'Return to home screen' page.")
            # Debug screenshots removed - using S3-only storage
        except Exception as e:
            self.logger.error(f"Failed to log debug info: {e}")

        time.sleep(2)
        try:
            camera_button = None
            selectors = [
                '//div[@aria-label="Turn off camera"]',
                '//div[@data-is-muted="false"][@role="button"]//i[contains(text(), "videocam")]/ancestor::div[@role="button"]',
                '//div[@role="button"][.//span[contains(@class, "material-icons-extended")][contains(text(), "videocam")]]'
            ]
            for selector in selectors:
                try:
                    camera_button = WebDriverWait(self.browser, 3).until(EC.element_to_be_clickable((By.XPATH, selector)))
                    if camera_button: break
                except: continue
            
            if camera_button:
                camera_button.click()
                self.logger.info("Camera disabled successfully.")
        except Exception as e:
            self.logger.error(f"Failed to disable camera: {e}")
        
        time.sleep(2)
        try: 
            name_input = None
            try:
                name_input = WebDriverWait(self.browser, 5).until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Your name']")))
            except TimeoutException:
                self.logger.info("Name input not found.")

            if name_input and name_input.is_displayed():
                name_input.clear()
                name_input.send_keys(self.bot_name)
                self.logger.info(f"Entered the bot name: {self.bot_name}")
                time.sleep(1) # Wait for button to enable
        except Exception as e:
            self.logger.error(f"Failed to enter the bot's name: {e}")

        try:
            join_button = None
            join_selectors = [
                '//span[contains(text(), "Ask to join")]', 
                '//span[contains(text(), "Join now")]',
                '//span[contains(text(), "Join meeting")]',
                '//button[.//span[contains(text(), "Join now")]]',
                '//button[.//span[contains(text(), "Ask to join")]]',
                '//button[.//span[contains(text(), "Join meeting")]]',
                '//button[contains(., "Join now")]',
                '//button[contains(., "Ask to join")]',
                '//button[contains(., "Join meeting")]'
            ]
            for selector in join_selectors:
                try:
                    join_button = WebDriverWait(self.browser, 5).until(EC.element_to_be_clickable((By.XPATH, selector)))
                    if join_button: break
                except: continue
            if join_button:
                join_button.click()
                self.logger.info(f"Clicked the Join button ({join_button.text}) successfully.")
        except Exception as e:
            self.logger.error(f"Failed to click Join button: {e}")
        
        time.sleep(4)

    def check_meeting_removal(self):        
        removed_text = self.browser.find_elements(By.XPATH, "//h1[contains(text(), 'been removed from the meeting')]")
        if removed_text:
            self.logger.info("Detected removal from meeting.")
            self.end_session()

    def check_meeting_end(self): 
        return_button = self.browser.find_elements(By.XPATH, "//span[contains(text(), 'Return to home screen')]")
        if return_button:
            self.logger.info("Detected 'Return to home screen' button. Meeting has ended.")
            if self.recording_started:
                self.end_session()
            else:
                self.need_retry = True
        
        ended_message = self.browser.find_elements(By.XPATH, "//span[contains(text(), 'The call ended because everyone left')]")
        if ended_message:
            self.logger.info("Detected 'The call ended because everyone left'.")
            self.end_session()

    def handle_waiting_modal(self):
        try:
            # Handle "Got it", "OK", or "Dismiss" buttons that block the UI
            popups = [
                "//span[contains(text(), 'Got it')]",
                "//span[contains(text(), 'OK')]",
                "//span[contains(text(), 'Dismiss')]",
                "//button[contains(., 'Got it')]",
                "//button[contains(., 'OK')]",
                "//button[contains(., 'Dismiss')]",
                "//div[@role='button'][contains(., 'Got it')]",
                "//div[@role='button'][contains(., 'Dismiss')]"
            ]
            for xpath in popups:
                try:
                    btns = self.browser.find_elements(By.XPATH, xpath)
                    for btn in btns:
                        if btn.is_displayed():
                            self.logger.info(f"Clicking popup button: {btn.text or xpath}")
                            btn.click()
                            time.sleep(1)
                except:
                    continue

            # Original "Are you still there?" logic
            try:
                modal_text = self.browser.find_elements(By.XPATH, "//div[contains(text(), 'Are you still there?')]")
                if modal_text:
                    self.logger.info("Detected 'Are you still there?' modal.")
                    keep_waiting_button = self.browser.find_element(By.XPATH, "//button[.//span[contains(text(), 'Keep waiting')]]")
                    keep_waiting_button.click()
            except:
                pass
        except Exception as e:
            self.logger.error(f"Failed to handle the waiting modal: {e}")

    def check_join_page(self):
        self.handle_waiting_modal()
        for classname in ['Jyj1Td', 'dHFSie']:
            try:
                text = self.browser.find_element(By.XPATH, f'//*[contains(@class, "{classname}")]').text.strip()
                if text: return text
            except: pass
        return ''

    def check_admission(self):
        admitted = self.browser.find_elements(By.XPATH, '//div[contains(@class, "u6vdEc")]')
        if admitted and not self.recording_started:
            self.logger.info("Admitted to the meeting. Starting recording...")
            self.start_recording()
            # Audio input disabled - using Google Meet captions instead
            # if not platform.system().lower().startswith("win"):
            #     self.audio_in.start()
        
        denied_message = self.browser.find_elements(By.XPATH, "//div[contains(text(), \"You can't join this call\")]")
        if denied_message:
            is_timeout = self.browser.find_elements(By.XPATH, "//div[contains(text(), \"No one responded\")]")
            if is_timeout:
                self.need_retry = True
            else: 
                self.end_session()

    def attendee_count(self):
        time.sleep(2)
        count = -1
        try: 
            element = WebDriverWait(self.browser, 10).until(EC.presence_of_element_located((By.XPATH, '//div[@class="gFyGKf BN1Lfc"]//div[@class="uGOf1d"]')))
            count_text = element.get_attribute('textContent').strip()
            if count_text.isdigit(): count = int(count_text)
        except: pass
        return count

    def start_recording(self):
        self.logger.info("Starting meeting audio recording with FFmpeg...")
        
        # Maximize window and go full screen to "record the window" better
        try:
            self.browser.maximize_window()
            time.sleep(1)
            # Send F11 to go full screen (hides URL bar and tabs)
            from selenium.webdriver.common.keys import Keys
            self.browser.find_element(By.TAG_NAME, "body").send_keys(Keys.F11)
            time.sleep(1)
        except:
            pass

        # Match the sink name defined in entrypoint.sh (MeetOutput)
        pulse_monitor = "MeetOutput.monitor" if platform.system().lower().startswith("linux") else "default"
        output_wav_file = f"{self.output_file}.wav"

        # Linux/WSL Specific Commands
        if platform.system().lower().startswith("linux"):
            # Audio-only recording (for transcription/backup)
            # file_command = ["ffmpeg", "-y", "-f", "pulse", "-i", pulse_monitor, "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", output_wav_file]
            # command = ["ffmpeg", "-y", "-f", "pulse", "-i", pulse_monitor, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
            
            # CRITICAL: Use DEVNULL for stderr to prevent process hanging when buffer fills
            # self.file_recording_process = subprocess.Popen(file_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.file_recording_process = None # Disabled local audio recording
            
            # Start VAD monitoring after admission
            if self.audio_in and not self.audio_in.running:
                try:
                    self.audio_in.start()
                    self.logger.info("✅ VAD monitor started after join")
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to start VAD monitor: {e}")
            
            self.recording_started = True
            self.recording_start_time = time.perf_counter()

            if self.enable_recording:
                # Use the canonical recording path for S3 upload
                video_file = self.recording_path
                # Screen recording with audio
                # Using libmp3lame for audio as it's very compatible
                screen_command = [
                    "ffmpeg", "-y", 
                    "-thread_queue_size", "1024",
                    "-f", "x11grab", 
                    "-framerate", "30", 
                    "-video_size", "1920x1080",
                    "-i", os.getenv("DISPLAY", ":99"), 
                    "-thread_queue_size", "1024",
                    "-f", "pulse", 
                    "-ac", "2", # Match sink channels
                    "-i", pulse_monitor,
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-pix_fmt", "yuv420p",
                    "-c:a", "libmp3lame", 
                    "-b:a", "128k", 
                    "-movflags", "+faststart",
                    video_file
                ]
                try:
                    # CRITICAL: Use DEVNULL for stderr to prevent process hanging
                    self.screen_recording_process = subprocess.Popen(
                        screen_command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    self.logger.info(f"✅ Screen recording started: {video_file}")
                except Exception as e:
                    self.logger.error(f"❌ Failed to start screen recording: {e}")
                
            if self.enable_transcript:
                # Use callback to send transcripts directly to Pipecat when speak mode enabled
                if self.enable_speak and self.speak_handler:
                    def on_transcript_callback(speaker: str, text: str):
                        """Callback when new transcript arrives from Google Meet captions."""
                        # Only process non-bot utterances
                        if speaker != self.bot_name and text.strip():
                            self.logger.info(f"📝 Google Meet Caption: {speaker}: {text}")
                            # Send directly to Pipecat without filtering
                            self.logger.info(f"🗣️ Sending to Pipecat: {text}")
                            self.speak_handler.process_transcript(text)
                    
                    self.transcript_extractor = TranscriptExtractor(
                        self.browser, 
                        self.bot_name, 
                        self.id,
                        on_transcript=on_transcript_callback
                    )
                    self.transcript_extractor.start()
                    self.logger.info("✅ Transcript extractor started (routing to Pipecat)")
                else:
                    # Just extract transcripts without processing
                    self.transcript_extractor = TranscriptExtractor(self.browser, self.bot_name, self.id)
                    self.transcript_extractor.start()
                    self.logger.info("✅ Transcript extractor started (recording only)")

    def pause_recording(self):
        """Pause recording by stopping FFmpeg processes without ending session."""
        if not self.recording_started or self.recording_paused:
            return
        self.logger.info("⏸️ Pausing recording due to empty meeting...")
        # Stop screen and file recording processes gracefully
        for name, proc in [("screen_rec", self.screen_recording_process), ("file_rec", self.file_recording_process)]:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                    self.logger.info(f"✅ {name} paused")
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self.screen_recording_process = None
        self.file_recording_process = None
        self.recording_paused = True

    def resume_recording(self):
        """Resume recording by restarting FFmpeg processes with a new segment."""
        if not self.recording_started or not self.recording_paused:
            return
        self.recording_segment_index += 1
        segment_suffix = f"_seg{self.recording_segment_index}"
        # Update base only for segment-specific files; transcript path remains meeting-scoped
        base = os.path.join(self.temp_dir, self.id + segment_suffix)
        self.logger.info("▶️ Resuming recording; starting new segment...")

        try:
            pulse_monitor = "MeetOutput.monitor" if platform.system().lower().startswith("linux") else "default"
            # output_wav_file = f"{base}.wav"
            # file_command = [
            #     "ffmpeg", "-y", "-f", "pulse", "-i", pulse_monitor,
            #     "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", output_wav_file
            # ]
            # self.file_recording_process = subprocess.Popen(file_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.file_recording_process = None
        except Exception as e:
            self.logger.error(f"❌ Failed to resume file recording: {e}")

        if self.enable_recording:
            try:
                video_file = f"{base}_recording.mp4"
                screen_command = [
                    "ffmpeg", "-y",
                    "-thread_queue_size", "1024",
                    "-f", "x11grab",
                    "-framerate", "30",
                    "-video_size", "1920x1080",
                    "-i", os.getenv("DISPLAY", ":99"),
                    "-thread_queue_size", "1024",
                    "-f", "pulse",
                    "-ac", "2",
                    "-i", pulse_monitor,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "libmp3lame",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                    video_file
                ]
                self.screen_recording_process = subprocess.Popen(screen_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.logger.info(f"✅ Screen recording resumed: {video_file}")
            except Exception as e:
                self.logger.error(f"❌ Failed to resume screen recording: {e}")

        self.recording_paused = False

    def stop_recording(self):
        self.logger.info("Stopping all recording processes...")
        processes = [
            ("audio_stream", self.recording_process), 
            ("screen_rec", self.screen_recording_process), 
            ("file_rec", self.file_recording_process)
        ]
        
        # 1. Send terminate to all first
        for name, proc in processes:
            if proc:
                self.logger.info(f"Terminating {name}...")
                try:
                    proc.terminate()
                except Exception as e:
                    self.logger.error(f"Error terminating {name}: {e}")

        # 2. Wait for all with a short timeout
        for name, proc in processes:
            if proc:
                try: 
                    proc.wait(timeout=3)
                    self.logger.info(f"✅ {name} stopped cleanly")
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"⚠️ {name} did not terminate, killing...")
                    try:
                        proc.kill()
                    except:
                        pass

        # Ensure ffmpeg has finished writing the MP4 header
        time.sleep(1)
        
        # Convert WAV to OPUS for upload - DISABLED (No local audio files)
        # wav_file = f"{self.output_file}.wav"
        # opus_file = f"{self.output_file}.opus"
        
        # if os.path.exists(wav_file) and not os.path.exists(opus_file):
        #     self.logger.info("Converting WAV to OPUS...")
        #     try:
        #         subprocess.run([
        #             "ffmpeg", "-y", "-i", wav_file, 
        #             "-c:a", "libopus", "-b:a", "32k", 
        #             opus_file
        #         ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        #         self.logger.info("✅ Conversion complete")
        #     except Exception as e:
        #         self.logger.error(f"❌ Conversion failed: {e}")

    def save_transcript(self):
        try:
            transcript_data = self.browser.execute_script("return localStorage.getItem('transcript');")
            chat_data = self.browser.execute_script("return localStorage.getItem('chatMessages');")
            title = self.browser.execute_script("return localStorage.getItem('meetingTitle');")
            transcript_json = {
                'title': title,
                'meeting_start_time': self.event_start_time.isoformat() if self.event_start_time else None,
                'meeting_end_time': datetime.now(timezone.utc).isoformat(),
                'transcript': json.loads(transcript_data) if transcript_data else None,
                'chat_messages': json.loads(chat_data) if chat_data else None,
                'user_id': self.user_id,
                'meeting_id': self.meeting_id,
            }
            # Save to temp path for S3 upload
            with open(self.transcript_path, 'w', encoding='utf-8') as f:
                json.dump(transcript_json, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving transcript: {e}")

    def upload_to_s3(self, file_path: str, s3_key: str, content_type: str) -> bool:
        """Upload a file directly to S3 using IAM roles."""
        if not self.s3_client or not self.s3_bucket:
            self.logger.warning("S3 not configured. Skipping upload.")
            return False
        
        try:
            self.logger.info(f"Uploading {file_path} to S3: s3://{self.s3_bucket}/{s3_key}")
            self.s3_client.upload_file(
                file_path,
                self.s3_bucket,
                s3_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'Metadata': {
                        'user_id': self.user_id or '',
                        'meeting_id': self.meeting_id or '',
                        'upload_time': datetime.utcnow().isoformat()
                    }
                }
            )
            self.logger.info(f"✅ Successfully uploaded to S3: {s3_key}")
            return True
        except ClientError as e:
            self.logger.error(f"S3 upload failed for {s3_key}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error uploading to S3: {e}")
            return False

    def upload_files(self):
        """Upload all meeting files to S3 and clean up temp files."""
        if not self.meeting_id:
            self.logger.warning("No meeting_id set. Cannot upload to S3.")
            return
        
        try:
            # Upload recording (MP4 video)
            recording_path = self.recording_path
            if os.path.exists(recording_path):
                s3_key = f"meetings/meet_{self.meeting_id}/video/recording.mp4"
                if self.upload_to_s3(recording_path, s3_key, "video/mp4"):
                    try:
                        os.remove(recording_path)  # Clean up temp file
                        self.logger.info(f"Deleted local recording: {recording_path}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete local recording: {e}")
            
            # Upload transcript (JSON)
            if os.path.exists(self.transcript_path):
                s3_key = f"meetings/meet_{self.meeting_id}/transcript/transcript.json"
                if self.upload_to_s3(self.transcript_path, s3_key, "application/json"):
                    try:
                        os.remove(self.transcript_path)  # Clean up temp file
                        self.logger.info(f"Deleted local transcript: {self.transcript_path}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete local transcript: {e}")
            
            # Upload metadata
            metadata_path = os.path.join(self.temp_dir, f"{self.meeting_id}_metadata.json")
            try:
                metadata = {
                    'meeting_id': self.meeting_id,
                    'user_id': self.user_id,
                    'bot_name': self.bot_name,
                    'start_time': self.event_start_time.isoformat() if self.event_start_time else None,
                    'end_time': datetime.now(timezone.utc).isoformat(),
                    'upload_time': datetime.utcnow().isoformat()
                }
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                s3_key = f"meetings/meet_{self.meeting_id}/metadata/meeting.json"
                if self.upload_to_s3(metadata_path, s3_key, "application/json"):
                    try:
                        os.remove(metadata_path)  # Clean up temp file
                        self.logger.info(f"Deleted local metadata: {metadata_path}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete local metadata: {e}")
            except Exception as e:
                self.logger.error(f"Error creating/uploading metadata: {e}")
                
        except Exception as e:
            self.logger.error(f"Upload error: {e}")

    def end_session(self):
        if self.session_ended: return
        self.session_ended = True
        self.logger.info("Ending session...")
        
        # Stop Pipecat speak handler if enabled
        if self.enable_speak and self.speak_handler:
            try:
                self.speak_handler.stop()
                self.logger.info("✅ Pipecat speak handler stopped")
            except Exception as e:
                self.logger.error(f"Error stopping speak handler: {e}")
        
        # Stop transcript extractor to ensure it saves its data
        if self.enable_transcript and self.transcript_extractor:
            try:
                self.transcript_extractor.stop()
                # Save to meeting-scoped path
                self.transcript_extractor.save_transcript(self.transcript_path)
            except Exception as e:
                self.logger.error(f"Error stopping transcript extractor: {e}")
        
        # Save legacy transcript if needed
        if self.browser and self.recording_started:
            try:
                self.save_transcript()
            except Exception as e:
                self.logger.error(f"Error saving legacy transcript: {e}")
        
        # Stop audio input
        if hasattr(self, 'audio_in') and self.audio_in: 
            try:
                self.audio_in.stop()
            except Exception as e:
                self.logger.error(f"Error stopping audio input: {e}")
        
        # Stop recording processes
        if self.recording_started:
            try:
                self.stop_recording()
                self.upload_files()
            except Exception as e:
                self.logger.error(f"Error stopping recording: {e}")
            
        # Quit browser
        if self.browser: 
            try:
                self.browser.quit()
            except:
                pass
                
        self.stop_event.set()
        self.logger.info("✅ Session ended gracefully.")

    def monitor_meeting(self, initial_elapsed_time=0):
        start_time = time.perf_counter() - initial_elapsed_time
        low_member_count_end_time = None
        while not self.stop_event.is_set():
            current_time = time.perf_counter()
            elapsed = current_time - start_time
            if not self.recording_started and elapsed > self.max_waiting_time: break
            if self.recording_started and (current_time - self.recording_start_time) > self.min_record_time: break
            if self.need_retry: break

            try:
                self.check_meeting_end()
                self.check_meeting_removal()
                self.handle_waiting_modal() # Check for popups like "Got it"
                if not self.recording_started: self.check_admission()
                if self.recording_started:
                    self.audio_out.play_if_allowed()
                    members = self.attendee_count()
                    # Only act on known counts; ignore unknown (-1)
                    if members > 1:
                        # Reset timer and resume if paused
                        if low_member_count_end_time is not None:
                            self.logger.info("👥 Participants detected; cancelling empty-room timer.")
                        low_member_count_end_time = None
                        if self.recording_paused:
                            self.resume_recording()
                    elif members != -1:
                        if low_member_count_end_time is None:
                            low_member_count_end_time = current_time + 120  # 2 minutes
                            self.pause_recording()
                            self.logger.info("⏳ No participants; will exit if still empty after 2 minutes.")
                        elif current_time > low_member_count_end_time:
                            self.logger.info("🚪 Empty for 2 minutes — exiting meeting.")
                            break
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
            time.sleep(2)

    def retry_join(self):
        self.logger.info("Retrying...")
        time.sleep(12)
        self.browser.refresh()
        self.navigate_to_meeting()
        self.join_meeting()

    def run(self):
        try:
            self.setup_browser()
            self.navigate_to_meeting()
            self.join_meeting()
            self.thread_start_time = time.perf_counter()
            while True:
                self.monitor_meeting(initial_elapsed_time=(time.perf_counter() - self.thread_start_time))
                if self.need_retry:
                    self.need_retry = False
                    self.retry_join()
                else: break
        except Exception as e:
            self.logger.error(f"Run error: {e}")
        finally:
            self.end_session()