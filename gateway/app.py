"""
Passerelle réseau de SmartHome : permet de piloter l'assistant depuis un autre appareil (LAN, Tailscale).

Routes :
- GET  /health   : état (sans authentification)
- POST /api/ask  : {"text" | "audio" (WAV base64), "session"?, "speak"?} -> réponse JSON (sans confirmation possible :
                   les actions dangereuses sont refusées)
- WS   /ws       : session interactive (streaming, outils, confirmations). Protocole JSON :
    client -> serveur : {"type": "auth", "token", "session"?}  (premier message si pas d'en-tête Authorization)
                        {"type": "text", "text", "speak"?} | {"type": "audio", "data": <WAV base64>, "speak"?}
                        {"type": "confirm_response", "id", "accepted": bool} | {"type": "stop"} | {"type": "reset"}
                        | {"type": "ping"}
                        Paramètres (voir core/settings_store.py) : {"type": "get_settings"} | {"type": "list_models"}
                        | {"type": "update_settings", "values": {VARIABLE: valeur}}
    serveur -> client : {"type": "ready", "session", "tools", "audio", "confirm_timeout", "llm"} puis les événements du cœur
                        (transcript, token, tool, confirm_request, response, interrupted, error), la voix si speak :
                        {"type": "audio_chunk", "seq", "format": "wav", "data"} phrase par phrase (TTS_STREAMING)
                        ou {"type": "audio", ...} en un bloc, et {"type": "done"} à la fin de chaque demande.
                        Paramètres : {"type": "settings", "groups", "llm"} | {"type": "models", "models", "error"?}
                        | {"type": "settings_saved", "changed", "restart", "overridden", "llm"} | {"type": "settings_error", "message"}
                        ; "settings_changed" est diffusé à tous les clients après une modification.
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
from core.assistant import AssistantCore, Reply, to_wav_bytes
from core import settings_store
from core.config import Settings
from core.security import (
    BearerTokenMiddleware, LocalOnlyMiddleware, SecurityHeadersMiddleware, bearer_from_headers, token_matches,
)

# Interface web (PWA) servie à la racine : publique, elle ne contient aucun secret (le jeton est saisi par l'utilisateur)
WEB_DIR = Path(__file__).resolve().parent / "web"

# Code de fermeture WebSocket pour un jeton refusé (plage 4000-4999 réservée aux applications)
WS_UNAUTHORIZED = 4401
AUTH_TIMEOUT_SECONDS = 10


def _reply_to_dict(reply: Reply) -> dict:
    data = {"session": reply.session_id, "transcript": reply.transcript, "text": reply.text, "tools": reply.tools}
    if reply.audio_wav:
        data["audio"] = {"format": "wav", "data": base64.b64encode(reply.audio_wav).decode()}
    return data


def create_app(core: AssistantCore, settings: Optional[Settings] = None):
    # Le jeton et l'adresse sont fixés au démarrage ; le reste est relu dans core.settings (modifiable à chaud)
    token = (settings or core.settings).GATEWAY_AUTH_TOKEN

    async def health(request: Request):
        return JSONResponse({"status": "ok", "service": "smarthome-gateway"})

    async def ask(request: Request):
        try:
            body = await request.json()
            audio = base64.b64decode(body["audio"]) if body.get("audio") else None
        except Exception:
            return JSONResponse({"error": "Corps JSON invalide."}, status_code=400)
        if not body.get("text") and audio is None:
            return JSONResponse({"error": "Champ 'text' ou 'audio' requis."}, status_code=400)
        session = core.open_session(body.get("session"))
        reply = await asyncio.to_thread(
            core.respond, session.id, text=body.get("text"), audio_wav=audio, synthesize=bool(body.get("speak"))
        )
        return JSONResponse(_reply_to_dict(reply))

    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        loop = asyncio.get_running_loop()

        # 1. Authentification : en-tête Authorization, sinon premier message {"type": "auth"} (navigateurs)
        hello: dict = {}
        authorized = not token or token_matches(bearer_from_headers(ws.scope.get("headers", [])), token)
        if not authorized:
            try:
                hello = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS))
            except Exception:
                hello = {}
            if hello.get("type") != "auth" or not token_matches(str(hello.get("token", "")), token):
                await ws.send_json({"type": "error", "message": "Jeton manquant ou invalide."})
                await ws.close(code=WS_UNAUTHORIZED)
                return

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
            core.events.emit("confirm_request", session.id, id=request_id, question=question)
            try:
                return bool(future.result(timeout=s.GATEWAY_CONFIRM_TIMEOUT))
            except concurrent.futures.TimeoutError:
                return False
            finally:
                pending.pop(request_id, None)

        session_id = hello.get("session") or ws.query_params.get("session")
        session = core.open_session(session_id, confirm=confirm)
        unsubscribe = core.events.subscribe(lambda e: push(e.to_dict()), session_id=session.id)
        # Modifications de paramètres faites depuis un autre appareil : chaque client recharge son formulaire
        unsubscribe_settings = core.events.subscribe(
            lambda e: push(e.to_dict()) if e.type == "settings_changed" else None
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
            return SpeechPipeline(core.tts, sink=send_chunk)

        def run_request(text, audio, speak) -> Reply:
            speech = streamed_speech() if speak and core.settings.TTS_STREAMING else None
            if speech:
                speeches.add(speech)
            try:
                reply = core.respond(session.id, text=text, audio_wav=audio, synthesize=speak and not speech,
                                     on_sentence=speech.say if speech else None)
                if speech:
                    speech.wait()
                return reply
            finally:
                if speech:
                    speeches.discard(speech)
                    speech.close()

        async def handle(message: dict):
            try:
                audio = base64.b64decode(message["data"]) if message["type"] == "audio" else None
                reply = await asyncio.to_thread(run_request, message.get("text"), audio, bool(message.get("speak")))
                if reply.audio_wav:
                    push({"type": "audio", "format": "wav", "data": base64.b64encode(reply.audio_wav).decode()})
            except Exception as e:
                push({"type": "error", "message": str(e)})
            finally:
                push({"type": "done"})

        async def handle_settings(message: dict):
            """Lecture / modification des paramètres et liste des modèles (appels bloquants hors de la boucle)."""
            kind = message["type"]
            try:
                if kind == "list_models":
                    try:
                        models = await asyncio.to_thread(core.llm.list_models)
                        push({"type": "models", "provider": core.settings.LLM_PROVIDER, "models": models})
                    except Exception as e:
                        push({"type": "models", "provider": core.settings.LLM_PROVIDER, "models": [],
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

        s = core.settings
        push({
            "type": "ready",
            "session": session.id,
            "tools": [t.name for t in core.tools.all()],
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
                if kind in ("text", "audio"):
                    task = asyncio.create_task(handle(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif kind == "confirm_response":
                    future = pending.get(message.get("id", ""))
                    if future and not future.done():
                        future.set_result(bool(message.get("accepted")))
                elif kind == "stop":
                    # L'utilisateur coupe la parole : fin de la génération et des phrases encore à envoyer
                    core.cancel(session.id)
                    for speech in list(speeches):
                        speech.interrupt()
                elif kind == "reset":
                    session.conversation.clear()
                    push({"type": "reset_done"})
                elif kind in ("get_settings", "update_settings", "list_models"):
                    task = asyncio.create_task(handle_settings(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
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
