"""
Détection d'activité vocale (VAD) : distingue la parole du bruit ambiant (ventilateur, musique, claquements...).

Moteurs (VAD_ENGINE) :
- "silero" : réseau Silero VAD fourni par openWakeWord (ONNX local, ~0,3 ms par trame). Le niveau sonore
             (VOICE_THRESHOLD) reste un pré-filtre pour démarrer un enregistrement.
- "energy" : seuil de niveau sonore seul (ancien comportement, sensible au bruit).
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

# Hystérésis : une parole commencée continue tant que la probabilité reste au-dessus de (seuil - marge)
_HYSTERESIS = 0.15
_FRAME_SIZE = 640


class SpeechDetector:
    def __init__(self, settings: Optional[Settings] = None, model=None):
        self.settings = settings or get_settings()
        self.engine = self.settings.VAD_ENGINE
        self.model = model
        if self.engine == "silero" and self.model is None:
            try:
                from openwakeword.vad import VAD
                self.model = VAD()
            except Exception as e:
                print(f"⚠️ [VAD] Silero indisponible ({e}) : détection au niveau sonore seul.")
                self.engine = "energy"

    def reset(self):
        if self.model is not None:
            self.model.reset_states()

    def probability(self, chunk: np.ndarray) -> float:
        """Probabilité que la trame (int16, 16 kHz) contienne de la parole."""
        if self.engine != "silero":
            return 1.0 if np.abs(chunk).mean() > self.settings.VOICE_THRESHOLD else 0.0
        usable = len(chunk) - len(chunk) % _FRAME_SIZE
        return float(self.model.predict(chunk[:usable], frame_size=_FRAME_SIZE)) if usable else 0.0

    def is_speech_start(self, chunk: np.ndarray) -> bool:
        """Début de parole : assez fort ET reconnu comme de la voix."""
        prob = self.probability(chunk)
        return np.abs(chunk).mean() > self.settings.VOICE_THRESHOLD and prob >= self.settings.VAD_SPEECH_THRESHOLD

    def is_speech_continuing(self, chunk: np.ndarray) -> bool:
        """Pendant un enregistrement : la parole continue-t-elle (même à voix plus basse) ?"""
        if self.engine != "silero":
            return np.abs(chunk).mean() > self.settings.VOICE_THRESHOLD
        return self.probability(chunk) >= max(0.05, self.settings.VAD_SPEECH_THRESHOLD - _HYSTERESIS)


if __name__ == "__main__":
    s = get_settings()
    print(f"🧪 [DEBUG] VAD ({s.VAD_ENGINE}) : parlez, puis faites du bruit sans parler (Ctrl+C pour quitter)")
    import pyaudio
    detector = SpeechDetector(s)
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=s.AUDIO_RATE, input=True,
                    input_device_index=s.AUDIO_INPUT_DEVICE_INDEX, frames_per_buffer=s.AUDIO_CHUNK)
    try:
        while True:
            chunk = np.frombuffer(stream.read(s.AUDIO_CHUNK, exception_on_overflow=False), dtype=np.int16)
            prob = detector.probability(chunk)
            bar = "█" * int(prob * 20)
            print(f"\rniveau {np.abs(chunk).mean():6.0f} | parole {prob:.2f} {bar:<20}", end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        stream.close()
        p.terminate()
