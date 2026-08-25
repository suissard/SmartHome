import io
import time
import wave
import numpy as np
import pyaudio
from faster_whisper import WhisperModel

# Modèle : 'base' (rapide) ou 'small' (bien plus précis en français sur CPU)
MODEL_NAME = "base"
print(f"Chargement du modèle Whisper ({MODEL_NAME})... ⏳")
model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")

RATE = 16000
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1

THRESHOLD = 700          # Seuil sonore du micro
SILENCE_DURATION = 1.0   # Silence requis pour valider la fin de phrase (en secondes)

p = pyaudio.PyAudio()
stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

def transcribe_audio(frames):
    """Transcrit l'audio et mesure le temps d'exécution"""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    wav_buffer.seek(0)

    # Mesure précise du temps de transcription
    start_time = time.perf_counter()
    segments, _ = model.transcribe(
        wav_buffer,
        language="fr",
        beam_size=3,
        condition_on_previous_text=False
    )
    text = " ".join([segment.text for segment in segments]).strip()
    inference_time = time.perf_counter() - start_time

    return text, inference_time

print("Prêt ! Parle dans ton micro... 🎙️\n")

try:
    frames = []
    is_speaking = False
    silence_start = None

    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_chunk = np.frombuffer(data, dtype=np.int16)
        volume = np.abs(audio_chunk).mean()

        if volume > THRESHOLD:
            if not is_speaking:
                is_speaking = True
                print("🎤 [Enregistrement en cours...]")
            frames.append(data)
            silence_start = None
        elif is_speaking:
            frames.append(data)
            if silence_start is None:
                silence_start = time.perf_counter()
            elif time.perf_counter() - silence_start > SILENCE_DURATION:
                # Calcul de la durée totale de l'audio enregistré
                audio_duration = (len(frames) * CHUNK) / RATE

                text, inference_time = transcribe_audio(frames)

                if text:
                    print(f"👉 Texte : « {text} »")
                    print(f"⏱️  Inférence : {inference_time:.2f} s | Audio : {audio_duration:.2f} s | Ratio : {(inference_time / audio_duration):.2f}x temps réel\n")

                # Réinitialisation
                frames = []
                is_speaking = False
                silence_start = None

except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    stream.stop_stream()
    stream.close()
    p.terminate()
