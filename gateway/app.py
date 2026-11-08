"""
Passerelle réseau de SmartHome : permet de piloter l'assistant depuis un autre appareil (LAN, Tailscale).

Routes :
- GET  /health   : état (sans authentification)
- POST /api/ask  : {"text" | "audio" (WAV base64), "session"?, "speak"?} -> réponse JSON (sans confirmation possible :
                   les actions dangereuses sont refusées)
- WS   /ws       : session interactive (streaming, outils, confirmations). Protocole JSON :
    client -> serveur : {"type": "auth", "token"?, "session"?}  (premier message si pas d'en-tête Authorization)
                        Comptes (AUTH_PROVIDER, voir core/users.py) : {"type": "auth", "identity", "password", "session"?}
                        ou {"type": "auth", "user_token", "session"?} ; le jeton maître ("token") donne l'accès administrateur
                        {"type": "text", "text", "speak"?} | {"type": "audio", "data": <WAV base64>, "speak"?}
                        (avec "turn"? : identifiant de l'échange, repris dans ses événements et "done" ; "forget"? : échanges
                        à retirer d'abord de l'historique, pour relancer à partir d'un message)
                        {"type": "forget", "turns", "role"?} | {"type": "edit_answer", "turn", "text", "forget"?}
                        {"type": "confirm_response", "id", "accepted": bool} | {"type": "stop"} | {"type": "reset"}
                        | {"type": "ping"}
                        Profil du compte connecté : {"type": "update_profile", "name", "instructions", "voice"?}
                        | {"type": "preview_voice", "voice"} (phrase d'essai renvoyée en {"type": "voice_preview", "data"})
                        Paramètres (voir core/settings_store.py) : {"type": "get_settings"} | {"type": "list_models", "provider"?: nom}
                        | {"type": "update_settings", "values": {VARIABLE: valeur}} | {"type": "restart"}
    serveur -> client : {"type": "ready", "session", "user", "tools", "audio", "confirm_timeout", "llm"} puis les événements du cœur
                        ("user" : {"id", "name", "role", "admin", "token"?} ; "token" = jeton du compte à réutiliser,
                        refus : {"type": "error", "message", "accounts"} puis fermeture 4401)
                        (transcript, token, tool, confirm_request, response, interrupted, error), la voix si speak :
                        {"type": "audio_chunk", "seq", "format": "wav", "data"} phrase par phrase (TTS_STREAMING)
                        ou {"type": "audio", ...} en un bloc, et {"type": "done"} à la fin de chaque demande.
                        Paramètres : {"type": "settings", "groups", "llm"} | {"type": "models", "models", "error"?}
                        | {"type": "settings_saved", "changed", "restart", "overridden", "llm"} | {"type": "settings_error", "message"}
                        | {"type": "profile_saved", "user"} | {"type": "profile_error", "message"}
                        ; "ready.history" : [{role, content, turn?}] (conversation en cours, rechargée depuis
                        l'historique du compte si la session est neuve)
                        ; "settings_changed" est diffusé à tous les clients après une modification,
                        "restarting" juste avant un redémarrage demandé par un client.
                        Paramètres, liste des modèles et redémarrage sont réservés aux rôles AUTH_ADMIN_ROLES.
"""

import asyncio
import base64
import concurrent.futures
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from audio.speech import SpeechPipeline
from audio.confirm import classify_confirmation
from core.assistant import AssistantCore, Reply, to_wav_bytes
from core import restart, settings_store
from core.config import Settings
from core.security import (
    BearerTokenMiddleware, LocalOnlyMiddleware, SecurityHeadersMiddleware, bearer_from_headers, token_matches,
)
from core.users import AuthError, DirectoryUnavailable, User, admin_user, create_directory, is_admin

# Interface web (PWA) servie à la racine : publique, elle ne contient aucun secret (le jeton est saisi par l'utilisateur)
WEB_DIR = Path(__file__).resolve().parent / "web"

# Code de fermeture WebSocket pour un jeton refusé (plage 4000-4999 réservée aux applications)
WS_UNAUTHORIZED = 4401
AUTH_TIMEOUT_SECONDS = 10
RESTART_DELAY_SECONDS = 0.3
ADMIN_ONLY_MESSAGE = "Réservé aux administrateurs."


