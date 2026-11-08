"""
Cœur de l'assistant, indépendant des entrées/sorties : sessions + pipeline (audio|texte -> STT -> LLM/outils -> voix).

Le même cœur sert le micro local (main.py, session "local") et les clients distants de la passerelle
(une session par client). Chaque session a sa conversation, son historique et sa façon de confirmer
les actions dangereuses. Les étapes du pipeline sont publiées sur `core.events` (voir core/events.py).
"""

import io
import sys
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import ENV_FILE, Settings, get_settings, set_settings
from core.events import EventBus
from core.history import HistoryStore, new_conversation_id
from core.sentences import SentenceSplitter, matches_phrase
from core.tools import ConfirmationHandler, ToolRegistry, ToolResult, build_tool_registry
from core.users import User, tool_policy, user_prompt
from llm.llm import Conversation, ResponseInterrupted


def to_wav_bytes(samples, sample_rate: int) -> bytes:
    """Encode des échantillons int16 (mono ou multi-canal) en fichier WAV en mémoire."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def _tool_summary(result: ToolResult) -> dict:
    return {
        "name": result.call.name,
        "arguments": result.call.arguments,
        "executed": result.executed,
        "output": result.output,
    }


def _asks_to_sleep(raw: str, tools: list[dict]) -> bool:
    """Le LLM a demandé la mise en veille : outil « sleep » exécuté, ou tag [SLEEP] dans le texte."""
    from actions.modules.sleep import SLEEP_ACTION
    if any(t["name"] == SLEEP_ACTION.tool_name and t["executed"] for t in tools):
        return True
    return bool(raw and SLEEP_ACTION.pattern.search(raw))


@dataclass
class Reply:
    session_id: str
    transcript: str = ""          # ce que l'utilisateur a dit (ou écrit)
    text: str = ""                # réponse épurée, prête pour la voix
    tools: list[dict] = field(default_factory=list)
    audio_wav: Optional[bytes] = None
    interrupted: bool = False     # génération abandonnée (barge-in, bouton stop)
    end_conversation: bool = False  # l'utilisateur a pris congé : retour en veille (phrase de fin ou outil « sleep »)


@dataclass
class Session:
    id: str
    conversation: Conversation
    persistent: bool = False      # jamais expirée (session locale)
    user: Optional[User] = None   # propriétaire (None : session interne, sans restriction d'outils)
    conversation_id: str = field(default_factory=new_conversation_id)  # conversation enregistrée (historique)
    restored: bool = False        # dernière conversation du compte déjà rechargée
    last_seen: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)


# Préfixes des paramètres lus par le fournisseur LLM : le modifier impose de recréer le fournisseur
_LLM_PREFIXES = ("LLM_", "OLLAMA_", "OPENROUTER_")


class AssistantCore:
    def __init__(self, settings: Optional[Settings] = None, stt=None, tts=None, tools: Optional[ToolRegistry] = None, llm=None,
                 env_file: Optional[Path] = None):
        self.settings = settings or get_settings()
        self.events = EventBus()
        self._llm = llm
        self._stt = stt
        self._tts = tts
        self._fallback_stt = None
        self._tools = tools
        # Composants fournis par l'appelant (tests, main.py) : jamais recréés, seulement mis à jour
        self._injected = {"llm": llm is not None, "tools": tools is not None}
        self.env_file = env_file or ENV_FILE
        self._sessions: dict[str, Session] = {}
        self._sessions_lock = threading.Lock()
        # Historique persistant des comptes (PocketBase) ; inactif sans annuaire
        self.history = HistoryStore(self.settings)

    # ---- Composants partagés (chargés au premier besoin) ----
    @property
    def llm(self):
        if self._llm is None:
            from llm.providers import LLM_PROVIDERS
            self._llm = LLM_PROVIDERS.create(self.settings.LLM_PROVIDER, self.settings)
        return self._llm

    @property
    def stt(self):
        if self._stt is None:
            from audio.stt import create_stt
            self._stt = create_stt(self.settings)
        return self._stt

    @property
    def fallback_stt(self):
        """Transcription de repli du mode direct (modèle sans entrée audio), chargée au premier besoin."""
        if self._fallback_stt is None:
            from audio.stt import create_fallback_stt
            self._fallback_stt = create_fallback_stt(self.settings)
        return self._fallback_stt

    def transcribe_audio(self, audio_wav: bytes) -> str:
        """Transcrit un buffer WAV avec le fournisseur STT actif (ou de repli si mode direct)."""
        stt = self.fallback_stt if self.stt.passthrough else self.stt
        return stt.transcribe(audio_wav)

    def audio_to_llm(self) -> bool:
        """True si un enregistrement doit être envoyé tel quel au modèle actif (mode direct et modèle audio)."""
        from audio.stt import STT_PROVIDERS
        # La classe suffit pour savoir si le mode est direct : inutile de charger Whisper pour le savoir
        passthrough = self._stt.passthrough if self._stt is not None else STT_PROVIDERS.get(self.settings.STT_PROVIDER).passthrough
        llm = self.llm
        return passthrough and not llm.is_decision_model() and llm.accepts_audio()

    @property
    def tts(self):
        if self._tts is None:
            from audio.tts import TextToSpeech
            self._tts = TextToSpeech(self.settings)
        return self._tts

    @property
    def tools(self) -> ToolRegistry:
        if self._tools is None:
            self._tools = build_tool_registry(self.settings)
        return self._tools

    def refresh_tools(self):
        """Reconstruit le registre d'outils (ex: après connexion du hub MCP) pour toutes les sessions."""
        self._tools = None
        with self._sessions_lock:
            for session in self._sessions.values():
                session.conversation._tools = None

    # ---- Paramètres modifiables à chaud (interface web) ----
    def update_settings(self, changes: dict) -> dict:
        """Valide les changements, les enregistre dans .env et applique ceux qui peuvent l'être sans redémarrer.
        Lève ValueError si un paramètre est inconnu, non modifiable ou invalide."""
        from core import settings_store
        new, changed = settings_store.validate_changes(self.settings, changes)
        if changed:
            settings_store.save_changes(new, changed, self.env_file)
            self.apply_settings(new, changed)
            print(f"⚙️ [CONFIG] Paramètres modifiés : {', '.join(changed)}")
        return {
            "changed": changed,
            "restart": [n for n in changed if not settings_store.EDITABLE[n][1]],
            "overridden": settings_store.overridden_by_environment(changed),
        }

    def apply_settings(self, settings: Settings, changed: list[str]):
        """Bascule le cœur et toutes les sessions (historique conservé) sur la nouvelle configuration."""
        if self.settings is get_settings():
            set_settings(settings)
        self.settings = settings
        if any(name.startswith(_LLM_PREFIXES) for name in changed):
            if self._injected["llm"]:
                self._llm.settings = settings
            else:
                self._llm = None
        if "STT_FALLBACK_PROVIDER" in changed:
            self._fallback_stt = None
        if any(name.startswith("ACTIONS_") for name in changed):
            if self._injected["tools"]:
                self._tools.settings = settings
            else:
                self._tools = None
        with self._sessions_lock:
            for session in self._sessions.values():
                conversation = session.conversation
                conversation.settings = settings
                conversation.max_messages = settings.LLM_HISTORY_MESSAGES
                conversation.tool_mode = settings.LLM_TOOL_CALLING
                conversation._provider = self.llm
                conversation._tools = self.tools
                conversation.tool_policy = tool_policy(session.user, settings)
                conversation.user_prompt = user_prompt(session.user, settings)

    def model_info(self) -> dict:
        """Modèle actif, pour l'affichage côté client."""
        llm = self.llm
        return {"provider": self.settings.LLM_PROVIDER, "model": llm.model, "decision": llm.is_decision_model(),
                "audio_input": self.audio_to_llm()}

    # ---- Sessions ----
    def open_session(
        self,
        session_id: Optional[str] = None,
        confirm: Optional[ConfirmationHandler] = None,
        persistent: bool = False,
        user: Optional[User] = None,
    ) -> Session:
        """Retourne la session existante (en mettant à jour sa confirmation) ou en crée une nouvelle.
        Avec `user`, une session appartenant à quelqu'un d'autre n'est jamais reprise : une nouvelle est créée
        (un client ne peut pas lire l'historique d'un autre compte en devinant son identifiant de session)."""
        self._expire_sessions()
        with self._sessions_lock:
            sid = session_id or uuid.uuid4().hex[:12]
            session = self._sessions.get(sid)
            if session is not None and user is not None and (session.user is None or session.user.id != user.id):
                print(f"⛔ [ASSISTANT] Session {sid} d'un autre utilisateur : nouvelle session pour {user.name}.")
                session, sid = None, uuid.uuid4().hex[:12]
            if session is None:
                conversation = Conversation(self.llm, self.settings, tools=self.tools, confirm=confirm,
                                            tool_policy=tool_policy(user, self.settings))
                conversation.user_prompt = user_prompt(user, self.settings)
                session = Session(sid, conversation, persistent=persistent, user=user)
                self._sessions[sid] = session
            else:
                if confirm is not None:
                    session.conversation.confirm = confirm
                if user is not None and session.user != user:
                    # Même compte, rôle, profil ou jeton renouvelés à la reconnexion : droits et prompt suivent
                    self._assign_user(session, user)
            session.last_seen = time.monotonic()
            return session

    def _assign_user(self, session: Session, user: User):
        session.user = user
        session.conversation.tool_policy = tool_policy(user, self.settings)
        session.conversation.user_prompt = user_prompt(user, self.settings)

    def set_session_user(self, session_id: str, user: User):
        """Profil du même compte modifié (prénom, consignes) : pris en compte dès la demande suivante."""
        session = self.get_session(session_id)
        if session is None or session.user is None or session.user.id != user.id:
            raise ValueError("Session d'un autre utilisateur.")
        self._assign_user(session, user)

    # ---- Voix ----
    def voices(self) -> list[dict]:
        """Voix que les comptes peuvent choisir (vide si le fournisseur TTS n'en propose pas ou ne charge pas)."""
        try:
            return self.tts.voices()
        except Exception as e:
            print(f"⚠️ [ASSISTANT] Liste des voix indisponible : {e}")
            return []

    def session_voice(self, session_id: str) -> Optional[str]:
        """Voix du compte de la session, si elle est encore installée (sinon None : voix configurée)."""
        session = self.get_session(session_id)
        voice = session.user.voice if session and session.user else ""
        return voice if voice and voice in {v["id"] for v in self.voices()} else None

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str):
        with self._sessions_lock:
            self._sessions.pop(session_id, None)

    def cancel(self, session_id: str):
        """Interrompt la réponse en cours de la session (prise en compte au prochain fragment généré)."""
        session = self.get_session(session_id)
        if session:
            session.cancel.set()

    def detach_confirmation(self, session_id: str):
        """Le client s'est déconnecté : la session survit (reprise possible) mais ne peut plus confirmer."""
        session = self.get_session(session_id)
        if session:
            session.conversation.confirm = None

    def _expire_sessions(self):
        limit = time.monotonic() - self.settings.GATEWAY_SESSION_TIMEOUT
        with self._sessions_lock:
            for sid in [s.id for s in self._sessions.values() if not s.persistent and s.last_seen < limit]:
                del self._sessions[sid]

    # ---- Historique (le verrou attend la fin de la réponse en cours, qui pourrait y écrire) ----
    def restore_history(self, session_id: str) -> list[dict]:
        """Recharge une fois la dernière conversation enregistrée du compte (session neuve), puis renvoie
        la conversation de la session pour l'affichage : [{role, content, turn?}], tags d'actions retirés."""
        session = self.get_session(session_id)
        if session is None:
            return []
        if not session.restored and self.history.applies(session.user):
            conversation_id, messages = self.history.load_latest(session.user)
            with session.lock:
                conversation = session.conversation
                if conversation_id and not (conversation.older or conversation.history):
                    session.conversation_id = conversation_id
                    conversation.older = messages
                    conversation._fit_window()
                    print(f"📜 [ASSISTANT {session.id}] Conversation de {session.user.name} rechargée "
                          f"({len(messages)} message(s))")
        session.restored = True
        return self._format_messages_for_client(session)

    def _format_messages_for_client(self, session: Session) -> list[dict]:
        from actions.manager import get_action_manager
        manager = get_action_manager()
        with session.lock:
            messages = list(session.conversation.older) + list(session.conversation.history)
        result = []
        for m in messages:
            if m.get("role") not in ("user", "assistant"):
                continue
            entry = {
                "role": m["role"],
                **({"turn": m["turn"]} if m.get("turn") else {})
            }
            if m["role"] == "assistant":
                cleaned, acts = manager.extract_actions(m["content"])
                entry["content"] = cleaned
                tools = list(m.get("tools") or [])
                if not tools and acts:
                    for act in acts:
                        cmd = act.get("definition")
                        tools.append({
                            "name": cmd.tool_name if cmd else act.get("tag", "").lower(),
                            "arguments": {"raw": act.get("args", "")} if act.get("args") else {},
                            "executed": True,
                            "output": "",
                            "tag": act.get("tag", "")
                        })
                if tools:
                    entry["tools"] = tools
            else:
                entry["content"] = m["content"]
            result.append(entry)
        return result

    def load_conversation(self, session_id: str, conversation_id: str, client_messages: Optional[list] = None) -> list[dict]:
        """Bascule la session sur une conversation existante et renvoie ses messages."""
        session = self.get_session(session_id)
        if session is None:
            return []
        with session.lock:
            session.conversation.clear()
            session.conversation_id = conversation_id
            messages = []
            if self.history.applies(session.user):
                _, messages = self.history.load_conversation(session.user, conversation_id)
            elif client_messages:
                messages = client_messages
            session.conversation.older = messages
            session.conversation._fit_window()
            session.restored = True
            print(f"📜 [ASSISTANT {session.id}] Conversation {conversation_id} chargée ({len(messages)} message(s))")
        return self._format_messages_for_client(session)

    def list_conversations(self, session_id: str) -> list[dict]:
        """Retourne la liste des conversations du compte."""
        session = self.get_session(session_id)
        if session is None or not self.history.applies(session.user):
            return []
        return self.history.list_conversations(session.user)

    def delete_conversation(self, session_id: str, conversation_id: str) -> bool:
        """Supprime une conversation du compte. Si c'est la conversation active, réinitialise la session."""
        session = self.get_session(session_id)
        if session is None:
            return False
        with session.lock:
            if session.conversation_id == conversation_id:
                session.conversation.clear()
                session.conversation_id = new_conversation_id()
        if self.history.applies(session.user):
            self.history.delete_conversation(session.user, conversation_id)
        return True

    def reset(self, session_id: str):
        """Nouvelle conversation : l'historique en mémoire est vidé, l'ancienne conversation reste enregistrée."""
        session = self.get_session(session_id)
        if session:
            with session.lock:
                session.conversation.clear()
                session.conversation_id = new_conversation_id()

    def forget(self, session_id: str, turns: Iterable[str], role: Optional[str] = None):
        """Retire de l'historique les messages de ces échanges (seulement ceux de `role` s'il est précisé)."""
        session = self.get_session(session_id)
        if session:
            turns = list(turns)
            with session.lock:
                session.conversation.forget(turns, role)
                self.history.forget(session.user, session.conversation_id, turns, role)

    def edit_answer(self, session_id: str, turn: str, text: str, forget: Iterable[str] = ()):
        """Remplace la réponse d'un échange et retire les échanges `forget` (ceux qui la suivaient)."""
        session = self.get_session(session_id)
        if session:
            forget = list(forget)
            with session.lock:
                session.conversation.edit_answer(turn, text)
                session.conversation.forget(forget)
                self.history.edit_answer(session.user, session.conversation_id, turn, text)
                self.history.forget(session.user, session.conversation_id, forget)

    # ---- Pipeline ----
    def respond(
        self,
        session_id: str,
        text: Optional[str] = None,
        audio_wav: Optional[bytes] = None,
        synthesize: bool = False,
        on_sentence: Optional[Callable[[str], None]] = None,
        turn: Optional[str] = None,
        forget: Iterable[str] = (),
    ) -> Reply:
        """Traite une demande (texte ou enregistrement WAV) et retourne la réponse. Bloquant : à appeler
        depuis un thread pour un serveur asyncio. Les demandes d'une même session sont traitées une à une.
        `on_sentence` reçoit chaque phrase à prononcer dès qu'elle est complète (parole en streaming).
        `turn` identifie l'échange (repris dans les événements et l'historique) ; `forget` retire d'abord
        ces échanges de l'historique (relance d'un message : les suivants sont effacés)."""
        session = self.open_session(session_id)
        sid = session.id

        def emit(event_type: str, session_id: str, **data):
            self.events.emit(event_type, session_id, **data, **({"turn": turn} if turn else {}))

        with session.lock:
            session.last_seen = time.monotonic()
            session.cancel.clear()
            forget = list(forget)
            session.conversation.forget(forget)
            self.history.forget(session.user, session.conversation_id, forget)
            # Échange toujours numéroté dans l'historique (pour l'enregistrer, puis l'effacer ou le corriger)
            stored_turn = turn or uuid.uuid4().hex[:12]
            print(f"\n📥 [ASSISTANT {sid}] Nouveau tour (texte: « {text or ''} », audio: {len(audio_wav) if audio_wav else 0} octets)")
            reply = Reply(sid, transcript=(text or "").strip())
            llm_audio = None

            if audio_wav is not None:
                if self.audio_to_llm():
                    llm_audio = audio_wav
                else:
                    try:
                        stt = self.fallback_stt if self.stt.passthrough else self.stt
                        reply.transcript = stt.transcribe(audio_wav)
                    except Exception as e:
                        emit("error", sid, message=f"Erreur de transcription : {e}")
                        return reply
                    emit("transcript", sid, text=reply.transcript)
                    print(f"🎙️ [STT {sid}] Transcription : « {reply.transcript} »")

            if not reply.transcript and llm_audio is None:
                emit("response", sid, text="", tools=[])
                return reply

            # « Au revoir », « c'est tout »... : fin immédiate, sans solliciter le LLM
            s = self.settings
            if reply.transcript and matches_phrase(reply.transcript, s.CONVERSATION_END_PHRASES, s.CONVERSATION_END_FILLERS):
                reply.end_conversation = True
                emit("response", sid, text="", tools=[], end_conversation=True)
                return reply

            splitter = SentenceSplitter(self.settings.TTS_STREAM_MIN_CHARS) if on_sentence else None
            spoken: list[str] = []

            def say(sentence: str):
                spoken.append(sentence)
                on_sentence(sentence)

            def on_token(token: str):
                if session.cancel.is_set():
                    raise ResponseInterrupted()
                emit("token", sid, text=token)
                if splitter:
                    for sentence in splitter.feed(token):
                        say(sentence)

            raw = session.conversation.ask(
                prompt=reply.transcript or None,
                audio_bytes=llm_audio,
                on_token=on_token,
                on_tool=lambda r: emit("tool", sid, **_tool_summary(r)),
                turn=stored_turn,
            )
            reply.tools = [_tool_summary(r) for r in session.conversation.last_tool_results]

            if session.cancel.is_set():
                reply.interrupted = True
                emit("interrupted", sid)
                return reply

            # Mode tags (ou tag égaré) : exécution des [ACTION] du texte et nettoyage pour la voix
            reply.text = raw
            if raw and self.settings.ACTIONS_ENABLED:
                from actions.manager import get_action_manager

                def on_tag_action(tool_info):
                    emit("tool", sid, **tool_info)
                    reply.tools.append(tool_info)

                reply.text = get_action_manager().process_response(
                    raw, confirm=session.conversation.confirm, policy=session.conversation.tool_policy,
                    on_action=on_tag_action)

            # Associe les outils exécutés au message assistant dans l'historique
            conversation = session.conversation
            for m in reversed(conversation.history):
                if m.get("turn") == stored_turn and m.get("role") == "assistant":
                    m["tools"] = list(reply.tools)
                    break

            self.history.append(session.user, session.conversation_id,
                                [m for m in conversation.older + conversation.history if m.get("turn") == stored_turn])
            if splitter:
                for sentence in splitter.flush():
                    say(sentence)

            reply.end_conversation = _asks_to_sleep(raw, reply.tools)
            print(f"📤 [ASSISTANT {sid}] Réponse : « {reply.text} » ({len(reply.tools)} outil(s))")
            emit("response", sid, text=reply.text, tools=reply.tools, end_conversation=reply.end_conversation)

            # Rien n'a été prononcé en direct (réponse non streamée, message d'erreur...) : on dit le texte final
            if on_sentence and not spoken and reply.text:
                say(reply.text)

            if synthesize and reply.text:
                try:
                    samples, sample_rate = self.tts.synthesize(reply.text, voice=self.session_voice(sid))
                    if len(samples):
                        reply.audio_wav = to_wav_bytes(samples, sample_rate)
                except Exception as e:
                    emit("error", sid, message=f"Erreur de synthèse vocale : {e}")
            return reply


if __name__ == "__main__":
    print("🧪 [DEBUG] AssistantCore en mode texte (session 'debug', Ctrl+C pour quitter)")
    core = AssistantCore()
    core.events.subscribe(lambda e: print(e.data["text"], end="", flush=True) if e.type == "token" else None)
    core.open_session("debug")
    while True:
        try:
            question = input("\nToi > ").strip()
            if question:
                print("Assistant > ", end="", flush=True)
                core.respond("debug", text=question)
        except (KeyboardInterrupt, EOFError):
            break
