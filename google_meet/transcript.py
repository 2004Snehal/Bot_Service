"""
Transcript Extractor for Google Meet
=====================================
Extracts speaker-attributed transcripts using:
1. Live Captions (Primary) - Most reliable
2. Active Speaker Tile (Secondary) - Visual indicator fallback
3. ARIA Text (Fallback) - Screen reader text

Output Format:
{
  "meeting_id": "meet_abc123",
  "events": [
    {"id": "evt_001", "speaker": "John Doe", "text": "Hello", ...}
  ]
}
"""

import json
import time
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
        self.source = source  # "captions", "active_tile", "aria", "bot_audio"
        self.confidence = confidence
        self.last_update_ts = int(time.time() * 1000)

    
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
    
    Usage:
        extractor = TranscriptExtractor(browser, bot_name="hicapybot")
        extractor.start()
        ...
        extractor.stop()
        extractor.save_transcript("meeting_transcript.json")
    """
    
    # CSS Selectors for Google Meet (may need updates as Google changes UI)
    SELECTORS = {
        # Caption selectors (primary)
        "captions_container": "[jscontroller='D1tHje']",
        "caption_text": "div[class*='iOzk7']",
        "caption_speaker": "div[class*='zs7s8d']",
        
        # Alternative caption selectors
        "captions_alt_container": "[data-is-persistent-captions='true']",
        "captions_alt_text": "span[class*='CNusmb']",
        
        # Participant tiles
        "participant_tiles": "div[data-participant-id]",
        "tile_name": "div[class*='XEazBc']",
        "tile_speaking_indicator": "div[class*='Gv1mTb']",  # Speaking animation
        
        # Active speaker (highlighted tile)
        "active_speaker_tile": "div[data-self-name][class*='qdulke']",
        
        # ARIA/Accessibility
        "aria_live_region": "[aria-live='polite']",
        "speaking_status": "[aria-label*='speaking']",
        
        # Captions button
        "captions_button": "button[aria-label*='caption' i], button[data-tooltip*='caption' i]",
        "cc_button": "button[aria-label*='Turn on captions'], button[aria-label*='Turn off captions']"
    }
    
    def __init__(self, browser, bot_name: str = "hicapybot", meeting_id: str = None, on_transcript=None):
        self.browser = browser
        self.bot_name = bot_name
        self.meeting_id = meeting_id or f"meet_{uuid.uuid4().hex[:8]}"
        self.meeting_start_time = int(time.time() * 1000)
        
        self.events: List[TranscriptEvent] = []
        self.speaker_map: Dict[str, str] = {}  # name -> speaker_id
        self.current_speaker: Optional[str] = None
        self.current_text: str = ""
        self.last_caption_text: str = ""
        
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        
        # Callback for real-time processing
        self.on_transcript = on_transcript
        
        # Tracking
        self._last_active_speaker = None
        self._last_switch_ts = 0
        self._caption_enabled = False
        
    def _get_speaker_id(self, name: str) -> str:
        """Get or create consistent speaker ID for a name."""
        if name not in self.speaker_map:
            self.speaker_map[name] = f"p_{uuid.uuid4().hex[:4]}"
        return self.speaker_map[name]
    
    def enable_captions(self) -> bool:
        """Programmatically enable Google Meet captions."""
        try:
            # Try multiple selectors for caption button
            selectors = [
                "button[aria-label*='captions' i]",
                "button[aria-label*='Turn on captions']",
                "button[data-tooltip*='caption' i]",
                "[aria-label*='subtitle' i]",
                "button[jsname='r8qRAd']"
            ]
            
            for selector in selectors:
                try:
                    buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    for btn in buttons:
                        aria = btn.get_attribute("aria-label") or ""
                        if "turn on" in aria.lower() or "enable" in aria.lower():
                            btn.click()
                            logger.info("✅ Captions enabled via button")
                            self._caption_enabled = True
                            time.sleep(1)
                            return True
                except:
                    continue
            
            # Try keyboard shortcut (c key toggles captions)
            try:
                from selenium.webdriver.common.keys import Keys
                body = self.browser.find_element(By.TAG_NAME, "body")
                body.send_keys("c")
                logger.info("✅ Captions toggled via 'c' key")
                self._caption_enabled = True
                return True
            except:
                pass
                
            logger.warning("⚠️ Could not enable captions automatically")
            return False
            
        except Exception as e:
            logger.error(f"Error enabling captions: {e}")
            return False
    
    def _extract_from_captions(self) -> Optional[Dict]:
        """
        PRIMARY: Extract speaker + text from live captions DOM.
        Returns: {"speaker": str, "text": str, "confidence": float} or None
        """
        try:
            # Google Meet captions structure:
            # Container [jscontroller='D1tHje']
            #   Block (one per speaker turn)
            #     Speaker Name [class*='zs7s8d']
            #     Text Container [class*='iOzk7']
            #       Text Spans [class*='CNusmb']
            
            blocks = self.browser.find_elements(By.CSS_SELECTOR, "div[jscontroller='D1tHje'] > div")
            if not blocks:
                # Fallback to any elements that look like captions
                blocks = self.browser.find_elements(By.CSS_SELECTOR, "div[class*='iOzk7']")
            
            if not blocks:
                return None
                
            for block in reversed(blocks):
                try:
                    # 1. Extract Speaker
                    speaker = None
                    speaker_elems = block.find_elements(By.CSS_SELECTOR, "div[class*='zs7s8d']")
                    if speaker_elems:
                        speaker = speaker_elems[0].text.strip()
                    
                    # 2. Extract Text
                    text = None
                    # Try spans first (more granular)
                    text_spans = block.find_elements(By.CSS_SELECTOR, "span[class*='CNusmb'], div[class*='VpByLc'] span")
                    if text_spans:
                        text = "".join([s.text for s in text_spans]).strip()
                    else:
                        # Fallback to the text container
                        text_containers = block.find_elements(By.CSS_SELECTOR, "div[class*='iOzk7'], div[class*='VpByLc']")
                        if text_containers:
                            # If speaker is inside the same container, we need to strip it
                            raw_text = text_containers[-1].text.strip()
                            if speaker and raw_text.startswith(speaker):
                                text = raw_text[len(speaker):].strip()
                            else:
                                text = raw_text
                    
                    if not text or text == self.last_caption_text:
                        continue
                        
                    # Ignore reflows (shorter text)
                    if len(text) <= len(self.last_caption_text) and self.last_caption_text.startswith(text):
                        continue

                    self.last_caption_text = text
                    
                    # Fallback to active speaker if caption speaker missing
                    final_speaker = speaker or self._get_active_speaker_name() or "Unknown"
                    
                    # Confidence decay
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
        SECONDARY: Detect active speaker from video tile indicators.
        Debounced to avoid flickering.
        """
        try:
            # Look for tiles with speaking indicator (animated bars or glow)
            tiles = self.browser.find_elements(
                By.CSS_SELECTOR,
                "div[data-participant-id]"
            )
            
            detected_speaker = None
            
            for tile in tiles:
                try:
                    # Check for speaking indicator
                    speaking_indicators = tile.find_elements(
                        By.CSS_SELECTOR,
                        "div[class*='Gv1mTb'], div[class*='speaking'], [class*='qdulke']"
                    )
                    
                    # Check for visual glow/border (active speaker)
                    class_attr = tile.get_attribute("class") or ""
                    is_active = (
                        len(speaking_indicators) > 0 or
                        "qdulke" in class_attr or
                        "KXcH3e" in class_attr  # Active speaker highlight
                    )
                    
                    if is_active:
                        # Extract name from tile
                        name_elements = tile.find_elements(
                            By.CSS_SELECTOR,
                            "div[class*='XEazBc'], div[class*='ZjFb7c'], [data-self-name]"
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
            
            # Debounce logic
            now = int(time.time() * 1000)
            if detected_speaker:
                if detected_speaker != self._last_active_speaker:
                    # Only switch if stable for 500ms
                    if now - self._last_switch_ts > 500:
                        self._last_active_speaker = detected_speaker
                        self._last_switch_ts = now
                        return detected_speaker
                    else:
                        # Not stable yet, return previous
                        return self._last_active_speaker
                else:
                    # Same speaker, update timestamp to keep it fresh? 
                    # No, we want to track when it *changed*.
                    # Actually, if it's the same, we just return it.
                    self._last_switch_ts = now # Reset switch timer as we are stable on this one
                    return detected_speaker
            
            return self._last_active_speaker
            
        except Exception as e:
            logger.debug(f"Active speaker detection error: {e}")
            return None
    
    def _extract_from_aria(self) -> Optional[Dict]:
        """
        FALLBACK: Extract speaker from ARIA live regions.
        Less reliable but useful when captions fail.
        """
        try:
            # Look for "X is speaking" aria labels
            elements = self.browser.find_elements(
                By.CSS_SELECTOR,
                "[aria-label*='speaking'], [aria-live='polite']"
            )
            
            for elem in elements:
                aria = elem.get_attribute("aria-label") or elem.text
                if "speaking" in aria.lower():
                    # Extract name from "John Doe is speaking"
                    parts = aria.lower().split(" is speaking")
                    if parts:
                        speaker = parts[0].strip().title()
                        if speaker and len(speaker) > 1:
                            return {
                                "speaker": speaker,
                                "text": None,  # ARIA doesn't give us text
                                "confidence": 0.60
                            }
                            
            return None
            
        except Exception as e:
            logger.debug(f"ARIA extraction error: {e}")
            return None
    
    def _poll_transcripts(self):
        """Main polling loop for transcript extraction."""
        last_text = ""
        
        while self.running:
            try:
                # Check for silence/finalization
                with self.lock:
                    if self.events:
                        last_event = self.events[-1]
                        if not last_event.end_ms:
                            time_since_update = int(time.time() * 1000) - getattr(last_event, 'last_update_ts', 0)
                            if time_since_update > 800:
                                last_event.finalize()
                                # logger.debug(f"Finalized event {last_event.id} due to silence")

                # 1. Try captions first (most reliable)
                caption_data = self._extract_from_captions()
                
                if caption_data and caption_data.get("text"):
                    text = caption_data["text"]
                    speaker = caption_data.get("speaker") or "Unknown"
                    
                    if text != last_text:
                        last_text = text
                        self._add_event(
                            speaker=speaker,
                            text=text,
                            source="captions",
                            confidence=caption_data.get("confidence", 0.95)
                        )
                else:
                    # 2. Try active speaker detection
                    active_speaker = self._get_active_speaker_name()
                    
                    if active_speaker and active_speaker != self.current_speaker:
                        self.current_speaker = active_speaker
                        logger.debug(f"Active speaker changed: {active_speaker}")
                        # Explicit speaker change event (if needed, but user asked for it)
                        # { "type": "speaker_change", "speaker": "John" }
                        # We can add an event with empty text or special flag?
                        # The user said: Create explicit speaker-change events when no text is available.
                        # But TranscriptEvent expects text.
                        # I will add an event with empty text, but maybe mark source as 'speaker_change'?
                        # Or just rely on the fact that it's a new event.
                        # But if I add event with empty text, it might clutter.
                        # However, the user explicitly asked for it.
                        # "Create explicit speaker-change events when no text is available."
                        # I'll add it.
                        self._add_event(
                            speaker=active_speaker,
                            text="", 
                            source="active_tile",
                            confidence=0.6
                        )
                    
                    # 3. Fallback to ARIA
                    aria_data = self._extract_from_aria()
                    if aria_data and aria_data.get("speaker"):
                        self.current_speaker = aria_data["speaker"]
                
                time.sleep(0.1)  # Poll every 100ms (was 700ms)
                
            except Exception as e:
                logger.debug(f"Transcript poll error: {e}")
                time.sleep(1)
    
    def _add_event(
        self,
        speaker: str,
        text: str,
        source: str = "captions",
        role: str = "human",
        confidence: float = 0.95
    ):
        """Add a new transcript event."""
        with self.lock:
            # Check if we should merge with previous event
            if self.events:
                last_event = self.events[-1]
                
                # Check for same speaker
                if last_event.speaker == speaker:
                    # CASE 1: Not finalized - normal merge
                    if not last_event.end_ms:
                        last_event.text = text  # Update with latest text
                        last_event.last_update_ts = int(time.time() * 1000)
                        
                        # Trigger callback for updates too
                        if self.on_transcript:
                            self.on_transcript(speaker, text)
                        return
                    
                    # CASE 2: Finalized but text is a prefix match (Fix for duplication)
                    # Example: "I am snehal" -> "I am snehal i am a entrepreneur"
                    clean_last = last_event.text.strip().lower()
                    clean_new = text.strip().lower()
                    
                    # Allow a small tolerance for minor punctuation/capitalization diffs via startswith
                    if clean_new.startswith(clean_last) and len(clean_new) > len(clean_last):
                        logger.info(f"🔄 Merging finalized event overlap: '{last_event.text}' -> '{text}'")
                        last_event.text = text
                        last_event.end_ms = None  # Un-finalize to allow more updates
                        last_event.last_update_ts = int(time.time() * 1000)
                        
                        if self.on_transcript:
                            self.on_transcript(speaker, text)
                        return
            
            # Create new event
            event = TranscriptEvent(
                speaker=speaker,
                text=text,
                source=source,
                role=role,
                speaker_id=self._get_speaker_id(speaker),
                confidence=confidence
            )
            
            self.events.append(event)
            logger.info(f"📝 [{source}] {speaker}: {text[:50]}...")
            
            # Trigger callback for new event
            if self.on_transcript:
                self.on_transcript(speaker, text)
    
    def add_bot_utterance(self, text: str, start_ms: int = None, end_ms: int = None):
        """
        Add bot's own speech to transcript.
        Called by AudioOutput when bot speaks.
        """
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
            
            self.events.append(event)
            logger.info(f"📝 [bot] {self.bot_name}: {text[:50]}...")
            
            # Trigger callback for bot utterance
            if self.on_transcript:
                self.on_transcript(self.bot_name, text)
    
    def start(self):
        """Start transcript extraction."""
        if self.running:
            return
        
        self.running = True
        self.meeting_start_time = int(time.time() * 1000)
        
        # Try to enable captions
        time.sleep(2)  # Wait for UI to load
        self.enable_captions()
        
        # Start polling thread
        self.thread = threading.Thread(target=self._poll_transcripts, daemon=True)
        self.thread.start()
        logger.info("🎙️ Transcript extraction started")
    
    def stop(self):
        """Stop transcript extraction."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        
        # Finalize last event
        with self.lock:
            if self.events and not self.events[-1].end_ms:
                self.events[-1].finalize()
        
        logger.info(f"🎙️ Transcript extraction stopped. {len(self.events)} events captured.")
    
    def get_transcript(self) -> Dict:
        """Get full transcript as dictionary."""
        with self.lock:
            return {
                "meeting_id": self.meeting_id,
                "meeting_start_ms": self.meeting_start_time,
                "meeting_end_ms": int(time.time() * 1000),
                "bot_name": self.bot_name,
                "participants": list(self.speaker_map.keys()),
                "event_count": len(self.events),
                "events": [e.to_dict() for e in self.events]
            }
    
    def save_transcript(self, filepath: str = None) -> str:
        """Save transcript to JSON file."""
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = os.getenv("OUTPUT_DIR", "/tmp/cuemeet")
            filepath = os.path.join(temp_dir, f"transcript_{self.meeting_id}_{timestamp}.json")
        
        transcript = self.get_transcript()
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Transcript saved to: {filepath}")
        return filepath
    
    def get_recent_text(self, last_n: int = 5) -> List[str]:
        """Get last N transcript entries as simple strings."""
        with self.lock:
            recent = self.events[-last_n:] if self.events else []
            return [f"{e.speaker}: {e.text}" for e in recent]
