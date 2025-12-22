import math
import struct
import logging

logger = logging.getLogger(__name__)

class VAD:
    def __init__(self, threshold=0.01):  # Realistic threshold for speech detection
        """
        Voice Activity Detection based on RMS energy.
        
        Args:
            threshold: Normalized RMS threshold (0.0 to 1.0).
                       0.01 = 1% of max amplitude (good for most setups)
                       0.02 = 2% of max amplitude (less sensitive, reduces false positives)
                       0.005 = 0.5% (more sensitive, may catch quiet speech)
                       
        Based on observed values:
            - Silence: ~0.001 to 0.005 normalized
            - Speech: ~0.02 to 0.10 normalized
        """
        # Allow runtime override via env for quick calibration
        try:
            import os
            env_thresh = os.getenv("VAD_THRESHOLD")
            self.threshold = float(env_thresh) if env_thresh else threshold
        except Exception:
            self.threshold = threshold
        # Announce VAD configuration at startup for visibility
        logger.info(f"[VAD] Initialized with threshold={self.threshold}")
        self._speech_frames = 0  # Track consecutive speech frames for logging
        self._debug_counter = 0

    def is_speaking(self, pcm_chunk: bytes) -> bool:
        """
        Compute RMS energy of the chunk.
        Return True if above threshold.
        Assumes 16-bit PCM (s16le).
        """
        if not pcm_chunk:
            return False
            
        count = len(pcm_chunk) // 2
        if count == 0:
            return False
            
        # Unpack as signed 16-bit integers (little-endian, typical for s16le)
        # Using explicit '<h' avoids platform endianness issues
        format_str = f"<{count}h"
        try:
            samples = struct.unpack(format_str, pcm_chunk)
        except struct.error:
            return False

        # Calculate RMS
        sum_squares = sum(s**2 for s in samples)
        rms = math.sqrt(sum_squares / count)
        
        # Normalize RMS to 0.0 - 1.0 range (max amplitude for 16-bit is 32767)
        normalized_rms = rms / 32767.0
        
        is_speech = normalized_rms > self.threshold
        
        # Debug logging every 20 frames (~1.2 seconds) - more frequent for debugging
        self._debug_counter += 1
        if self._debug_counter % 20 == 0 or is_speech:
            if is_speech or normalized_rms > 0.00001:  # Log any non-zero audio
                logger.info(f"[VAD] RMS={rms:.1f}, Norm={normalized_rms:.6f}, Thresh={self.threshold}, Speech={is_speech}")
        
        # Log when speech state changes
        if is_speech and self._speech_frames == 0:
            logger.info(f"🗣️ [VAD] Speech START detected (RMS={rms:.1f}, norm={normalized_rms:.6f})")
        elif not is_speech and self._speech_frames > 0:
            logger.info(f"🔇 [VAD] Speech END after {self._speech_frames} frames")
            
        if is_speech:
            self._speech_frames += 1
        else:
            self._speech_frames = 0
        
        return is_speech
