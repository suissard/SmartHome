"""
Package audio regroupant le traitement sonore, la détection de wakeword, le STT, le TTS, le feedback et le ducking.
"""

from audio.wakeword import WakeWordDetector
from audio.transcribe import Transcriber
from audio.tts import TextToSpeech
from audio.feedback import FeedbackManager
from audio.ducking import AudioDucker

__all__ = [
    "WakeWordDetector",
    "Transcriber",
    "TextToSpeech",
    "FeedbackManager",
    "AudioDucker",
]

