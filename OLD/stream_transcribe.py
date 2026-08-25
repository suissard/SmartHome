import sys
import time
import numpy as np
import pyaudio
from faster_whisper import WhisperModel

# Modèle 'tiny' ou 'base' recommandé pour un rendu immédiat sur CPU
print("Chargement du modèle... ⏳")
model = WhisperModel("tiny", device="cpu", compute_type="int8")

RATE = 16000
CHUNK = 1024
CHANNELS = 1
SILENCE_LIMIT = 1.0       # Validation finale après 1s de silence
TRANSCRIBE_INTERVAL = 0.4 # Intervalle de rafraîchissement (400 ms)

p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

audio_buffer = []
is_speaking = False
last_speech_time = time.time()
last_transcribe_time = time.time()
current_text = ""

print("Prêt ! Parle en direct... 🎙️\n")

try:
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        chunk_np = np.frombuffer(data, dtype=np.int16)
        volume = np.abs(chunk_np).mean()

        if volume > 600:  # Détection de voix
            is_speaking = True
            last_speech_time = time.time()
            audio_buffer.append(chunk_np)
        elif is_speaking:
            audio_buffer.append(chunk_np)

        now = time.time()

        # Rafraîchissement en temps réel pendant que tu parles
        if is_speaking and (now - last_transcribe_time > TRANSCRIBE_INTERVAL) and len(audio_buffer) > 0:
            last_transcribe_time = now

            # Conversion en tableau float32 normalisé pour Whisper
            full_audio = np.concatenate(audio_buffer).astype(np.float32) / 32768.0

            # Inférence rapide (beam_size=1 pour zéro latence)
            segments, _ = model.transcribe(
                full_audio,
                language="fr",
                beam_size=1,
                condition_on_previous_text=False
            )

            current_text = " ".join([seg.text for seg in segments]).strip()
            if current_text:
                sys.stdout.write(f"\r💬 {current_text}   ")
                sys.stdout.flush()

        # Fin de phrase après silence
        if is_speaking and (now - last_speech_time > SILENCE_LIMIT):
            if current_text:
                print(f"\n✅ Validé : « {current_text} »\n")
                # Variable prête à être envoyée à Ollama / Hermes

            audio_buffer = []
            is_speaking = False
            current_text = ""

except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    stream.stop_stream()
    stream.close()
    p.terminate()
