import queue
import sys
import threading

from core.profiles import active_profile, describe_profile, pop_profile_argument, warn_shadowed_profile

pop_profile_argument(sys.argv)  # --profile <nom> doit être connu avant le chargement de core.config

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
from audio.media_pause import MediaPauser
from audio.confirm import VoiceConfirmer
from audio.speech import SpeechPipeline
from audio.barge_in import BargeInDetector
from llm.providers import LLM_PROVIDERS
from actions import get_all_commands
from core.assistant import AssistantCore, Reply
from core.mcp_hub import get_mcp_hub
from core.remote_voice import RemoteVoiceGuard
from core.restart import restart_if_requested
from core.security import require_token_for_host
from core.users import LOCAL_USER_ID, local_user

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
        elif event.type == "transcript":
            # Mode direct avec un modèle sans entrée audio : transcription de repli faite par le cœur
            print(f"\r👤 : « {event.data['text']} »\n🤖 : ", end="", flush=True)
        return
    tag = f"🌍 [{event.session_id}]"
    if event.type == "transcript":
        print(f"\n{tag} 👤 « {event.data['text']} »")
    elif event.type == "response":
        print(f"\n{tag} 🤖 « {event.data['text']} »")
    elif event.type == "confirm_request":
        print(f"\n{tag} ❓ {event.data['question']} (en attente du client)")


def watch_reminders(core) -> "queue.Queue[str]":
    """Rappels à dire sur l'ordinateur (SCHEDULER_LOCAL_ANNOUNCE) : mis en file, dits dès que l'assistant est en veille."""
    pending: "queue.Queue[str]" = queue.Queue()

    def on_event(event):
        if event.type != "reminder" or not event.data.get("text"):
            return
        mode = core.settings.SCHEDULER_LOCAL_ANNOUNCE
        household = (event.data.get("user_id") or LOCAL_USER_ID) == LOCAL_USER_ID
        if mode == "all" or (mode == "household" and household):
            pending.put(event.data["text"])

    core.events.subscribe(on_event)
    return pending


def announce_reminders(pending, speech, feedback, media_pauser, ducker, stream, detector, settings):
    """Dit les rappels en attente (son, puis la phrase), médias en pause, puis purge l'écho du micro."""
    media_pauser.pause()
    ducker.duck()
    try:
        while True:
            try:
                text = pending.get_nowait()
            except queue.Empty:
                break
            print(f"\n⏰ {text}")
            if settings.SCHEDULER_SOUND:
                feedback.play_sound(settings.SCHEDULER_SOUND)
            speech.say_and_wait(text)
    finally:
        if ducker.enabled:
            ducker.unduck()
        media_pauser.resume()
        flush_stream(stream)
        detector.oww.reset()


