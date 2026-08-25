import numpy as np
import pyaudio
from config import (
     CHUNK,
     RATE,
     CHANNELS,
     AUDIO_INPUT_DEVICE_INDEX,
     FOLLOW_UP_TIMEOUT,
)
from wakeword import WakeWordDetector, FORMAT
from transcribe import VoiceTranscriber
from llm import ask_llm
from tts import TextToSpeech
from feedback import FeedbackManager


def flush_stream(stream):
    """Purge les données audio résiduelles du flux micro."""
    try:
        avail = stream.get_read_available()
        if avail > 0:
            stream.read(avail, exception_on_overflow=False)
    except Exception:
        pass


def main():
    print("Initialisation des composants... ⏳")
    detector = WakeWordDetector()
    transcriber = VoiceTranscriber()
    tts = TextToSpeech()
    feedback = FeedbackManager(tts=tts)

    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INPUT_DEVICE_INDEX,
        frames_per_buffer=CHUNK
    )

    print("\n🟢 Démarrage\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            detected, score = detector.process_chunk(chunk)

            if detected:
                print(f"✨ Mot-clé détecté ! (Score: : {score:.2f})")
                
                # Signal / Phrase de prise en compte du mot-clé
                feedback.on_wakeword_detected()
                in_conversation = True

                while in_conversation:
                    text, inf_t, _ = transcriber.record_and_transcribe(
                        stream,
                        timeout_silence=FOLLOW_UP_TIMEOUT
                    )

                    if text:
                        print(f"👤 : « {text} » ({inf_t:.2f} s)")
                        print("🤖 : ", end="", flush=True)

                        # 1. Génération de la réponse Ollama
                        response_text = ask_llm(text)

                        # 2. Vocalisation de la réponse
                        if response_text:
                            tts.speak(response_text)

                        # 3. Signal de fin de réponse (passage de la parole)
                        feedback.on_response_end()

                        print("\n" + "-" * 40)
                    else:
                        # print("\n😴 Fin de la session.")
                        
                        # Signal / Phrase de mise en veille
                        feedback.on_timeout()
                        flush_stream(stream)
                        detector.oww.reset()
                        in_conversation = False

                print("\n🟢 Veille...\n")

    except KeyboardInterrupt:
        print("\nArrêt de l'assistant.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()


