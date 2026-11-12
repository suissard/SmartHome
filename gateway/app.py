"""
Passerelle réseau de SmartHome : permet de piloter l'assistant depuis un autre appareil (LAN, Tailscale).

Routes :
- GET  /health   : état (sans authentification)
- POST /api/ask  : {"text" | "audio" (WAV base64), "images"?, "session"?, "speak"?} -> réponse JSON (sans confirmation
                   possible : les actions dangereuses sont refusées)
- WS   /ws       : session interactive (streaming, outils, confirmations). Protocole JSON :
    client -> serveur : {"type": "auth", "token"?, "session"?}  (premier message si pas d'en-tête Authorization)
                        Comptes (AUTH_PROVIDER, voir core/users.py) : {"type": "auth", "identity", "password", "session"?}
                        ou {"type": "auth", "user_token", "session"?} ; le jeton maître ("token") donne l'accès administrateur
                        {"type": "text", "text", "speak"?} | {"type": "audio", "data": <WAV base64>, "speak"?}
                        (avec "turn"? : identifiant de l'échange, repris dans ses événements et "done" ; "forget"? : échanges
                        à retirer d'abord de l'historique, pour relancer à partir d'un message ; "images"? :
                        [{"data": base64 | data URL, "name"?}] jointes au message, voir core/images.py)
                        {"type": "forget", "turns", "role"?} | {"type": "edit_answer", "turn", "text", "forget"?}
                        {"type": "confirm_response", "id", "accepted": bool} | {"type": "stop"} | {"type": "reset"}
                        | {"type": "set_agent", "agent": nom | null} (relie la conversation à un agent externe, voir
                        core/agents.py ; null : retour à l'assistant) -> {"type": "agent_changed", "agent": {...} | null}
                        | {"type": "feedback", "conversation_id", "turn", "rating": -2..2, "comment"?}
                          -> {"type": "feedback_saved", "conversation_id", "turn", "rating", "comment"} | {"type": "feedback_error", "message"}
                        | {"type": "list_memories"} | {"type": "add_memory", "text"} | {"type": "delete_memory", "id"}
                          (souvenirs du compte, core/memory.py) -> {"type": "memories", "memories": [{id, text, updated_at}]}
                          | {"type": "memory_error", "message"} ; {"type": "reminder", "id", "kind", "text", ...} à
                          l'échéance d'un rappel du compte (core/scheduler.py) ; {"type": "timings", "timings"} après
                          chaque réponse (latence par étape, core/metrics.py)
                        | {"type": "load_conversation", "conversation_id", "source": "local"} (conversation du micro, lecture
                          seule, ARCHIVE_HOUSEHOLD_ROLES) ; {"type": "history_updated", "conversation_id", "source"} à chaque échange au micro
                        | {"type": "ping"} | {"type": "listening", "active": bool} (micro du client ouvert / fermé :
                        le micro de l'ordinateur ignore alors le mot-clé et repasse en veille, voir core/remote_voice.py)
                        Profil du compte connecté : {"type": "update_profile", "name", "instructions", "voice"?, "assistant_name"?}
                        | {"type": "preview_voice", "voice"} (phrase d'essai renvoyée en {"type": "voice_preview", "data"})
                        Paramètres (voir core/settings_store.py) : {"type": "get_settings"} | {"type": "list_models", "provider"?: nom}
                        | {"type": "update_settings", "values": {VARIABLE: valeur}} | {"type": "restart"}
    serveur -> client : {"type": "ready", "session", "user", "tools", "audio", "confirm_timeout", "llm"} puis les événements du cœur
                        ("user" : {"id", "name", "role", "admin", "token"?} ; "token" = jeton du compte à réutiliser,
                        refus : {"type": "error", "message", "accounts"} puis fermeture 4401)
                        (transcript, token, tool, confirm_request, response, interrupted, error, warning ;
                        image : {"name", "mime", "data", "path"} montrée par l'assistant, outil show_image), la voix si speak :
                        {"type": "audio_chunk", "seq", "format": "wav", "data"} phrase par phrase (TTS_STREAMING)
                        ou {"type": "audio", ...} en un bloc, et {"type": "done"} à la fin de chaque demande.
                        Paramètres : {"type": "settings", "groups", "llm"} | {"type": "models", "models", "error"?}
                        | {"type": "settings_saved", "changed", "restart", "overridden", "llm"} | {"type": "settings_error", "message"}
                        | {"type": "profile_saved", "user"} | {"type": "profile_error", "message"}
                        ; "ready.history" : [{role, content, turn?}] (conversation en cours, rechargée depuis
                        l'historique du compte si la session est neuve)
                        ; "ready.agents" / "ready.agent" : agents externes permis et agent relié (les réponses d'un agent
                        portent "agent" dans l'événement "response")
                        ; "ready", "profile_saved" et "settings_changed" portent "assistant" ({"name", "default_name"} :
                        nom affiché sur les bulles) et "wakeword" ({"enabled", "available"} : écoute du mot-clé
                        par le micro de l'ordinateur, coupée avec update_settings {"WAKEWORD_ENABLED": false})
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
from audio.confirm import classify_confirmation, format_confirm_prompt
from core.assistant import AssistantCore, Reply, to_wav_bytes
from core import restart, settings_store
from core.config import Settings
from core.images import ImageError, decode_uploads
from core.security import (
    BearerTokenMiddleware, LocalOnlyMiddleware, SecurityHeadersMiddleware, bearer_from_headers, token_matches,
)
from core.users import (AuthError, DirectoryUnavailable, User, admin_user, assistant_name, create_directory,
                        is_admin, LOCAL_USER_ID)
from core.version import check_version, local_version_info, pull_update

# Interface web (PWA) servie à la racine : publique, elle ne contient aucun secret (le jeton est saisi par l'utilisateur)
WEB_DIR = Path(__file__).resolve().parent / "web"

# Code de fermeture WebSocket pour un jeton refusé (plage 4000-4999 réservée aux applications)
WS_UNAUTHORIZED = 4401
AUTH_TIMEOUT_SECONDS = 10
RESTART_DELAY_SECONDS = 0.3
ADMIN_ONLY_MESSAGE = "Réservé aux administrateurs."


def _reply_to_dict(reply: Reply) -> dict:
    data = {"session": reply.session_id, "transcript": reply.transcript, "text": reply.text, "tools": reply.tools,
            "images": reply.images}
    if reply.audio_wav:
        data["audio"] = {"format": "wav", "data": base64.b64encode(reply.audio_wav).decode()}
    return data


class _WSClient:
    """Session WebSocket d'un client connecté à la passerelle : envoi asynchrone, confirmation et dispatch."""

    def __init__(self, ws: WebSocket, core: AssistantCore, directory, user: User, session_id: Optional[str],
                 loop: asyncio.AbstractEventLoop):
        self.ws = ws
        self.core = core
        self.directory = directory
        self.user = user
        self.loop = loop
        self.admin = is_admin(user, core.settings)
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.pending: dict[str, concurrent.futures.Future] = {}
        self._confirm_speak_tls = threading.local()
        self.speeches: set[SpeechPipeline] = set()
        self.tasks: set[asyncio.Task] = set()
        self.mic_open = False
        self.session = core.open_session(session_id, confirm=self.confirm, user=user, attach=True)

        client_ip = getattr(ws.client, "host", ws.client[0] if isinstance(ws.client, (tuple, list)) else "inconnu") if ws.client else "inconnu"
        print(f"🔌 [GATEWAY {self.session.id}] {user.name} (rôle {user.role}) connecté depuis {client_ip}")
        self._unsub_session = core.events.subscribe(lambda e: self.push(e.to_dict()), session_id=self.session.id)
        self._unsub_global = core.events.subscribe(self._on_global)

        self._async_handlers = {
            "text": self.handle_chat,
            "audio": self.handle_chat,
            "forget": self.handle_history,
            "edit_answer": self.handle_history,
            "list_conversations": self.handle_conversations,
            "load_conversation": self.handle_conversations,
            "delete_conversation": self.handle_conversations,
            "list_memories": self.handle_memories,
            "add_memory": self.handle_memories,
            "delete_memory": self.handle_memories,
            "feedback": self.handle_feedback,
            "update_profile": self.handle_profile,
            "preview_voice": self.handle_voice_preview,
            "get_settings": self.handle_settings,
            "update_settings": self.handle_settings,
            "list_models": self.handle_settings,
            "pb_list_users": self.handle_pb_admin,
            "pb_create_user": self.handle_pb_admin,
            "pb_update_user": self.handle_pb_admin,
            "pb_delete_user": self.handle_pb_admin,
            "check_update": self.handle_version,
            "apply_update": self.handle_version,
        }

    def push(self, message: dict):
        # Appelé depuis les threads du pipeline : on repasse par la boucle asyncio
        self.loop.call_soon_threadsafe(self.outbox.put_nowait, message)

    def public_state(self) -> dict:
        s = self.core.settings
        return {
            "assistant": {"name": assistant_name(self.user, s), "default_name": s.ASSISTANT_NAME},
            "wakeword": {"enabled": s.WAKEWORD_ENABLED, "available": self.core.local_microphone},
        }

    def _reminder_visible(self, data: dict) -> bool:
        creator = data.get("user_id") or LOCAL_USER_ID
        return creator == self.user.id or (creator == LOCAL_USER_ID and self.core.sees_household(self.user))

    def _on_global(self, e):
        if e.type in ("settings_changed", "restarting"):
            self.push({**e.to_dict(), **(self.public_state() if e.type == "settings_changed" else {})})
        elif e.type == "history_updated" and e.session_id != self.session.id and self.core.sees_household(self.user):
            # Échange au micro de l'ordinateur : la liste des conversations (et la conversation affichée) suit
            self.push(e.to_dict())
        elif e.type == "reminder" and self._reminder_visible(e.data):
            # Rappel ou routine à échéance : au compte qui l'a créé (ceux du foyer : à qui voit le foyer)
            self.push(e.to_dict())

    def confirm(self, description: str) -> bool:
        request_id = uuid.uuid4().hex[:8]
        future: concurrent.futures.Future = concurrent.futures.Future()
        self.pending[request_id] = future
        s = self.core.settings
        question = format_confirm_prompt(s.ACTIONS_CONFIRM_PROMPT, description)
        speak_confirm = getattr(self._confirm_speak_tls, "speak", False)
        print(f"❓ [GATEWAY {self.session.id}] Demande de confirmation envoyée (id={request_id}) : « {question} »")
        if speak_confirm and self.core.tts and not getattr(self.core.tts, "passthrough", False):
            try:
                res = self.core.tts.synthesize(question, voice=self.core.session_voice(self.session.id))
                if res:
                    samples, sr = res
                    if len(samples) > 0:
                        wav_data = to_wav_bytes(samples, sr)
                        self.push({"type": "audio_chunk", "seq": 0, "format": "wav",
                                   "data": base64.b64encode(wav_data).decode("ascii")})
            except Exception as e:
                print(f"⚠️ [GATEWAY {self.session.id}] Erreur synthèse TTS confirmation : {e}")
        self.core.events.emit("confirm_request", self.session.id, id=request_id, question=question)
        try:
            res = bool(future.result(timeout=s.GATEWAY_CONFIRM_TIMEOUT))
            print(f"{'✅' if res else '⛔'} [GATEWAY {self.session.id}] Confirmation {request_id} : "
                  f"{'Acceptée' if res else 'Refusée'}")
            return res
        except concurrent.futures.TimeoutError:
            print(f"⏰ [GATEWAY {self.session.id}] Délai expiré ({s.GATEWAY_CONFIRM_TIMEOUT}s) pour confirmation {request_id}")
            return False
        finally:
            self.pending.pop(request_id, None)

    def _streamed_speech(self) -> SpeechPipeline:
        """Voix envoyée phrase par phrase au client, synthétisée pendant que le LLM génère la suite."""
        seq = iter(range(1_000_000))

        def send_chunk(samples, sample_rate):
            self.push({"type": "audio_chunk", "seq": next(seq), "format": "wav",
                       "data": base64.b64encode(to_wav_bytes(samples, sample_rate)).decode()})

        # Voix résolue à chaque phrase : un agent externe relié en cours de réponse parle avec sa propre voix
        return SpeechPipeline(self.core.tts, sink=send_chunk, voice=lambda: self.core.session_voice(self.session.id))

    def _run_request(self, text, audio, speak: bool, turn, forget, images=()) -> Reply:
        self._confirm_speak_tls.speak = bool(speak)
        speech = self._streamed_speech() if speak and self.core.settings.TTS_STREAMING else None
        if speech:
            self.speeches.add(speech)
        try:
            reply = self.core.respond(
                self.session.id, text=text, audio_wav=audio, synthesize=speak and not speech,
                on_sentence=speech.say if speech else None, turn=turn, forget=forget,
                images=images, user=self.user,
            )
            if speech:
                speech.wait()
            return reply
        finally:
            self._confirm_speak_tls.speak = False
            if speech:
                self.speeches.discard(speech)
                speech.close()

    async def handle_chat(self, message: dict):
        turn = message.get("turn")
        tag = {"turn": turn} if turn else {}
        try:
            audio = base64.b64decode(message["data"]) if message["type"] == "audio" else None
            images = decode_uploads(message.get("images"), self.core.settings)
            reply = await asyncio.to_thread(
                self._run_request, message.get("text"), audio, bool(message.get("speak")),
                turn, message.get("forget") or (), images,
            )
            if reply.audio_wav:
                self.push({"type": "audio", "format": "wav", "data": base64.b64encode(reply.audio_wav).decode()})
        except Exception as e:
            self.push({"type": "error", "message": str(e), **tag})
        finally:
            self.push({"type": "done", **tag})

    async def handle_history(self, message: dict):
        """Suppression d'un message ou correction d'une réponse (bloquant tant qu'une réponse est en cours)."""
        try:
            if message["type"] == "forget":
                await asyncio.to_thread(self.core.forget, self.session.id, message.get("turns") or (), message.get("role"))
            else:
                await asyncio.to_thread(self.core.edit_answer, self.session.id, message["turn"], str(message["text"]),
                                        message.get("forget") or ())
        except Exception as e:
            self.push({"type": "error", "message": f"Historique non modifié : {e}"})

    async def handle_conversations(self, message: dict):
        """Gestion des différentes conversations (liste, chargement, suppression)."""
        kind = message["type"]
        try:
            if kind == "list_conversations":
                convs = await asyncio.to_thread(self.core.list_conversations, self.session.id)
                self.push({"type": "conversations_list", "conversations": convs})
            elif kind == "load_conversation" and message.get("source") == "local":
                # Conversation tenue au micro de l'ordinateur : affichée en lecture seule, la session n'en change pas
                cid = str(message.get("conversation_id", "")).strip()
                msgs = await asyncio.to_thread(self.core.household_conversation, self.session.id, cid)
                self.push({"type": "conversation_loaded", "conversation_id": cid, "history": msgs,
                           "source": "local", "readonly": True})
            elif kind == "load_conversation":
                cid = str(message.get("conversation_id", "")).strip()
                client_msgs = message.get("messages")
                msgs = await asyncio.to_thread(self.core.load_conversation, self.session.id, cid, client_msgs)
                self.push({"type": "conversation_loaded", "conversation_id": cid, "history": msgs})
            elif kind == "delete_conversation":
                cid = str(message.get("conversation_id", "")).strip()
                ok = await asyncio.to_thread(self.core.delete_conversation, self.session.id, cid)
                self.push({"type": "conversation_deleted", "conversation_id": cid, "success": ok})
        except Exception as e:
            self.push({"type": "error", "message": f"Erreur conversation : {e}"})

    async def handle_memories(self, message: dict):
        """Souvenirs du compte : liste, ajout à la main, effacement."""
        kind = message["type"]
        try:
            if kind == "add_memory":
                await asyncio.to_thread(self.core.add_memory, self.session.id, str(message.get("text") or ""))
            elif kind == "delete_memory":
                if not await asyncio.to_thread(self.core.delete_memory, self.session.id, message.get("id")):
                    raise ValueError("Souvenir introuvable.")
            memories = await asyncio.to_thread(self.core.list_memories, self.session.id)
            self.push({"type": "memories", "memories": memories})
        except ValueError as e:
            self.push({"type": "memory_error", "message": str(e)})

    async def handle_feedback(self, message: dict):
        """Note d'une réponse (-2 à +2) et commentaire facultatif, enregistrés dans l'archive."""
        try:
            saved = await asyncio.to_thread(
                self.core.set_feedback, self.session.id, str(message.get("conversation_id") or ""),
                str(message.get("turn") or ""), message.get("rating"), str(message.get("comment") or ""))
            self.push({"type": "feedback_saved", **saved})
        except (ValueError, PermissionError) as e:
            self.push({"type": "feedback_error", "message": str(e), "turn": message.get("turn")})
        except Exception as e:
            self.push({"type": "feedback_error", "message": f"Note non enregistrée : {e}", "turn": message.get("turn")})

    async def handle_profile(self, message: dict):
        """Prénom et consignes du compte, enregistrés dans l'annuaire avec le jeton du compte lui-même."""
        if not self.directory.enabled or not self.user.has_profile:
            self.push({"type": "profile_error", "message": "Profil disponible seulement avec un compte utilisateur."})
            return
        voice = str(message.get("voice", self.user.voice) or "")
        voices = await asyncio.to_thread(self.core.voices) if voice else []
        if voice and voice not in {v["id"] for v in voices}:
            self.push({"type": "profile_error", "message": f"Voix « {voice} » non installée sur cette machine."})
            return
        try:
            # Nom de l'assistant : seulement s'il est envoyé (sinon inchangé)
            extra = {"assistant_name": str(message.get("assistant_name") or "")} \
                if "assistant_name" in message else {}
            updated = await asyncio.to_thread(
                self.directory.update_profile, self.user, message.get("name", ""),
                message.get("instructions", ""), voice, **extra,
            )
            self.core.set_session_user(self.session.id, updated)
            self.user = updated
            print(f"👤 [GATEWAY {self.session.id}] Profil de {self.user.name} mis à jour")
            self.push({"type": "profile_saved", "user": self.user.public(self.core.settings), **self.public_state()})
        except (ValueError, AuthError, DirectoryUnavailable) as e:
            self.push({"type": "profile_error", "message": str(e)})
        except Exception as e:
            print(f"⚠️ [GATEWAY {self.session.id}] Profil non enregistré : {e!r}")
            self.push({"type": "profile_error", "message": f"Profil non enregistré : {e}"})

    async def handle_voice_preview(self, message: dict):
        """Phrase d'essai dans une voix installée, pour la choisir (jouée même si la réponse vocale est coupée)."""
        voice = str(message.get("voice") or "")
        voices = await asyncio.to_thread(self.core.voices) if voice else []
        if voice and voice not in {v["id"] for v in voices}:
            self.push({"type": "profile_error", "message": f"Voix « {voice} » non installée sur cette machine."})
            return
        try:
            samples, rate = await asyncio.to_thread(
                self.core.tts.synthesize, self.core.settings.TTS_VOICE_PREVIEW_TEXT, voice or None,
            )
            if len(samples):
                self.push({"type": "voice_preview", "voice": voice, "format": "wav",
                           "data": base64.b64encode(to_wav_bytes(samples, rate)).decode()})
        except Exception as e:
            self.push({"type": "profile_error", "message": f"Écoute impossible : {e}"})

    async def handle_settings(self, message: dict):
        """Lecture / modification des paramètres et liste des modèles (appels bloquants hors de la boucle)."""
        kind = message["type"]
        if not self.admin:
            self.push({"type": "settings_error", "message": ADMIN_ONLY_MESSAGE})
            return
        try:
            if kind == "list_models":
                name = str(message.get("provider") or self.core.settings.LLM_PROVIDER)
                try:
                    if name == self.core.settings.LLM_PROVIDER:
                        provider = self.core.llm
                    else:
                        from llm.providers import LLM_PROVIDERS
                        provider = LLM_PROVIDERS.create(name, self.core.settings)
                    models = await asyncio.to_thread(provider.list_models)
                    self.push({"type": "models", "provider": name, "models": models})
                except Exception as e:
                    self.push({"type": "models", "provider": name, "models": [],
                               "error": f"Liste des modèles indisponible : {e}"})
                return
            if kind == "update_settings":
                values = message.get("values")
                if not isinstance(values, dict):
                    raise ValueError("Champ 'values' attendu : {VARIABLE: valeur}.")
                result = await asyncio.to_thread(self.core.update_settings, values)
                self.push({"type": "settings_saved", **result, "llm": self.core.model_info()})
                if result["changed"]:
                    self.core.events.emit("settings_changed", None, changed=result["changed"])
            self.push({"type": "settings", "groups": settings_store.describe(self.core.settings), "llm": self.core.model_info()})
        except ValueError as e:
            self.push({"type": "settings_error", "message": str(e)})
        except Exception as e:
            self.push({"type": "settings_error", "message": f"Erreur : {e}"})

    async def handle_pb_admin(self, message: dict):
        """Gestion des comptes utilisateurs PocketBase (réservée aux superadmins référencés sur PocketBase)."""
        kind = message["type"]
        if not self.directory.enabled or not getattr(self.user, "superadmin", False):
            self.push({"type": "pb_admin_error", "message": "Réservé aux superadministrateurs PocketBase."})
            return
        try:
            if kind == "pb_list_users":
                users_list = await asyncio.to_thread(self.directory.list_users, self.user)
                self.push({"type": "pb_users", "users": users_list, "pocketbase_url": self.core.settings.POCKETBASE_URL})
            elif kind == "pb_create_user":
                created = await asyncio.to_thread(
                    self.directory.create_user,
                    self.user,
                    message.get("email", ""),
                    message.get("password", ""),
                    message.get("name", ""),
                    message.get("role", "member"),
                )
                users_list = await asyncio.to_thread(self.directory.list_users, self.user)
                self.push({"type": "pb_user_saved", "user": created, "users": users_list})
            elif kind == "pb_update_user":
                updated_u = await asyncio.to_thread(
                    self.directory.update_user_role,
                    self.user,
                    message.get("id", ""),
                    message.get("role", ""),
                    message.get("name"),
                )
                users_list = await asyncio.to_thread(self.directory.list_users, self.user)
                self.push({"type": "pb_user_saved", "user": updated_u, "users": users_list})
            elif kind == "pb_delete_user":
                del_id = str(message.get("id", ""))
                await asyncio.to_thread(self.directory.delete_user, self.user, del_id)
                users_list = await asyncio.to_thread(self.directory.list_users, self.user)
                self.push({"type": "pb_user_deleted", "id": del_id, "users": users_list})
        except (ValueError, AuthError, DirectoryUnavailable) as e:
            self.push({"type": "pb_admin_error", "message": str(e)})
        except Exception as e:
            self.push({"type": "pb_admin_error", "message": f"Erreur PocketBase : {e}"})

    async def handle_version(self, message: dict):
        """Vérifie la version sur GitHub ou tire les dernières modifications Git (admins)."""
        kind = message["type"]
        if kind == "check_update":
            info = await asyncio.to_thread(check_version, bool(message.get("force")))
            self.push({"type": "version_info", **info})
        elif kind == "apply_update":
            if not self.admin:
                self.push({"type": "update_applied", "ok": False, "output": ADMIN_ONLY_MESSAGE})
                return
            res = await asyncio.to_thread(pull_update)
            self.push({"type": "update_applied", **res})

    async def answer_confirmation(self, message: dict, kind: str) -> bool:
        """« Oui » / « non » écrit ou dit pendant une confirmation. False : plus de question en attente."""
        turn = message.get("turn")
        active_id, future = next(iter(self.pending.items()), (None, None))
        if future is None or future.done():
            return False
        answer = (message.get("text") or "").strip()
        if kind == "audio":
            try:
                answer = await asyncio.to_thread(self.core.transcribe_audio, base64.b64decode(message.get("data", "")))
            except Exception as e:
                print(f"⚠️ [GATEWAY {self.session.id}] Erreur confirmation audio : {e}")
                self.push({"type": "done", "turn": turn})
                return True
            print(f"🎙️ [GATEWAY {self.session.id}] Audio transcrit pendant confirmation : « {answer} »")
            self.push({"type": "transcript", "text": answer, "turn": turn})
        s = self.core.settings
        decision = classify_confirmation(answer, s.ACTIONS_CONFIRM_WORDS, s.ACTIONS_CANCEL_WORDS)
        source = "à la voix" if kind == "audio" else "par texte"
        if decision is None:
            print(f"❓ [GATEWAY {self.session.id}] Réponse non interprétée comme confirmation {source} (« {answer} »)")
            self.push({"type": "toast", "message": f"Non compris (« {answer} »). Dites « Oui » ou « Non »."})
        elif not future.done():
            print(f"🗣️ [GATEWAY {self.session.id}] Confirmation résolue {source} (« {answer} ») -> "
                  f"{'Acceptée' if decision else 'Refusée'}")
            future.set_result(decision)
            self.push({"type": "confirm_dismiss", "id": active_id, "accepted": decision})
        self.push({"type": "done", "turn": turn})
        return True

    async def send_ready(self):
        try:
            history = await asyncio.to_thread(self.core.restore_history, self.session.id)
        except Exception as e:
            print(f"⚠️ [GATEWAY {self.session.id}] Historique non rechargé : {e}")
            history = []
        s = self.core.settings
        self.push({
            "type": "ready",
            "history": history,
            "session": self.session.id,
            "conversation_id": self.session.conversation_id,
            "user": {**self.user.public(s), **({"token": self.user.token} if self.user.token else {})},
            "accounts": self.directory.enabled,
            "pocketbase_url": s.POCKETBASE_URL if self.directory.enabled else "",
            "version": local_version_info(),
            "profile_max": s.AUTH_INSTRUCTIONS_MAX_CHARS,
            "voices": await asyncio.to_thread(self.core.voices) if self.user.has_profile else [],
            "tools": [t.name for t in self.session.conversation.tools.all()],
            "audio": {
                "sample_rate": s.AUDIO_RATE,
                "voice_threshold": s.VOICE_THRESHOLD / 32768.0,
                "silence_duration": s.SILENCE_DURATION,
                "max_speech_duration": s.MAX_SPEECH_DURATION,
            },
            "confirm_timeout": s.GATEWAY_CONFIRM_TIMEOUT,
            "images": {"enabled": s.IMAGES_ENABLED, "max_bytes": s.IMAGES_MAX_BYTES,
                       "max_per_message": s.IMAGES_MAX_PER_MESSAGE, "max_side": s.IMAGES_MAX_SIDE},
            "llm": self.core.model_info(),
            "agents": self.core.available_agents(self.session.id),
            "agent": self.core.agent_info(self.session.id),
            "feedback": {"enabled": self.core.feedback_available(), "comment_max": s.FEEDBACK_COMMENT_MAX_CHARS},
            "memory": {"enabled": self.core.memory.enabled, "max_chars": s.MEMORY_MAX_CHARS},
            "household": self.core.sees_household(self.user),
            **self.public_state(),
        })

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def dispatch(self, message: dict):
        kind = message.get("type")
        if self.pending:
            if kind == "confirm_response":
                req_id = message.get("id", "")
                accepted = bool(message.get("accepted"))
                print(f"📩 [GATEWAY {self.session.id}] Reçu confirm_response (id={req_id}, accepted={accepted})")
                future = self.pending.get(req_id)
                if future and not future.done():
                    future.set_result(accepted)
                return
            if kind in ("text", "audio") and await self.answer_confirmation(message, kind):
                return

        if kind in ("text", "audio"):
            txt_prev = f"texte='{message.get('text')}'" if kind == "text" else f"audio={len(message.get('data', ''))}b"
            if message.get("images"):
                txt_prev += f", {len(message['images'])} image(s)"
            print(f"📩 [GATEWAY {self.session.id}] Message entrant : {kind} ({txt_prev})")
            self._spawn(self.handle_chat(message))
        elif kind in self._async_handlers:
            self._spawn(self._async_handlers[kind](message))
        elif kind == "confirm_response":
            future = self.pending.get(message.get("id", ""))
            if future and not future.done():
                future.set_result(bool(message.get("accepted")))
        elif kind == "stop":
            print(f"⏹️ [GATEWAY {self.session.id}] Interruption reçue (stop)")
            self.core.cancel(self.session.id)
            for speech in list(self.speeches):
                speech.interrupt()
        elif kind in ("reset", "new_conversation"):
            print(f"🔄 [GATEWAY {self.session.id}] Nouvelle conversation (reset)")
            self.core.reset(self.session.id)
            self.push({"type": "reset_done", "conversation_id": self.session.conversation_id})
        elif kind == "restart" and not self.admin:
            self.push({"type": "settings_error", "message": ADMIN_ONLY_MESSAGE})
        elif kind == "restart":
            self.core.events.emit("restarting", None)
            asyncio.get_running_loop().call_later(RESTART_DELAY_SECONDS, restart.request_restart)
        elif kind == "set_agent":
            try:
                self.core.set_agent(self.session.id, message.get("agent") or None)
            except ValueError as e:
                self.push({"type": "toast", "message": str(e), "kind": "warn"})
        elif kind == "listening":
            self.mic_open = bool(message.get("active", True))
            self.core.events.emit("remote_listening", self.session.id, active=self.mic_open)
        elif kind == "ping":
            self.push({"type": "pong"})
        elif kind == "auth":
            pass
        else:
            self.push({"type": "error", "message": f"Type de message inconnu : {kind}"})

    async def _sender_loop(self):
        while True:
            await self.ws.send_json(await self.outbox.get())

    async def run(self):
        await self.send_ready()
        sender_task = asyncio.create_task(self._sender_loop())
        try:
            while True:
                try:
                    message = json.loads(await self.ws.receive_text())
                except (json.JSONDecodeError, TypeError):
                    self.push({"type": "error", "message": "Message JSON invalide."})
                    continue
                if isinstance(message, dict):
                    await self.dispatch(message)
                else:
                    self.push({"type": "error", "message": "Objet JSON attendu."})
        except WebSocketDisconnect:
            pass
        finally:
            if self.mic_open:
                self.core.events.emit("remote_listening", self.session.id, active=False)
            self._unsub_session()
            self._unsub_global()
            self.core.detach_confirmation(self.session.id, confirm=self.confirm)
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_result(False)
            sender_task.cancel()
            print(f"🔌 [GATEWAY {self.session.id}] Client déconnecté")


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
            "pocketbase_url": core.settings.POCKETBASE_URL if directory.enabled else "",
            "version": local_version_info(),
        })

    async def ask(request: Request):
        try:
            body = await request.json()
            audio = base64.b64decode(body["audio"]) if body.get("audio") else None
        except Exception:
            return JSONResponse({"error": "Corps JSON invalide."}, status_code=400)
        try:
            images = decode_uploads(body.get("images"), core.settings)
        except ImageError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not body.get("text") and audio is None and not images:
            return JSONResponse({"error": "Champ 'text', 'audio' ou 'images' requis."}, status_code=400)
        # Seul le jeton maître protège /api/ask : c'est l'administrateur
        admin = admin_user(core.settings)
        session = core.open_session(body.get("session"), user=admin)
        reply = await asyncio.to_thread(
            core.respond, session.id, text=body.get("text"), audio_wav=audio, synthesize=bool(body.get("speak")),
            images=images, user=admin,
        )
        return JSONResponse(_reply_to_dict(reply))

    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        loop = asyncio.get_running_loop()

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

        session_id = hello.get("session") or ws.query_params.get("session")
        client = _WSClient(ws, core, directory, user, session_id, loop)
        await client.run()

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
