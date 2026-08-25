import sys
import numpy as np
import pyaudio
from openwakeword.model import Model

MODEL_PATH = "wakewords/Salut_Jarvisse_20260601_005854.onnx"
CHUNK = 1280
RATE = 16000
FORMAT = pyaudio.paInt16

class WakeWordDetector:
    def __init__(self, model_path=MODEL_PATH, threshold=0.5):
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
    print("🧪 [DEBUG] Mode test Détecteur de mot-clé...")
    detector = WakeWordDetector()
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=1,
        rate=RATE,
        input=True,
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
