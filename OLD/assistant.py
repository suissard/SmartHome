import io
import time
import wave
import numpy as np
import pyaudio
import ollama
from openwakeword.model import Model
from faster_whisper import WhisperModel

# --- CONFIGURATION ---
WAKEWORD_MODEL = "hey_smarthome_20260716_200659.onnx"
WHISPER_MODEL_NAME = "base"
OLLAMA_MODEL = "llama3.2"  # ou "mistral", "qwen2.5", etc.

SCORE_THRESHOLD = 0.5
VOICE_THRESHOLD = 700
SILENCE_DURATION = 1.0
MAX_RECORD_TIME = 10

RATE = 16000
CHUNK = 1280
FORMAT = pyaudio.paInt16
CHANNELS = 1

# --- CHARGEMENT ---
print("Chargement des modèles locaux... ⏳")
oww = Model(wakeword_model_paths=[WAKEWORD_MODEL])
whisper = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")

p = pyaudio.PyAudio()
stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

def transcribe(frames):
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
    wav_buffer.seek(0)

    segments, _ = whisper.transcribe(
        wav_buffer,
        language="fr",
        beam_size=3,
        condition_on_previous_text=False
    )
    return " ".join([seg.text for seg in segments]).strip()

def ask_ollama(prompt):
    """Envoie la commande à Ollama et affiche la réponse en continu"""
    print("🤖 Réponse : ", end="", flush=True)

    # Prompt système pour forcer des réponses courtes adaptées à la voix
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe (1 à 2 phrases max). N'utilise aucun formatage Markdown complexe."
        },
        {"role": "user", "content": prompt}
    ]

    response = ollama.chat(model=OLLAMA_MODEL, messages=messages, stream=True)
    for chunk in response:
        print(chunk["message"]["content"], end="", flush=True)
    print("\n")

print("\n🟢 Prêt ! Dis ton mot-clé... 🎙️\n")

try:
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_chunk = np.frombuffer(data, dtype=np.int16)

        oww.predict(audio_chunk)
        model_name = list(oww.prediction_buffer.keys())[0]
        score = oww.prediction_buffer[model_name][-1]

        if score > SCORE_THRESHOLD:
            print(f"✨ Mot-clé détecté ! (Score: {score:.2f}) -> Je t'écoute... 👂")
            oww.reset()

            frames = []
            is_speaking = False
            silence_start = None
            start_listen = time.time()

            while time.time() - start_listen < MAX_RECORD_TIME:
                cmd_data = stream.read(CHUNK, exception_on_overflow=False)
                cmd_chunk = np.frombuffer(cmd_data, dtype=np.int16)
                vol = np.abs(cmd_chunk).mean()
                frames.append(cmd_data)

                if vol > VOICE_THRESHOLD:
                    is_speaking = True
                    silence_start = None
                elif is_speaking:
                    if silence_start is None:
                        silence_start = time.perf_counter()
                    elif time.perf_counter() - silence_start > SILENCE_DURATION:
                        break

            if is_speaking and frames:
                text = transcribe(frames)
                if text:
                    print(f"👉 Toi : « {text} »")
                    ask_ollama(text)
                else:
                    print("⚠️ Aucun texte reconnu.\n")
            else:
                print("⚠️ Aucune phrase détectée.\n")

            print("🟢 En attente du mot-clé... 🎙️")

except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    stream.stop_stream()
    stream.close()
    p.terminate()
