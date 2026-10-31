import sys
import numpy as np
import pyaudio
from core.config import (
    get_settings,
    CHUNK,
    RATE,
    CHANNELS,
    AUDIO_INPUT_DEVICE_INDEX,
    FOLLOW_UP_TIMEOUT,
    LLM_HISTORY_MESSAGES,
    ACTIONS_ENABLED,
    MCP_CLIENT_ENABLED,
)
from audio.wakeword import WakeWordDetector, FORMAT
from audio.transcribe import VoiceTranscriber
from audio.tts import TextToSpeech
from audio.feedback import FeedbackManager
from audio.ducking import AudioDucker
from audio.confirm import VoiceConfirmer
from llm.llm import ask_llm, get_conversation
from llm.providers import LLM_PROVIDERS
from actions import get_action_manager, get_all_commands
from core.mcp_hub import get_mcp_hub
from core.tools import set_confirmation_handler




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
    mcp_hub = get_mcp_hub() if MCP_CLIENT_ENABLED else None

    # Connexion aux serveurs MCP configurés
    mcp_info = "Désactivé"
    if mcp_hub and MCP_CLIENT_ENABLED:
        try:
            mcp_results = mcp_hub.connect_all()
            connected_names = [name for name, ok in mcp_results.items() if ok]
            total_tools = len(mcp_hub.tool_to_server)
            if connected_names:
                mcp_info = f"Actif ({len(connected_names)} serveur(s) : {', '.join(connected_names)} | {total_tools} outils)"
            else:
                mcp_info = "Actif (Aucun serveur connecté)"
        except Exception as e:
            mcp_info = f"Erreur de connexion ({e})"

    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INPUT_DEVICE_INDEX,
        frames_per_buffer=CHUNK
    )

    settings = get_settings()
    conversation = get_conversation()
    # Les actions dangereuses (extinction, outils MCP destructeurs...) sont confirmées à la voix
    set_confirmation_handler(VoiceConfirmer(tts, transcriber, stream, settings, conversation))

    llm_info = LLM_PROVIDERS.get(settings.LLM_PROVIDER).describe(settings)
    stt_info = transcriber.stt.describe(settings)
    tts_info = tts.engine.describe(settings)
    actions_info = f"Activées ({len(get_all_commands())} commandes prêtes)" if ACTIONS_ENABLED else "Désactivées"
    tools = conversation.tools.all()
    to_confirm = sum(1 for t in tools if t.danger == "confirm")
    tools_info = (
        f"{settings.LLM_TOOL_CALLING} ({len(tools)} outils dont {to_confirm} avec confirmation vocale)"
        if settings.LLM_TOOL_CALLING != "tags" else "tags [ACTION] dans le texte"
    )

    print(f"\n🟢 Démarrage de SmartHome")
    print(f"  • Cerveau LLM   : {llm_info} (Mémoire: {LLM_HISTORY_MESSAGES} msgs)")
    print(f"  • Écoute STT    : {stt_info}")
    print(f"  • Voix TTS      : {tts_info}")
    print(f"  • Actions OS    : {actions_info}")
    print(f"  • Appel d'outils: {tools_info}")
    print(f"  • Hub MCP       : {mcp_info}")
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
        if mcp_hub and MCP_CLIENT_ENABLED:
            mcp_hub.disconnect_all()
        ducker.unduck()
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()




