import sys
import numpy as np
import pyaudio
from openwakeword.model import Model

MODEL_PATH = "hey_smarthome_20260716_200659.onnx"
oww_model = Model(wakeword_model_paths=[MODEL_PATH])

RATE = 16000
CHUNK_SIZE = 1280

audio = pyaudio.PyAudio()
stream = audio.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK_SIZE
)

print("En écoute... Parle pour tester le micro 🎙️\n")

try:
    while True:
        raw_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        audio_data = np.frombuffer(raw_data, dtype=np.int16)

        # 1. Calcul du volume sonore (RMS)
        rms = np.sqrt(np.mean(audio_data.astype(np.float64)**2))
        vol_bars = int(min(rms / 100, 25))
        vu_meter = "█" * vol_bars + " " * (25 - vol_bars)

        # 2. Prédiction openWakeWord
        prediction = oww_model.predict(audio_data)

        # Récupération du score actuel du modèle
        model_name = list(oww_model.prediction_buffer.keys())[0]
        score = oww_model.prediction_buffer[model_name][-1]

        # Affichage dynamique sur une seule ligne
        sys.stdout.write(f"\rMicro: [{vu_meter}] | Score: {score:.3f} ")
        sys.stdout.flush()

        # Déclenchement
        if score > 0.5:
            print(f"\n🚀 DÉTECTION CONFIRMÉE ! (Score : {score:.2f})")
            oww_model.reset()

except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    stream.stop_stream()
    stream.close()
    audio.terminate()