def _reply_to_dict(reply: Reply) -> dict:
    data = {"session": reply.session_id, "transcript": reply.transcript, "text": reply.text, "tools": reply.tools}
    if reply.audio_wav:
        data["audio"] = {"format": "wav", "data": base64.b64encode(reply.audio_wav).decode()}
    return data


def create_app(core: AssistantCore, settings: Optional[Settings] = None):
    # Le jeton et l'adresse sont fixés au démarrage ; le reste est relu dans core.settings (modifiable à chaud)
    token = (settings or core.settings).GATEWAY_AUTH_TOKEN
    # Annuaire des comptes (AUTH_PROVIDER), fixé au démarrage comme le jeton
    directory = create_directory(settings or core.settings)

    def identify(hello: dict) -> User:
        """Identité annoncée par le premier message : jeton maître, identifiant + mot de passe, ou jeton de compte.
        Bloquant (requête à l'annuaire). Lève AuthError / DirectoryUnavailable."""
        if hello.get("type") != "auth":
            raise AuthError("Jeton manquant ou invalide.")
        # Une connexion explicite à un compte passe avant le jeton maître resté enregistré sur l'appareil
        if directory.enabled and hello.get("identity"):
            return directory.login(str(hello.get("identity", "")).strip(), str(hello.get("password", "")))
        if token_matches(str(hello.get("token") or ""), token):
            return admin_user(core.settings)
        if directory.enabled and hello.get("user_token"):
            return directory.refresh(str(hello["user_token"]))
        raise AuthError("Identifiant et mot de passe requis." if directory.enabled else "Jeton manquant ou invalide.")

    async def health(request: Request):
        return JSONResponse({
            "status": "ok",
            "service": "smarthome-gateway",
            "accounts": directory.enabled,
            "auth_required": bool(token),
        })

    async def ask(request: Request):
        try:
            body = await request.json()
            audio = base64.b64decode(body["audio"]) if body.get("audio") else None
        except Exception:
            return JSONResponse({"error": "Corps JSON invalide."}, status_code=400)
        if not body.get("text") and audio is None:
            return JSONResponse({"error": "Champ 'text' ou 'audio' requis."}, status_code=400)
        # Seul le jeton maître protège /api/ask : c'est l'administrateur
        session = core.open_session(body.get("session"), user=admin_user(core.settings))
        reply = await asyncio.to_thread(
            core.respond, session.id, text=body.get("text"), audio_wav=audio, synthesize=bool(body.get("speak"))
        )
        return JSONResponse(_reply_to_dict(reply))

    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        loop = asyncio.get_running_loop()

        # 1. Authentification : en-tête Authorization, sinon premier message {"type": "auth"} (navigateurs)
        #    ou, avec des comptes (AUTH_PROVIDER), identifiant + mot de passe / jeton de compte
        hello: dict = {}
        authorized = not token or token_matches(bearer_from_headers(ws.scope.get("headers", [])), token)
        user = admin_user(core.settings)
        if not authorized:
            try:
                hello = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS))
                if not isinstance(hello, dict):
                    hello = {}
            except Exception:
                hello = {}
            try:
                user = await asyncio.to_thread(identify, hello)
            except (AuthError, DirectoryUnavailable) as e:
                if isinstance(e, DirectoryUnavailable):
                    print(f"⚠️ [GATEWAY] Annuaire des comptes indisponible : {e}")
                await ws.send_json({"type": "error", "message": str(e), "accounts": directory.enabled})
                await ws.close(code=WS_UNAUTHORIZED)
                return
        admin = is_admin(user, core.settings)

        outbox: asyncio.Queue = asyncio.Queue()

        def push(message: dict):
            # Appelé depuis les threads du pipeline : on repasse par la boucle asyncio
            loop.call_soon_threadsafe(outbox.put_nowait, message)

        # 2. Confirmation des actions dangereuses : question envoyée au client, attente de sa réponse
        pending: dict[str, concurrent.futures.Future] = {}

        def confirm(description: str) -> bool:
            request_id = uuid.uuid4().hex[:8]
            future: concurrent.futures.Future = concurrent.futures.Future()
            pending[request_id] = future
            s = core.settings
            question = s.ACTIONS_CONFIRM_PROMPT.format(action=description.strip().rstrip(".").lower())
            print(f"❓ [GATEWAY {session.id}] Demande de confirmation envoyée (id={request_id}) : « {question} »")
            if core.tts and not getattr(core.tts, "passthrough", False):
                try:
                    res = core.tts.synthesize(question, voice=core.session_voice(session.id))
                    if res:
                        samples, sr = res
                        if len(samples) > 0:
                            wav_data = to_wav_bytes(samples, sr)
                            push({"type": "audio_chunk", "seq": 0, "format": "wav", "data": base64.b64encode(wav_data).decode("ascii")})
                except Exception as e:
                    print(f"⚠️ [GATEWAY {session.id}] Erreur synthèse TTS confirmation : {e}")
            core.events.emit("confirm_request", session.id, id=request_id, question=question)
            try:
                res = bool(future.result(timeout=s.GATEWAY_CONFIRM_TIMEOUT))
                print(f"{'✅' if res else '⛔'} [GATEWAY {session.id}] Confirmation {request_id} : {'Acceptée' if res else 'Refusée'}")
                return res
            except concurrent.futures.TimeoutError:
                print(f"⏰ [GATEWAY {session.id}] Délai expiré ({s.GATEWAY_CONFIRM_TIMEOUT}s) pour confirmation {request_id}")
                return False
            finally:
                pending.pop(request_id, None)

        session_id = hello.get("session") or ws.query_params.get("session")
        session = core.open_session(session_id, confirm=confirm, user=user)
        client_ip = getattr(ws.client, "host", ws.client[0] if isinstance(ws.client, (tuple, list)) else "inconnu") if ws.client else "inconnu"
        print(f"🔌 [GATEWAY {session.id}] {user.name} (rôle {user.role}) connecté depuis {client_ip}")
        unsubscribe = core.events.subscribe(lambda e: push(e.to_dict()), session_id=session.id)
        # Modifications de paramètres faites depuis un autre appareil : chaque client recharge son formulaire
        unsubscribe_settings = core.events.subscribe(
            lambda e: push(e.to_dict()) if e.type in ("settings_changed", "restarting") else None
        )

        async def sender():
            while True:
                await ws.send_json(await outbox.get())

        speeches: set[SpeechPipeline] = set()

        def streamed_speech() -> SpeechPipeline:
            """Voix envoyée phrase par phrase au client, synthétisée pendant que le LLM génère la suite."""
            seq = iter(range(1_000_000))

            def send_chunk(samples, sample_rate):
                push({"type": "audio_chunk", "seq": next(seq), "format": "wav",
                      "data": base64.b64encode(to_wav_bytes(samples, sample_rate)).decode()})
            return SpeechPipeline(core.tts, sink=send_chunk, voice=core.session_voice(session.id))

        def run_request(text, audio, speak, turn, forget) -> Reply:
            speech = streamed_speech() if speak and core.settings.TTS_STREAMING else None
            if speech:
                speeches.add(speech)
            try:
                reply = core.respond(session.id, text=text, audio_wav=audio, synthesize=speak and not speech,
                                     on_sentence=speech.say if speech else None, turn=turn, forget=forget)
                if speech:
                    speech.wait()
                return reply
            finally:
                if speech:
                    speeches.discard(speech)
                    speech.close()

        async def handle(message: dict):
            turn = message.get("turn")
            tag = {"turn": turn} if turn else {}
            try:
                audio = base64.b64decode(message["data"]) if message["type"] == "audio" else None
                reply = await asyncio.to_thread(run_request, message.get("text"), audio, bool(message.get("speak")),
                                                turn, message.get("forget") or ())
                if reply.audio_wav:
                    push({"type": "audio", "format": "wav", "data": base64.b64encode(reply.audio_wav).decode()})
            except Exception as e:
                push({"type": "error", "message": str(e), **tag})
            finally:
                push({"type": "done", **tag})

        async def handle_history(message: dict):
            """Suppression d'un message ou correction d'une réponse (bloquant tant qu'une réponse est en cours)."""
            try:
                if message["type"] == "forget":
                    await asyncio.to_thread(core.forget, session.id, message.get("turns") or (), message.get("role"))
                else:
                    await asyncio.to_thread(core.edit_answer, session.id, message["turn"], str(message["text"]),
                                            message.get("forget") or ())
            except Exception as e:
                push({"type": "error", "message": f"Historique non modifié : {e}"})

        async def handle_conversations(message: dict):
            """Gestion des différentes conversations (liste, chargement, suppression)."""
            kind = message["type"]
            try:
                if kind == "list_conversations":
                    convs = await asyncio.to_thread(core.list_conversations, session.id)
                    push({"type": "conversations_list", "conversations": convs})
                elif kind == "load_conversation":
                    cid = str(message.get("conversation_id", "")).strip()
                    client_msgs = message.get("messages")
                    msgs = await asyncio.to_thread(core.load_conversation, session.id, cid, client_msgs)
                    push({"type": "conversation_loaded", "conversation_id": cid, "history": msgs})
                elif kind == "delete_conversation":
                    cid = str(message.get("conversation_id", "")).strip()
                    ok = await asyncio.to_thread(core.delete_conversation, session.id, cid)
                    push({"type": "conversation_deleted", "conversation_id": cid, "success": ok})
            except Exception as e:
                push({"type": "error", "message": f"Erreur conversation : {e}"})

        async def handle_profile(message: dict):
            """Prénom et consignes du compte, enregistrés dans l'annuaire avec le jeton du compte lui-même."""
            nonlocal user
            if not directory.enabled or not user.has_profile:
                push({"type": "profile_error", "message": "Profil disponible seulement avec un compte utilisateur."})
                return
            voice = str(message.get("voice", user.voice) or "")
            if voice and voice not in {v["id"] for v in core.voices()}:
                push({"type": "profile_error", "message": f"Voix « {voice} » non installée sur cette machine."})
                return
            try:
                updated = await asyncio.to_thread(directory.update_profile, user, message.get("name", ""),
                                                  message.get("instructions", ""), voice)
                core.set_session_user(session.id, updated)
                user = updated
                print(f"👤 [GATEWAY {session.id}] Profil de {user.name} mis à jour")
                push({"type": "profile_saved", "user": user.public(core.settings)})
            except (ValueError, AuthError, DirectoryUnavailable) as e:
                push({"type": "profile_error", "message": str(e)})
            except Exception as e:
                print(f"⚠️ [GATEWAY {session.id}] Profil non enregistré : {e!r}")
                push({"type": "profile_error", "message": f"Profil non enregistré : {e}"})

        async def handle_voice_preview(message: dict):
            """Phrase d'essai dans une voix installée, pour la choisir (jouée même si la réponse vocale est coupée)."""
            voice = str(message.get("voice") or "")
            if voice and voice not in {v["id"] for v in core.voices()}:
                push({"type": "profile_error", "message": f"Voix « {voice} » non installée sur cette machine."})
                return
            try:
                samples, rate = await asyncio.to_thread(core.tts.synthesize, core.settings.TTS_VOICE_PREVIEW_TEXT,
                                                        voice or None)
                if len(samples):
                    push({"type": "voice_preview", "voice": voice, "format": "wav",
                          "data": base64.b64encode(to_wav_bytes(samples, rate)).decode()})
            except Exception as e:
                push({"type": "profile_error", "message": f"Écoute impossible : {e}"})

        async def handle_settings(message: dict):
            """Lecture / modification des paramètres et liste des modèles (appels bloquants hors de la boucle)."""
            kind = message["type"]
            if not admin:
                push({"type": "settings_error", "message": ADMIN_ONLY_MESSAGE})
                return
            try:
                if kind == "list_models":
                    # Fournisseur demandé (champ de modèle d'un autre fournisseur que l'actif), sinon le fournisseur actif
                    name = str(message.get("provider") or core.settings.LLM_PROVIDER)
                    try:
                        if name == core.settings.LLM_PROVIDER:
                            provider = core.llm
                        else:
                            from llm.providers import LLM_PROVIDERS
                            provider = LLM_PROVIDERS.create(name, core.settings)
                        models = await asyncio.to_thread(provider.list_models)
                        push({"type": "models", "provider": name, "models": models})
                    except Exception as e:
                        push({"type": "models", "provider": name, "models": [],
                              "error": f"Liste des modèles indisponible : {e}"})
                    return
                if kind == "update_settings":
                    values = message.get("values")
                    if not isinstance(values, dict):
                        raise ValueError("Champ 'values' attendu : {VARIABLE: valeur}.")
                    result = await asyncio.to_thread(core.update_settings, values)
                    push({"type": "settings_saved", **result, "llm": core.model_info()})
                    if result["changed"]:
                        core.events.emit("settings_changed", None, changed=result["changed"])
                push({"type": "settings", "groups": settings_store.describe(core.settings), "llm": core.model_info()})
            except ValueError as e:
                push({"type": "settings_error", "message": str(e)})
            except Exception as e:
                push({"type": "settings_error", "message": f"Erreur : {e}"})

        # Conversation en cours (rechargée depuis l'historique du compte pour une session neuve) : la PWA la réaffiche
        try:
            history = await asyncio.to_thread(core.restore_history, session.id)
        except Exception as e:
            print(f"⚠️ [GATEWAY {session.id}] Historique non rechargé : {e}")
            history = []
        s = core.settings
        push({
            "type": "ready",
            "history": history,
            "session": session.id,
            "conversation_id": session.conversation_id,
            "user": {**user.public(s), **({"token": user.token} if user.token else {})},
            "accounts": directory.enabled,
            "profile_max": s.AUTH_INSTRUCTIONS_MAX_CHARS,
            # Voix au choix du profil (Piper : voices/) ; vide si le fournisseur TTS n'en propose pas
            "voices": core.voices() if user.has_profile else [],
            # Outils permis à cet utilisateur (son rôle)
            "tools": [t.name for t in session.conversation.tools.all()],
            # Réglages utiles au client (détection de fin de phrase côté navigateur, délai de confirmation)
            "audio": {
                "sample_rate": s.AUDIO_RATE,
                "voice_threshold": s.VOICE_THRESHOLD / 32768.0,
                "silence_duration": s.SILENCE_DURATION,
                "max_speech_duration": s.MAX_SPEECH_DURATION,
            },
            "confirm_timeout": s.GATEWAY_CONFIRM_TIMEOUT,
            "llm": core.model_info(),
        })
        sender_task = asyncio.create_task(sender())
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                try:
                    message = json.loads(await ws.receive_text())
                except (json.JSONDecodeError, TypeError):
                    push({"type": "error", "message": "Message JSON invalide."})
                    continue
                kind = message.get("type")
                if pending:
                    if kind == "confirm_response":
                        req_id = message.get("id", "")
                        accepted = bool(message.get("accepted"))
                        print(f"📩 [GATEWAY {session.id}] Reçu confirm_response (id={req_id}, accepted={accepted})")
                        future = pending.get(req_id)
                        if future and not future.done():
                            future.set_result(accepted)
                        continue

                    if kind == "text":
                        user_text = (message.get("text") or "").strip()
                        decision = classify_confirmation(user_text, s.ACTIONS_CONFIRM_WORDS, s.ACTIONS_CANCEL_WORDS)
                        if decision is not None:
                            active_id = next(iter(pending.keys()))
                            future = pending[active_id]
                            if not future.done():
                                print(f"🗣️ [GATEWAY {session.id}] Confirmation résolue par texte (« {user_text} ») -> {'Acceptée' if decision else 'Refusée'}")
                                future.set_result(decision)
                                push({"type": "confirm_dismiss", "id": active_id, "accepted": decision})
                                push({"type": "done", "turn": message.get("turn")})
                                continue
                        else:
                            print(f"❓ [GATEWAY {session.id}] Texte non interprété comme confirmation (« {user_text} »)")
                            push({"type": "toast", "message": "Réponse non comprise. Dites « Oui » ou « Non »."})
                            push({"type": "done", "turn": message.get("turn")})
                            continue

                    if kind == "audio":
                        try:
                            audio_raw = base64.b64decode(message.get("data", ""))
                            transcribed = await asyncio.to_thread(core.transcribe_audio, audio_raw)
                            print(f"🎙️ [GATEWAY {session.id}] Audio transcrit pendant confirmation : « {transcribed} »")
                            push({"type": "transcript", "text": transcribed, "turn": message.get("turn")})
                            decision = classify_confirmation(transcribed, s.ACTIONS_CONFIRM_WORDS, s.ACTIONS_CANCEL_WORDS)
                            if decision is not None:
                                active_id = next(iter(pending.keys()))
                                future = pending[active_id]
                                if not future.done():
                                    print(f"🗣️ [GATEWAY {session.id}] Confirmation résolue à la voix (« {transcribed} ») -> {'Acceptée' if decision else 'Refusée'}")
                                    future.set_result(decision)
                                    push({"type": "confirm_dismiss", "id": active_id, "accepted": decision})
                                    push({"type": "done", "turn": message.get("turn")})
                                    continue
                            else:
                                print(f"❓ [GATEWAY {session.id}] Voix non interprétée comme confirmation (« {transcribed} »)")
                                push({"type": "toast", "message": f"Non compris (« {transcribed} »). Dites « Oui » ou « Non »."})
                                push({"type": "done", "turn": message.get("turn")})
                                continue
                        except Exception as e:
                            print(f"⚠️ [GATEWAY {session.id}] Erreur confirmation audio : {e}")
                            push({"type": "done", "turn": message.get("turn")})
                            continue
                if kind in ("text", "audio"):
                    txt_prev = f"texte='{message.get('text')}'" if kind == "text" else f"audio={len(message.get('data',''))}b"
                    print(f"📩 [GATEWAY {session.id}] Message entrant : {kind} ({txt_prev})")
                    task = asyncio.create_task(handle(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind == "confirm_response":
                    future = pending.get(message.get("id", ""))
                    if future and not future.done():
                        future.set_result(bool(message.get("accepted")))
                elif kind == "stop":
                    print(f"⏹️ [GATEWAY {session.id}] Interruption reçue (stop)")
                    # L'utilisateur coupe la parole : fin de la génération et des phrases encore à envoyer
                    core.cancel(session.id)
                    for speech in list(speeches):
                        speech.interrupt()
                elif kind in ("reset", "new_conversation"):
                    print(f"🔄 [GATEWAY {session.id}] Nouvelle conversation (reset)")
                    core.reset(session.id)
                    push({"type": "reset_done", "conversation_id": session.conversation_id})
                elif kind in ("list_conversations", "load_conversation", "delete_conversation"):
                    task = asyncio.create_task(handle_conversations(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind in ("forget", "edit_answer"):
                    task = asyncio.create_task(handle_history(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind in ("update_profile", "preview_voice"):
                    task = asyncio.create_task(
                        handle_profile(message) if kind == "update_profile" else handle_voice_preview(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind in ("get_settings", "update_settings", "list_models"):
                    task = asyncio.create_task(handle_settings(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind == "restart" and not admin:
                    push({"type": "settings_error", "message": ADMIN_ONLY_MESSAGE})
                elif kind == "restart":
                    core.events.emit("restarting", None)
                    # Laisse partir l'annonce aux clients avant l'arrêt
                    asyncio.get_running_loop().call_later(RESTART_DELAY_SECONDS, restart.request_restart)
                elif kind == "ping":
                    push({"type": "pong"})
                elif kind == "auth":
                    pass  # déjà authentifié (en-tête, ou passerelle sans jeton en loopback)
                else:
                    push({"type": "error", "message": f"Type de message inconnu : {kind}"})
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()
            unsubscribe_settings()
            core.detach_confirmation(session.id)
            for future in list(pending.values()):
                if not future.done():
                    future.set_result(False)
            sender_task.cancel()
            print(f"🔌 [GATEWAY {session.id}] Client déconnecté")

    app = Starlette(routes=[
        Route("/health", health),
        Route("/api/ask", ask, methods=["POST"]),
        WebSocketRoute("/ws", websocket_endpoint),
        Mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web"),
    ])
    # Les WebSockets sont authentifiés par leur handler (les navigateurs ne peuvent pas envoyer d'en-tête)
    secured = BearerTokenMiddleware(app, token, protected_prefixes=("/api/",)) if token else LocalOnlyMiddleware(app)
    return SecurityHeadersMiddleware(secured)


def build_server(core: AssistantCore, settings: Optional[Settings] = None):
    """Prépare le serveur uvicorn de la passerelle (sans le démarrer)."""
    import uvicorn
    s = settings or core.settings
    config = uvicorn.Config(
        create_app(core, s),
        host=s.GATEWAY_HOST,
        port=s.GATEWAY_PORT,
        ws_max_size=s.GATEWAY_MAX_MESSAGE_BYTES,
        log_level="warning",
    )
    return uvicorn.Server(config)


def start_in_thread(core: AssistantCore, settings: Optional[Settings] = None):
    """Démarre la passerelle en arrière-plan (ex: à côté de l'écoute micro de main.py). Arrêt : server.should_exit = True."""
    server = build_server(core, settings)
    thread = threading.Thread(target=server.run, name="smarthome-gateway", daemon=True)
    thread.start()
    return server, thread
