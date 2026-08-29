import sys
from pathlib import Path
import numpy as np
import pyaudio

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from openwakeword.model import Model
from core.config import (
    WAKEWORD_MODEL_PATH,
    WAKEWORD_THRESHOLD,
    AUDIO_CHUNK,
    AUDIO_RATE,
    AUDIO_INPUT_DEVICE_INDEX,
)


MODEL_PATH = WAKEWORD_MODEL_PATH
CHUNK = AUDIO_CHUNK
RATE = AUDIO_RATE
FORMAT = pyaudio.paInt16

class WakeWordDetector:
    def __init__(self, model_path=WAKEWORD_MODEL_PATH, threshold=WAKEWORD_THRESHOLD):
        self.oww = Model(wakeword_model_paths=[model_path])
        # Récupération du nom du modèle depuis le dictionnaire des modèles chargés
        self.model_name = list(self.oww.models.keys())[0]
        self.threshold = threshold

    def process_chunk(self, audio_chunk):
        """Retourne True et le score si le mot-clé est détecté"""
        self.oww.predict(audio_chunk)
        score = self.oww.prediction_buffer[self.model_name][-1]
        if score > self.threshold:
            self.oww.reset()
            return True, score
        return False, score

if __name__ == "__main__":
    print(f"🧪 [DEBUG] Mode test Détecteur de mot-clé ({MODEL_PATH}, seuil={WAKEWORD_THRESHOLD})...")
    detector = WakeWordDetector()
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=1,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INPUT_DEVICE_INDEX,
        frames_per_buffer=CHUNK
    )

    print("En écoute... Prononce ton mot-clé 🎙️\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)

            # Calcul du volume sonore pour le VU-mètre
            rms = np.sqrt(np.mean(chunk.astype(np.float64)**2))
            bars = int(min(rms / 100, 20))

            detected, score = detector.process_chunk(chunk)
            sys.stdout.write(f"\rMicro: [{'█'*bars}{' '*(20-bars)}] | Score: {score:.3f} ")
            sys.stdout.flush()

            if detected:
                print(f"\n🚀 DÉTECTION CONFIRMÉE ! (Score: {score:.2f})")
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

