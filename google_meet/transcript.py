"""
Transcript Extractor for Google Meet - FIXED VERSION
====================================================
Prevents duplicate storage by only saving finalized utterances.
Separates real-time processing from storage.

Key Changes:
1. Only store finalized utterances (no progressive updates)
2. Separate callbacks for real-time (Pipecat) vs storage
3. Debounce speaker changes to prevent false splits
"""

import json
import time
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List, Callable
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


class TranscriptEvent:
    """Single transcript event with speaker attribution."""
    
    def __init__(
        self,
        speaker: str,
        text: str,
        source: str = "captions",
        role: str = "human",
        speaker_id: str = None,
        confidence: float = 0.95,
        start_ms: int = None
    ):
        self.id = f"evt_{uuid.uuid4().hex[:8]}"
        self.speaker = speaker
        self.speaker_id = speaker_id or f"p_{uuid.uuid4().hex[:4]}"
        self.role = role  # "human" or "bot"
        self.text = text
        self.start_ms = start_ms or int(time.time() * 1000)
        self.end_ms = None
        self.source = source
        self.confidence = confidence
        self.last_update_ms = int(time.time() * 1000)
    
    def finalize(self, end_ms: int = None):
        """Mark event as complete."""
        self.end_ms = end_ms or int(time.time() * 1000)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "speaker": self.speaker,
            "speaker_id": self.speaker_id,
            "role": self.role,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "source": self.source,
            "confidence": self.confidence
        }


