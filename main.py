import numpy as np
import pyaudio
from wakeword import WakeWordDetector, CHUNK, RATE, FORMAT
from transcribe import VoiceTranscriber
from llm import ask_llm
from tts import TextToSpeech

FOLLOW_UP_TIMEOUT = 30.0

def main():
    print("Initialisation des composants... ⏳")
    detector = WakeWordDetector()
    transcriber = VoiceTranscriber(model_name="base")
    tts = TextToSpeech()

    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=1,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

    print("\n🟢 Assistant prêt avec voix active ! En attente du mot-clé... 🎙️\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            detected, score = detector.process_chunk(chunk)

            if detected:
                print(f"✨ Mot-clé détecté ! (Score : {score:.2f})")
                in_conversation = True

                while in_conversation:
                    text, inf_t, _ = transcriber.record_and_transcribe(
                        stream,
                        timeout_silence=FOLLOW_UP_TIMEOUT
                    )

                    if text:
                        print(f"👉 Toi : « {text} » ({inf_t:.2f} s)")
                        print("🤖 Assistant : ", end="", flush=True)

                        # 1. Génération de la réponse Ollama
                        response_text = ask_llm(text)

                        # 2. Vocalisation de la réponse
                        if response_text:
                            tts.speak(response_text)

                        print("\n" + "-" * 40)
                    else:
                        print("\n😴 Fin de la session.")
                        in_conversation = False

                print("\n🟢 En veille : en attente du mot-clé... 🎙️\n")

    except KeyboardInterrupt:
        print("\nArrêt de l'assistant.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
