import sys
import threading
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
from audio.speech import SpeechPipeline
from audio.barge_in import BargeInDetector
from llm.providers import LLM_PROVIDERS
from actions import get_all_commands
from core.assistant import AssistantCore, Reply
from core.mcp_hub import get_mcp_hub
from core.security import require_token_for_host

LOCAL_SESSION = "local"




def flush_stream(stream):
    """Purge les données audio résiduelles du flux micro."""
    try:
        avail = stream.get_read_available()
        if avail > 0:
            stream.read(avail, exception_on_overflow=False)
    except Exception:
        pass


def _print_event(event):
    """Affichage console : réponse en streaming pour le micro local, résumé des échanges distants."""
    if event.session_id == LOCAL_SESSION:
        if event.type == "token":
            print(event.data["text"], end="", flush=True)
        return
    tag = f"🌍 [{event.session_id}]"
    if event.type == "transcript":
        print(f"\n{tag} 👤 « {event.data['text']} »")
    elif event.type == "response":
        print(f"\n{tag} 🤖 « {event.data['text']} »")
    elif event.type == "confirm_request":
        print(f"\n{tag} ❓ {event.data['question']} (en attente du client)")


def run_local_turn(core, speech, stream, mic_lock, barge_in, user_input) -> Reply:
    """Traite une demande vocale locale. Le traitement tourne dans un thread pendant que ce thread-ci continue
    de lire le micro : l'utilisateur peut ainsi interrompre l'assistant pendant qu'il réfléchit ou parle."""
    streaming = core.settings.TTS_STREAMING
    result: dict = {}

    def work():
        kwargs = {"audio_wav": user_input} if isinstance(user_input, bytes) else {"text": user_input}
        try:
            result["reply"] = core.respond(LOCAL_SESSION, on_sentence=speech.say if streaming else None, **kwargs)
        except Exception as e:
            result["error"] = e

    worker = threading.Thread(target=work, name="local-turn", daemon=True)
    worker.start()
    barge_in.reset()
    spoken_at_end = streaming

    while worker.is_alive() or speech.busy or not spoken_at_end:
        if not worker.is_alive() and not spoken_at_end:
            # Mode sans streaming : la réponse complète est dite une fois générée (et reste interruptible)
            spoken_at_end = True
            if "reply" in result:
                speech.say(result["reply"].text)
            continue
        with mic_lock:
            data = stream.read(CHUNK, exception_on_overflow=False)
        if barge_in.process(np.frombuffer(data, dtype=np.int16)):
            print("\n✋ Interruption : je vous écoute.")
            core.cancel(LOCAL_SESSION)
            speech.interrupt()
            worker.join(timeout=30)
            speech.wait(timeout=2)
            reply = result.get("reply") or Reply(LOCAL_SESSION)
            reply.interrupted = True
            return reply

    worker.join()
    if "error" in result:
        raise result["error"]
    return result["reply"]


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
    # Cœur partagé entre le micro local et les clients distants (mêmes modèles chargés une seule fois)
    core = AssistantCore(settings, stt=transcriber.stt, tts=tts)
    local = core.open_session(LOCAL_SESSION, persistent=True)
    # Voix en streaming (phrase par phrase, interruptible) et micro partagé entre écoute et confirmation
    speech = SpeechPipeline(tts, output_device=settings.AUDIO_OUTPUT_DEVICE_INDEX)
    mic_lock = threading.Lock()
    barge_in = BargeInDetector(settings, detector)
    # Les actions dangereuses demandées au micro (extinction, outils MCP destructeurs...) sont confirmées à la voix
    local.conversation.confirm = VoiceConfirmer(
        tts, transcriber, stream, settings, local.conversation, speak=speech.say_and_wait, mic_lock=mic_lock
    )
    core.events.subscribe(_print_event)
    conversation = local.conversation

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
    print(f"  • Voix TTS      : {tts_info}{' (streaming par phrase)' if settings.TTS_STREAMING else ''}")
    print(f"  • Interruption  : {barge_in.mode}")
    print(f"  • Actions OS    : {actions_info}")
    print(f"  • Appel d'outils: {tools_info}")
    print(f"  • Hub MCP       : {mcp_info}")

    gateway = None
    if settings.GATEWAY_ENABLED:
        require_token_for_host(settings.GATEWAY_HOST, settings.GATEWAY_AUTH_TOKEN, "GATEWAY", "GATEWAY_AUTH_TOKEN")
        from gateway.app import start_in_thread
        gateway, _ = start_in_thread(core, settings)
        auth = "jeton requis" if settings.GATEWAY_AUTH_TOKEN else "loopback, sans jeton"
        print(f"  • Passerelle    : ws://{settings.GATEWAY_HOST}:{settings.GATEWAY_PORT}/ws ({auth})")
    else:
        print("  • Passerelle    : Désactivée (GATEWAY_ENABLED=false)")
    print(f"  • Veille active : {FOLLOW_UP_TIMEOUT}s\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            detected, score = detector.process_chunk(chunk)

            if detected:
                print(f"\n🎯 Mot-clé détecté ({detector.model_name}, score {score:.2f})")
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
                            else:
                                print(f"👤 : « {user_input} » ({elapsed_t:.2f} s)")
                            print("🤖 : ", end="", flush=True)

                            # 2. Réponse : actions exécutées et voix jouée au fil de la génération, interruptible
                            reply = run_local_turn(core, speech, stream, mic_lock, barge_in, user_input)
                            print()

                            # 3. Fin de conversation demandée (« au revoir », outil sleep) : retour en veille
                            if reply.end_conversation:
                                print("💤 Fin de conversation demandée.")
                                # Le LLM a déjà pris congé à voix haute : un simple son suffit
                                if reply.text:
                                    feedback.play_sound(settings.FEEDBACK_TIMEOUT_SOUND)
                                else:
                                    feedback.on_timeout()
                                in_conversation = False
                                continue

                            # 4. Signal de passage de la parole (son court si l'utilisateur a interrompu)
                            if reply.interrupted:
                                if settings.BARGE_IN_SOUND:
                                    feedback.play_sound(settings.BARGE_IN_SOUND)
                            else:
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
        if gateway:
            gateway.should_exit = True
        if mcp_hub and MCP_CLIENT_ENABLED:
            mcp_hub.disconnect_all()
        ducker.unduck()
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()




