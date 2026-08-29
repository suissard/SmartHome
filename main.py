import sys
import numpy as np
import pyaudio
from core.config import (
    CHUNK,
    RATE,
    CHANNELS,
    AUDIO_INPUT_DEVICE_INDEX,
    FOLLOW_UP_TIMEOUT,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OPENROUTER_MODEL,
    STT_PROVIDER,
    WHISPER_MODEL,
    OPENROUTER_STT_MODEL,
    TTS_PROVIDER,
    TTS_MODEL_PATH,
    OPENROUTER_TTS_MODEL,
    LLM_HISTORY_MESSAGES,
    ACTIONS_ENABLED,
)
from audio.wakeword import WakeWordDetector, FORMAT
from audio.transcribe import VoiceTranscriber
from audio.tts import TextToSpeech
from audio.feedback import FeedbackManager
from audio.ducking import AudioDucker
from llm.llm import ask_llm
from actions import get_action_manager




def flush_stream(stream):
    """Purge les données audio résiduelles du flux micro."""
    try:
        avail = stream.get_read_available()
        if avail > 0:
            stream.read(avail, exception_on_overflow=False)
    except Exception:
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--reset-sound", "--reset", "--restore", "-r"):
        AudioDucker.reset_all()
        return

    print("Initialisation des composants... ⏳")
    detector = WakeWordDetector()
    transcriber = VoiceTranscriber()
    tts = TextToSpeech()
    feedback = FeedbackManager(tts=tts)
    ducker = AudioDucker()
    action_manager = get_action_manager()

    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INPUT_DEVICE_INDEX,
        frames_per_buffer=CHUNK
    )

    llm_info = f"OpenRouter ({OPENROUTER_MODEL})" if LLM_PROVIDER == "openrouter" else f"Ollama ({OLLAMA_MODEL})"
    if STT_PROVIDER in ("none", "direct", "bypass"):
        stt_info = "Direct Audio (Bypass STT ⏩ Multimodal LLM)"
    elif STT_PROVIDER == "openrouter":
        stt_info = f"OpenRouter ({OPENROUTER_STT_MODEL})"
    else:
        stt_info = f"Whisper ({WHISPER_MODEL})"
    tts_info = f"OpenRouter ({OPENROUTER_TTS_MODEL})" if TTS_PROVIDER == "openrouter" else f"Piper ({TTS_MODEL_PATH})"
    actions_info = "Activées (12 commandes prêtes)" if ACTIONS_ENABLED else "Désactivées"

    print(f"\n🟢 Démarrage de SmartHome")
    print(f"  • Cerveau LLM   : {llm_info} (Mémoire: {LLM_HISTORY_MESSAGES} msgs)")
    print(f"  • Écoute STT    : {stt_info}")
    print(f"  • Voix TTS      : {tts_info}")
    print(f"  • Actions OS    : {actions_info}")
    print(f"  • Veille active : {FOLLOW_UP_TIMEOUT}s\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            detected, score = detector.process_chunk(chunk)

            if detected:
                # 1. Atténuation immédiate des autres sources audio (musique, vidéos, etc.)
                ducker.duck()

                try:
                    # Signal / Phrase de prise en compte du mot-clé
                    feedback.on_wakeword_detected()
                    in_conversation = True

                    while in_conversation:
                        user_input, elapsed_t, _ = transcriber.record_and_transcribe(
                            stream,
                            timeout_silence=FOLLOW_UP_TIMEOUT
                        )

                        if user_input:
                            if isinstance(user_input, bytes):
                                print(f"👤 : 🎙️ [Audio envoyé au LLM] ({elapsed_t:.2f} s)")
                                print("🤖 : ", end="", flush=True)
                                response_text = ask_llm(audio_bytes=user_input)
                            else:
                                print(f"👤 : « {user_input} » ({elapsed_t:.2f} s)")
                                print("🤖 : ", end="", flush=True)
                                response_text = ask_llm(prompt=user_input)

                            # 2. Exécution des actions système & Nettoyage du texte pour la voix
                            clean_voice_text = response_text
                            if response_text and ACTIONS_ENABLED:
                                clean_voice_text = action_manager.process_response(response_text)

                            # 3. Vocalisation de la réponse
                            if clean_voice_text:
                                tts.speak(clean_voice_text)

                            # 4. Signal de fin de réponse (passage de la parole)
                            feedback.on_response_end()

                            print("\n" + "-" * 40)
                        else:
                            # Signal / Phrase de mise en veille
                            feedback.on_timeout()
                            in_conversation = False

                except Exception as e:
                    print(f"\n⚠️ [ERREUR] Échange interrompu : {e}")
                finally:
                    # 2. Restauration systématique du son et retour en veille
                    ducker.unduck()
                    flush_stream(stream)
                    detector.oww.reset()
                    print("\n🟢 Veille...\n")

    except KeyboardInterrupt:
        print("\nArrêt de l'assistant.")
    finally:
        ducker.unduck()
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()




