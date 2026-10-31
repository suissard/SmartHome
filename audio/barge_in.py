"""
Détection d'une interruption de l'utilisateur pendant que l'assistant réfléchit ou parle (barge-in).

Modes (BARGE_IN_MODE) :
- "wakeword" : l'utilisateur redit le mot-clé. Robuste à l'écho : la voix de l'assistant ne le prononce pas.
- "voice"    : toute voix forte et continue. À réserver au casque ou à une annulation d'écho (PipeWire echo-cancel),
               sinon la voix de l'assistant elle-même déclencherait l'interruption.
- "off"      : désactivé.
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings


class BargeInDetector:
    def __init__(self, settings: Optional[Settings] = None, wakeword_detector=None):
        self.settings = settings or get_settings()
        self.mode = self.settings.BARGE_IN_MODE
        self.wakeword = wakeword_detector
        self._loud_seconds = 0.0
        if self.mode == "wakeword" and wakeword_detector is None:
            self.mode = "off"

    def reset(self):
        self._loud_seconds = 0.0

    def process(self, chunk: np.ndarray) -> bool:
        """Analyse une trame micro (int16) ; True si l'utilisateur veut interrompre l'assistant."""
        if self.mode == "wakeword":
            detected, _ = self.wakeword.process_chunk(chunk)
            return detected
        if self.mode == "voice":
            if np.abs(chunk).mean() > self.settings.BARGE_IN_VOICE_THRESHOLD:
                self._loud_seconds += len(chunk) / self.settings.AUDIO_RATE
            else:
                self._loud_seconds = 0.0
            return self._loud_seconds >= self.settings.BARGE_IN_MIN_DURATION
        return False


if __name__ == "__main__":
    s = get_settings()
    print(f"🧪 [DEBUG] Barge-in (mode {s.BARGE_IN_MODE}) : parlez pour tester le déclenchement (Ctrl+C pour quitter)")
    import pyaudio
    from audio.wakeword import WakeWordDetector, FORMAT
    detector = BargeInDetector(s, WakeWordDetector() if s.BARGE_IN_MODE == "wakeword" else None)
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=s.AUDIO_RATE, input=True,
                    input_device_index=s.AUDIO_INPUT_DEVICE_INDEX, frames_per_buffer=s.AUDIO_CHUNK)
    try:
        while True:
            chunk = np.frombuffer(stream.read(s.AUDIO_CHUNK, exception_on_overflow=False), dtype=np.int16)
            if detector.process(chunk):
                print("✋ Interruption détectée !")
                detector.reset()
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()
        p.terminate()