class TranscriptExtractor:
    """
    Extracts and manages meeting transcripts with speaker attribution.
    
    TWO CALLBACKS:
    - on_utterance_finalized: Called once per complete utterance (for storage + Pipecat)
    - on_progress_update: (Optional) Called on every caption update (for live UI)
    
    Usage:
        def handle_finalized(speaker, text, event):
            # This is called ONCE per utterance
            # 1. Store to transcript file
            # 2. Send to Pipecat for LLM processing
            print(f"Final: {speaker}: {text}")
        
        extractor = TranscriptExtractor(
            browser, 
            bot_name="hicapybot",
            on_utterance_finalized=handle_finalized,
            utterance_timeout_ms=2000  # 2 seconds of silence = finalize
        )
        extractor.start()
    """
    
    SELECTORS = {
        "captions_container": "[jscontroller='D1tHje']",
        "caption_text": "div[class*='iOzk7']",
        "caption_speaker": "div[class*='zs7s8d']",
        "participant_tiles": "div[data-participant-id]",
        "tile_name": "div[class*='XEazBc']",
        "tile_speaking_indicator": "div[class*='Gv1mTb']",
        "captions_button": "button[aria-label*='caption' i]",
    }
    
    def __init__(
        self, 
        browser, 
        bot_name: str = "hicapybot", 
        meeting_id: str = None,
        on_utterance_finalized: Callable[[str, str, TranscriptEvent], None] = None,
        on_progress_update: Callable[[str, str], None] = None,
        utterance_timeout_ms: int = 2000,  # 2 seconds
        speaker_change_debounce_ms: int = 500  # 0.5 seconds
    ):
        self.browser = browser
        self.bot_name = bot_name
        self.meeting_id = meeting_id or f"meet_{uuid.uuid4().hex[:8]}"
        self.meeting_start_time = int(time.time() * 1000)
        
        # Timeouts
        self.utterance_timeout_ms = utterance_timeout_ms
        self.speaker_change_debounce_ms = speaker_change_debounce_ms
        
        # Storage (only finalized events)
        self.finalized_events: List[TranscriptEvent] = []
        self.speaker_map: Dict[str, str] = {}
        
        # Active utterance tracking
        self.active_utterance: Optional[TranscriptEvent] = None
        self.last_caption_text: str = ""
        
        # Callbacks
        self.on_utterance_finalized = on_utterance_finalized
        self.on_progress_update = on_progress_update
        
        # Threading
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        
        # Speaker detection state
        self._last_active_speaker = None
        self._speaker_first_seen = 0
        self._caption_enabled = False
        
        logger.info(f"TranscriptExtractor initialized (timeout={utterance_timeout_ms}ms)")
    
    def _get_speaker_id(self, name: str) -> str:
        """Get or create consistent speaker ID."""
        if name not in self.speaker_map:
            self.speaker_map[name] = f"p_{uuid.uuid4().hex[:4]}"
        return self.speaker_map[name]
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        if not text:
            return ""
        return " ".join(text.lower().split())
    
    def enable_captions(self) -> bool:
        """Enable Google Meet captions programmatically."""
        try:
            selectors = [
                "button[aria-label*='Turn on captions']",
                "button[aria-label*='captions' i]",
            ]
            
            for selector in selectors:
                try:
                    buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    for btn in buttons:
                        aria = btn.get_attribute("aria-label") or ""
                        if "turn on" in aria.lower():
                            btn.click()
                            logger.info("✅ Captions enabled")
                            self._caption_enabled = True
                            time.sleep(1)
                            return True
                except:
                    continue
            
            # Try keyboard shortcut
            try:
                from selenium.webdriver.common.keys import Keys
                body = self.browser.find_element(By.TAG_NAME, "body")
                body.send_keys("c")
                logger.info("✅ Captions toggled via 'c' key")
                self._caption_enabled = True
                return True
            except:
                pass
            
            logger.warning("⚠️ Could not enable captions")
            return False
            
        except Exception as e:
            logger.error(f"Caption enable error: {e}")
            return False
    
    def _extract_from_captions(self) -> Optional[Dict]:
        """
        Extract speaker + text from captions.
        Returns: {"speaker": str, "text": str, "confidence": float} or None
        """
        try:
            blocks = self.browser.find_elements(
                By.CSS_SELECTOR, 
                "div[jscontroller='D1tHje'] > div"
            )
            
            if not blocks:
                return None
            
            # Get LAST block (most recent)
            for block in reversed(blocks):
                try:
                    # Extract speaker
                    speaker = None
                    speaker_elems = block.find_elements(
                        By.CSS_SELECTOR, 
                        "div[class*='zs7s8d']"
                    )
                    if speaker_elems:
                        speaker = speaker_elems[0].text.strip()
                    
                    # Extract text
                    text = None
                    text_spans = block.find_elements(
                        By.CSS_SELECTOR, 
                        "span[class*='CNusmb']"
                    )
                    if text_spans:
                        text = "".join([s.text for s in text_spans]).strip()
                    else:
                        text_containers = block.find_elements(
                            By.CSS_SELECTOR, 
                            "div[class*='iOzk7']"
                        )
                        if text_containers:
                            raw = text_containers[-1].text.strip()
                            if speaker and raw.startswith(speaker):
                                text = raw[len(speaker):].strip()
                            else:
                                text = raw
                    
                    if not text:
                        continue
                    
                    # Skip if unchanged
                    if text == self.last_caption_text:
                        return None
                    
                    self.last_caption_text = text
                    
                    # Use active speaker if no caption speaker
                    final_speaker = speaker or self._get_active_speaker_name() or "Unknown"
                    confidence = 0.95 if speaker else 0.60
                    
                    return {
                        "speaker": final_speaker,
                        "text": text,
                        "confidence": confidence
                    }
                except:
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Caption extraction error: {e}")
            return None
    
    def _get_active_speaker_name(self) -> Optional[str]:
        """
        Detect active speaker from video tiles with debouncing.
        Only switches speaker after speaker_change_debounce_ms of stability.
        """
        try:
            tiles = self.browser.find_elements(
                By.CSS_SELECTOR,
                "div[data-participant-id]"
            )
            
            detected_speaker = None
            
            for tile in tiles:
                try:
                    # Check for speaking indicators
                    indicators = tile.find_elements(
                        By.CSS_SELECTOR,
                        "div[class*='Gv1mTb'], [class*='qdulke']"
                    )
                    
                    class_attr = tile.get_attribute("class") or ""
                    is_active = len(indicators) > 0 or "qdulke" in class_attr
                    
                    if is_active:
                        name_elements = tile.find_elements(
                            By.CSS_SELECTOR,
                            "div[class*='XEazBc'], [data-self-name]"
                        )
                        for elem in name_elements:
                            name = elem.text.strip() or elem.get_attribute("data-self-name")
                            if name and len(name) > 1:
                                detected_speaker = name
                                break
                    
                    if detected_speaker:
                        break
                except:
                    continue
            
            # Debounce speaker changes
            now = int(time.time() * 1000)
            
            if detected_speaker:
                if detected_speaker != self._last_active_speaker:
                    # New speaker detected - wait for debounce
                    if self._speaker_first_seen == 0:
                        self._speaker_first_seen = now
                    
                    time_stable = now - self._speaker_first_seen
                    if time_stable >= self.speaker_change_debounce_ms:
                        # Speaker stable long enough - switch
                        logger.debug(f"Speaker changed: {self._last_active_speaker} → {detected_speaker}")
                        self._last_active_speaker = detected_speaker
                        self._speaker_first_seen = 0
                        return detected_speaker
                    else:
                        # Not stable yet - keep old speaker
                        return self._last_active_speaker
                else:
                    # Same speaker - reset timer
                    self._speaker_first_seen = 0
                    return detected_speaker
            
            return self._last_active_speaker
            
        except Exception as e:
            logger.debug(f"Active speaker detection error: {e}")
            return None
    
    def _should_finalize_utterance(self) -> bool:
        """Check if current utterance should be finalized."""
        if not self.active_utterance or self.active_utterance.end_ms:
            return False
        
        now = int(time.time() * 1000)
        time_since_update = now - self.active_utterance.last_update_ms
        
        return time_since_update >= self.utterance_timeout_ms
    
    def _finalize_active_utterance(self):
        """
        Finalize current utterance and trigger callback.
        This is called ONCE per utterance.
        """
        if not self.active_utterance:
            return
        
        with self.lock:
            self.active_utterance.finalize()
            
            # Add to storage (only finalized events)
            self.finalized_events.append(self.active_utterance)
            
            duration_ms = self.active_utterance.end_ms - self.active_utterance.start_ms
            logger.info(
                f"✅ Finalized: [{self.active_utterance.speaker}] "
                f"{self.active_utterance.text[:60]}... ({duration_ms}ms)"
            )
            
            # Trigger callback (for storage + Pipecat)
            if self.on_utterance_finalized:
                try:
                    self.on_utterance_finalized(
                        self.active_utterance.speaker,
                        self.active_utterance.text,
                        self.active_utterance
                    )
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            
            self.active_utterance = None
    
    def _poll_transcripts(self):
        """Main polling loop."""
        
        while self.running:
            try:
                # Check if should finalize
                if self._should_finalize_utterance():
                    self._finalize_active_utterance()
                
                # Extract caption
                caption_data = self._extract_from_captions()
                
                if caption_data and caption_data.get("text"):
                    text = caption_data["text"]
                    speaker = caption_data.get("speaker") or "Unknown"
                    confidence = caption_data.get("confidence", 0.95)
                    
                    now = int(time.time() * 1000)
                    
                    with self.lock:
                        if self.active_utterance:
                            # Same speaker - update
                            if self.active_utterance.speaker == speaker:
                                norm_old = self._normalize_text(self.active_utterance.text)
                                norm_new = self._normalize_text(text)
                                
                                if len(norm_new) > len(norm_old):
                                    logger.debug(f"📝 Update: [{speaker}] {text[:60]}...")
                                    self.active_utterance.text = text
                                    self.active_utterance.last_update_ms = now
                                    
                                    # Optional: progress callback for live UI
                                    if self.on_progress_update:
                                        try:
                                            self.on_progress_update(speaker, text)
                                        except Exception as e:
                                            logger.debug(f"Progress callback error: {e}")
                                else:
                                    # Same text - just keep alive
                                    self.active_utterance.last_update_ms = now
                            else:
                                # Different speaker - finalize old, start new
                                self._finalize_active_utterance()
                                
                                self.active_utterance = TranscriptEvent(
                                    speaker=speaker,
                                    text=text,
                                    source="captions",
                                    speaker_id=self._get_speaker_id(speaker),
                                    confidence=confidence,
                                    start_ms=now
                                )
                                logger.info(f"🎤 New: [{speaker}] {text[:60]}...")
                        else:
                            # No active - create new
                            self.active_utterance = TranscriptEvent(
                                speaker=speaker,
                                text=text,
                                source="captions",
                                speaker_id=self._get_speaker_id(speaker),
                                confidence=confidence,
                                start_ms=now
                            )
                            logger.info(f"🎤 New: [{speaker}] {text[:60]}...")
                else:
                    # Check for speaker change (finalize if needed)
                    active_speaker = self._get_active_speaker_name()
                    if (active_speaker and self.active_utterance and 
                        active_speaker != self.active_utterance.speaker):
                        self._finalize_active_utterance()
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.debug(f"Poll error: {e}")
                time.sleep(1)
    
    def add_bot_utterance(self, text: str, start_ms: int = None, end_ms: int = None):
        """
        Add bot's speech to transcript.
        Called by AudioOutput after bot finishes speaking.
        """
        # Finalize any active human utterance first
        if self.active_utterance:
            self._finalize_active_utterance()
        
        with self.lock:
            event = TranscriptEvent(
                speaker=self.bot_name,
                text=text,
                source="bot_audio",
                role="bot",
                speaker_id="bot",
                confidence=1.0,
                start_ms=start_ms
            )
            
            if end_ms:
                event.finalize(end_ms)
            
            self.finalized_events.append(event)
            
            logger.info(f"🤖 Bot: {text[:50]}...")
            
            # Trigger callback
            if self.on_utterance_finalized:
                try:
                    self.on_utterance_finalized(self.bot_name, text, event)
                except Exception as e:
                    logger.error(f"Bot callback error: {e}")
    
    def start(self):
        """Start extraction."""
        if self.running:
            return
        
        self.running = True
        self.meeting_start_time = int(time.time() * 1000)
        
        # Enable captions
        time.sleep(2)
        self.enable_captions()
        
        # Start thread
        self.thread = threading.Thread(target=self._poll_transcripts, daemon=True)
        self.thread.start()
        
        logger.info("🎙️ Transcript extraction started")
    
    def stop(self):
        """Stop extraction."""
        self.running = False
        
        # Finalize any active utterance
        if self.active_utterance:
            self._finalize_active_utterance()
        
        if self.thread:
            self.thread.join(timeout=2)
        
        logger.info(f"🎙️ Stopped. {len(self.finalized_events)} events captured.")
    
    def get_transcript(self) -> Dict:
        """Get full transcript (only finalized events)."""
        with self.lock:
            return {
                "meeting_id": self.meeting_id,
                "meeting_start_ms": self.meeting_start_time,
                "meeting_end_ms": int(time.time() * 1000),
                "bot_name": self.bot_name,
                "participants": list(self.speaker_map.keys()),
                "event_count": len(self.finalized_events),
                "events": [e.to_dict() for e in self.finalized_events]
            }
    
    def save_transcript(self, filepath: str = None) -> str:
        """Save transcript to JSON."""
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            import os
            temp_dir = os.getenv("OUTPUT_DIR", "/tmp/hicapy")
            os.makedirs(temp_dir, exist_ok=True)
            filepath = os.path.join(
                temp_dir, 
                f"transcript_{self.meeting_id}_{timestamp}.json"
            )
        
        transcript = self.get_transcript()
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Saved: {filepath}")
        return filepath