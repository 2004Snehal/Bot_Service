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
    
    Usage:
        extractor = TranscriptExtractor(browser, bot_name="hicapybot", utterance_timeout_ms=15000)
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
    
    def __init__(
        self, 
        browser, 
        bot_name: str = "hicapybot", 
        meeting_id: str = None, 
        on_transcript=None,
        utterance_timeout_ms: int = 15000  # 15 seconds default
    ):
        self.browser = browser
        self.bot_name = bot_name
        self.meeting_id = meeting_id or f"meet_{uuid.uuid4().hex[:8]}"
        self.meeting_start_time = int(time.time() * 1000)
        
        # Time window for grouping utterances (15-20 seconds)
        self.utterance_timeout_ms = utterance_timeout_ms
        
        self.events: List[TranscriptEvent] = []
        self.speaker_map: Dict[str, str] = {}  # name -> speaker_id
        
        # Current active utterance tracking
        self.active_utterance: Optional[TranscriptEvent] = None
        
        # Track last finalized text to prevent duplicates
        self.last_finalized_text: str = ""
        self.last_caption_text: str = ""  # Last seen raw caption
        
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
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison (collapse whitespace, lowercase)."""
        if not text:
            return ""
        return " ".join(text.lower().split())

    def _is_text_duplicate(self, new_text: str, old_text: str) -> bool:
        """
        Check if new_text is a duplicate or subset of old_text.
        Returns True if they're essentially the same.
        """
        if not new_text or not old_text:
            return False
        
        norm_new = self._normalize_text(new_text)
        norm_old = self._normalize_text(old_text)
        
        # Exact match
        if norm_new == norm_old:
            return True
        
        # New text is a prefix of old (caption reflow/truncation)
        if norm_old.startswith(norm_new):
            return True
        
        # New text is very similar (>90% overlap)
        if len(norm_new) > 20:  # Only for substantial text
            overlap = len(set(norm_new.split()) & set(norm_old.split()))
            total = len(set(norm_new.split()) | set(norm_old.split()))
            if total > 0 and (overlap / total) > 0.9:
                return True
        
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
                
            # Get the LAST block (most recent caption)
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
                            raw_text = text_containers[-1].text.strip()
                            if speaker and raw_text.startswith(speaker):
                                text = raw_text[len(speaker):].strip()
                            else:
                                text = raw_text
                    
                    if not text:
                        continue
                    
                    # Skip if this is the same text we just saw
                    if text == self.last_caption_text:
                        return None
                    
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
                    self._last_switch_ts = now
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
    
    def _should_finalize_utterance(self) -> bool:
        """Check if current utterance should be finalized."""
        if not self.active_utterance or self.active_utterance.end_ms:
            return False
        
        now = int(time.time() * 1000)
        time_since_update = now - self.active_utterance.last_update_ms
        
        # Finalize if timeout exceeded
        return time_since_update >= self.utterance_timeout_ms
    
    def _finalize_active_utterance(self):
        """Finalize the current active utterance and move to events list."""
        if not self.active_utterance:
            return
        
        with self.lock:
            self.active_utterance.finalize()
            self.events.append(self.active_utterance)
            
            # Store normalized version to prevent duplicates
            self.last_finalized_text = self._normalize_text(self.active_utterance.text)
            
            logger.info(f"✅ Finalized: [{self.active_utterance.speaker}] {self.active_utterance.text[:60]}... (duration: {self.active_utterance.end_ms - self.active_utterance.start_ms}ms)")
            
            # Trigger callback for finalized utterance
            if self.on_transcript:
                self.on_transcript(self.active_utterance.speaker, self.active_utterance.text)
            
            self.active_utterance = None
    
    def _poll_transcripts(self):
        """Main polling loop for transcript extraction."""
        
        while self.running:
            try:
                # Check if we should finalize current utterance
                if self._should_finalize_utterance():
                    self._finalize_active_utterance()
                
                # 1. Try captions first (most reliable)
                caption_data = self._extract_from_captions()
                
                if caption_data and caption_data.get("text"):
                    text = caption_data["text"]
                    speaker = caption_data.get("speaker") or "Unknown"
                    confidence = caption_data.get("confidence", 0.95)
                    
                    # CRITICAL: Check if this text is a duplicate of what we just finalized
                    if self._is_text_duplicate(text, self.last_finalized_text):
                        logger.debug(f"⏭️ Skipping duplicate text: {text[:60]}...")
                        time.sleep(0.1)
                        continue
                    
                    now = int(time.time() * 1000)
                    
                    with self.lock:
                        # Check if we have an active utterance
                        if self.active_utterance:
                            # Same speaker - update existing utterance
                            if self.active_utterance.speaker == speaker:
                                # Only update if text is longer (progressive update)
                                norm_old = self._normalize_text(self.active_utterance.text)
                                norm_new = self._normalize_text(text)
                                
                                if len(norm_new) > len(norm_old):
                                    logger.debug(f"📝 Updating: [{speaker}] {text[:60]}...")
                                    self.active_utterance.text = text
                                    self.active_utterance.last_update_ms = now
                                elif norm_new == norm_old:
                                    # Same text, just update timestamp to keep alive
                                    self.active_utterance.last_update_ms = now
                            else:
                                # Different speaker - finalize old, start new
                                self._finalize_active_utterance()
                                
                                # Double-check against last finalized again after finalization
                                if not self._is_text_duplicate(text, self.last_finalized_text):
                                    self.active_utterance = TranscriptEvent(
                                        speaker=speaker,
                                        text=text,
                                        source="captions",
                                        speaker_id=self._get_speaker_id(speaker),
                                        confidence=confidence,
                                        start_ms=now
                                    )
                                    logger.info(f"🎤 New utterance: [{speaker}] {text[:60]}...")
                        else:
                            # No active utterance - create new one (if not duplicate)
                            if not self._is_text_duplicate(text, self.last_finalized_text):
                                self.active_utterance = TranscriptEvent(
                                    speaker=speaker,
                                    text=text,
                                    source="captions",
                                    speaker_id=self._get_speaker_id(speaker),
                                    confidence=confidence,
                                    start_ms=now
                                )
                                logger.info(f"🎤 New utterance: [{speaker}] {text[:60]}...")
                else:
                    # 2. Try active speaker detection (for speaker changes)
                    active_speaker = self._get_active_speaker_name()
                    
                    if active_speaker and self.active_utterance:
                        if active_speaker != self.active_utterance.speaker:
                            # Speaker changed but no caption yet - finalize previous
                            self._finalize_active_utterance()
                            logger.debug(f"Speaker changed to: {active_speaker}")
                
                time.sleep(0.1)  # Poll every 100ms
                
            except Exception as e:
                logger.debug(f"Transcript poll error: {e}")
                time.sleep(1)
    
    def add_bot_utterance(self, text: str, start_ms: int = None, end_ms: int = None):
        """
        Add bot's own speech to transcript.
        Called by AudioOutput when bot speaks.
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
            
            self.events.append(event)
            
            # Update last finalized to prevent duplicate detection
            self.last_finalized_text = self._normalize_text(text)
            
            logger.info(f"🤖 Bot: {self.bot_name}: {text[:50]}...")
            
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
        logger.info(f"🎙️ Transcript extraction started (timeout: {self.utterance_timeout_ms}ms)")
    
    def stop(self):
        """Stop transcript extraction."""
        self.running = False
        
        # Finalize any active utterance
        if self.active_utterance:
            self._finalize_active_utterance()
        
        if self.thread:
            self.thread.join(timeout=2)
        
        logger.info(f"🎙️ Transcript extraction stopped. {len(self.events)} events captured.")
    
    def get_transcript(self) -> Dict:
        """Get full transcript as dictionary."""
        with self.lock:
            # Include active utterance if present
            all_events = self.events.copy()
            if self.active_utterance:
                all_events.append(self.active_utterance)
            
            return {
                "meeting_id": self.meeting_id,
                "meeting_start_ms": self.meeting_start_time,
                "meeting_end_ms": int(time.time() * 1000),
                "bot_name": self.bot_name,
                "participants": list(self.speaker_map.keys()),
                "event_count": len(all_events),
                "events": [e.to_dict() for e in all_events]
            }
    
    def save_transcript(self, filepath: str = None) -> str:
        """Save transcript to JSON file."""
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            import os
            temp_dir = os.getenv("OUTPUT_DIR", "/tmp/cuemeet")
            os.makedirs(temp_dir, exist_ok=True)
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