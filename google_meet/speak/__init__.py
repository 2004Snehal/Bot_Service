"""
Pipecat-based Voice Integration Module
=======================================
Optional voice assistant capabilities using Pipecat framework.
Provides streaming LLM responses from Groq and TTS from Deepgram.

Only loaded when --speak=true flag is enabled.
"""

from .pipecat_handler import PipecatSpeakHandler

__all__ = ['PipecatSpeakHandler']