def run_local_turn(core, speech, stream, mic_lock, barge_in, user_input, remote=None) -> Reply:
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
        if remote is not None and remote.active():
            # On parle maintenant au téléphone : réponse locale abandonnée et retour en veille
            core.cancel(LOCAL_SESSION)
            speech.interrupt()
            worker.join(timeout=30)
            speech.wait(timeout=2)
            reply = result.get("reply") or Reply(LOCAL_SESSION)
            reply.interrupted = True
            reply.end_conversation = True
            return reply
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

    settings = get_settings()
    print("Initialisation des composants... ⏳")
    detector = WakeWordDetector()
    transcriber = VoiceTranscriber(settings)
    tts = TextToSpeech(settings)
    feedback = FeedbackManager(tts=tts, settings=settings)
    media_pauser = MediaPauser()
    # La pause des médias suffit : baisser le son en plus est redondant et laisse des volumes bridés
    ducker = AudioDucker(enabled=settings.DUCKING_ENABLED and not media_pauser.enabled)
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

    # Cœur partagé entre le micro local et les clients distants (mêmes modèles chargés une seule fois)
    core = AssistantCore(settings, stt=transcriber.stt, tts=tts)
    # Le micro n'identifie pas la voix : compte fixe « Foyer » (rôle AUTH_LOCAL_ROLE)
    local = core.open_session(LOCAL_SESSION, persistent=True, user=local_user(settings))
    # Voix en streaming (phrase par phrase, interruptible) et micro partagé entre écoute et confirmation
    # La voix suit la session : voix alternative quand un agent externe (Hermes, Claude...) est relié
    speech = SpeechPipeline(tts, output_device=settings.AUDIO_OUTPUT_DEVICE_INDEX,
                            voice=lambda: core.session_voice(LOCAL_SESSION))
    mic_lock = threading.Lock()
    barge_in = BargeInDetector(settings, detector)
    # Micro du téléphone utilisé : l'ordinateur entend la même voix mais doit rester en veille
    remote = RemoteVoiceGuard(core.events, LOCAL_SESSION, hold=settings.REMOTE_VOICE_HOLD,
                              enabled=settings.REMOTE_VOICE_SLEEP and settings.GATEWAY_ENABLED)
    # Les actions dangereuses demandées au micro (extinction, outils MCP destructeurs...) sont confirmées à la voix
    local.conversation.confirm = VoiceConfirmer(
        tts, transcriber, stream, settings, local.conversation, speak=speech.say_and_wait, mic_lock=mic_lock
    )
    core.events.subscribe(_print_event)
    conversation = local.conversation
    reminders = watch_reminders(core)
    core.start_scheduler()

    llm_info = LLM_PROVIDERS.get(settings.LLM_PROVIDER).describe(settings)
    stt_info = transcriber.stt.describe(settings)
    if transcriber.stt.passthrough:
        if core.audio_to_llm():
            stt_info += f" — {core.llm.model} comprend l'audio ✅"
        else:
            stt_info += f" — {core.llm.model} ne comprend pas l'audio : transcription par {settings.STT_FALLBACK_PROVIDER}"
            core.fallback_stt  # chargé dès maintenant plutôt qu'à la première demande
    tts_info = tts.engine.describe(settings)
    actions_info = f"Activées ({len(get_all_commands())} commandes prêtes)" if ACTIONS_ENABLED else "Désactivées"
    tools = conversation.tools.all()
    to_confirm = sum(1 for t in tools if t.danger == "confirm")
    tools_info = (
        f"{settings.LLM_TOOL_CALLING} ({len(tools)} outils dont {to_confirm} avec confirmation vocale)"
        if settings.LLM_TOOL_CALLING != "tags" else "tags [ACTION] dans le texte"
    )

    print("\n🟢 Démarrage de SmartHome")
    print(f"  • Profil        : {active_profile()} — {describe_profile(active_profile())}")
    warn_shadowed_profile()
    print(f"  • Cerveau LLM   : {llm_info} (Mémoire: {LLM_HISTORY_MESSAGES} msgs)")
    print(f"  • Écoute STT    : {stt_info}")
    print(f"  • Voix TTS      : {tts_info}{' (streaming par phrase)' if settings.TTS_STREAMING else ''}")
    print(f"  • Interruption  : {barge_in.mode}")
    print(f"  • Actions OS    : {actions_info}")
    print(f"  • Appel d'outils: {tools_info}")
    print(f"  • Hub MCP       : {mcp_info}")
    print(f"  • Rappels       : {'Actifs (annonce : ' + settings.SCHEDULER_LOCAL_ANNOUNCE + ')' if settings.SCHEDULER_ENABLED else 'Désactivés'}")

    gateway = None
    pocketbase = None
    if settings.GATEWAY_ENABLED:
        require_token_for_host(settings.GATEWAY_HOST, settings.GATEWAY_AUTH_TOKEN, "GATEWAY", "GATEWAY_AUTH_TOKEN")
        # Comptes de la PWA (AUTH_PROVIDER=pocketbase) : annuaire lancé avec SmartHome s'il ne tourne pas déjà
        from core.pocketbase import ensure_running
        pocketbase = ensure_running(settings)
        from gateway.app import start_in_thread
        gateway, _ = start_in_thread(core, settings)
        auth = "jeton requis" if settings.GATEWAY_AUTH_TOKEN else "loopback, sans jeton"
        print(f"  • Passerelle    : ws://{settings.GATEWAY_HOST}:{settings.GATEWAY_PORT}/ws ({auth})")
        from core.pairing import print_pairing
        print_pairing(settings)
    else:
        print("  • Passerelle    : Désactivée (GATEWAY_ENABLED=false)")
    print(f"  • Veille active : {FOLLOW_UP_TIMEOUT}s\n")

    core.local_microphone = True
    wakeword_on = settings.WAKEWORD_ENABLED
    if not wakeword_on:
        print("🔇 Écoute du mot-clé désactivée (WAKEWORD_ENABLED=false) : réactivable depuis les réglages de la PWA.")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            # Rappels arrivés à échéance pendant la veille (ceux d'une conversation attendent sa fin)
            if not reminders.empty():
                announce_reminders(reminders, speech, feedback, media_pauser, ducker, stream, detector, core.settings)
                continue
            # Écoute du mot-clé coupée depuis l'interface (faux positifs) : le flux est lu mais pas analysé
            enabled = core.settings.WAKEWORD_ENABLED
            if enabled != wakeword_on:
                wakeword_on = enabled
                detector.oww.reset()
                print("\n👂 Écoute du mot-clé réactivée." if enabled else "\n🔇 Écoute du mot-clé désactivée.")
            if not wakeword_on:
                continue
            chunk = np.frombuffer(data, dtype=np.int16)
            detected, score = detector.process_chunk(chunk)

            if detected and remote.active():
                print(f"\n📱 Mot-clé ignoré ({detector.model_name}, score {score:.2f}) : conversation en cours sur un client distant")
                detector.oww.reset()
                continue

            if detected:
                print(f"\n🎯 Mot-clé détecté ({detector.model_name}, score {score:.2f})")
                # 1. Atténuation immédiate des autres sources audio (musique, vidéos, etc.)
                media_pauser.pause()
                ducker.duck()

                try:
                    # Signal / Phrase de prise en compte du mot-clé
                    feedback.on_wakeword_detected()
                    in_conversation = True

                    while in_conversation:
                        user_input, elapsed_t, _ = transcriber.record_and_transcribe(
                            stream,
                            timeout_silence=FOLLOW_UP_TIMEOUT,
                            should_stop=remote.active,
                        )

                        if remote.active():
                            # On parle au téléphone : l'ordinateur se tait et repasse directement en veille
                            print("\n📱 Conversation reprise sur un client distant : mise en veille.")
                            in_conversation = False
                            continue

                        if user_input:
                            if isinstance(user_input, bytes):
                                where = "envoyé au LLM" if core.audio_to_llm() else "à transcrire"
                                print(f"👤 : 🎙️ [Audio {where}] ({elapsed_t:.2f} s)")
                            else:
                                print(f"👤 : « {user_input} » ({elapsed_t:.2f} s)")
                            print("🤖 : ", end="", flush=True)

                            # 2. Réponse : actions exécutées et voix jouée au fil de la génération, interruptible
                            reply = run_local_turn(core, speech, stream, mic_lock, barge_in, user_input, remote)
                            print()

                            # 3. Fin de conversation demandée (« au revoir », outil sleep) : retour en veille
                            if reply.end_conversation and remote.active():
                                print("\n📱 Conversation reprise sur un client distant : mise en veille.")
                                in_conversation = False
                                continue
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
                            if settings.AGENTS_LEAVE_ON_SLEEP:
                                core.set_agent(LOCAL_SESSION, None)

                except Exception as e:
                    print(f"\n⚠️ [ERREUR] Échange interrompu : {e}")
                finally:
                    # 2. Restauration systématique du son et retour en veille
                    if ducker.enabled:
                        ducker.unduck()
                    media_pauser.resume()
                    flush_stream(stream)
                    detector.oww.reset()
                    # Chaque réveil est une conversation distincte dans l'archive (affichée dans la PWA)
                    core.new_local_conversation(LOCAL_SESSION)
                    print("\n🟢 Veille...\n")

    except KeyboardInterrupt:
        print("\nArrêt de l'assistant.")
    finally:
        core.stop_scheduler()
        remote.close()
        if gateway:
            gateway.should_exit = True
        if pocketbase:
            pocketbase.stop()
        if mcp_hub and MCP_CLIENT_ENABLED:
            mcp_hub.disconnect_all()
        if ducker.enabled:
            ducker.unduck()
        media_pauser.resume()
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
    restart_if_requested()




