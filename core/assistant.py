"""
Cœur de l'assistant, indépendant des entrées/sorties : sessions + pipeline (audio|texte -> STT -> LLM/outils -> voix).

Le même cœur sert le micro local (main.py, session "local") et les clients distants de la passerelle
(une session par client). Chaque session a sa conversation, son historique et sa façon de confirmer
les actions dangereuses. Les étapes du pipeline sont publiées sur `core.events` (voir core/events.py).
"""

import io
import sys
from string import Template
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

from core.archive import SOURCE_API, SOURCE_LOCAL, SOURCE_PWA, ConversationArchive, clean_rating
from core.agents import ASSISTANT, AgentCancelled, AgentDirectory, AgentError, AgentRunner, AgentSpec, detect_switch
from core.config import ENV_FILE, Settings, get_settings, set_settings
from core.events import EventBus
from core.history import HistoryStore, is_safe_id, new_conversation_id, sanitize_messages
from core.images import Image, ImageError, load_image, save_upload
from core.memory import MemoryStore
from core.metrics import TurnTimer, format_timings
from core.scheduler import Scheduler
from core.turn_context import session_context
from core.sentences import SentenceSplitter, matches_phrase, strip_markdown
from core.tools import ConfirmationHandler, ToolRegistry, ToolResult, build_tool_registry
from core.users import LOCAL_USER_ID, User, tool_policy, user_prompt
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


def _shown_image(tool: dict) -> Optional[str]:
    """Chemin de l'image que l'outil « show_image » (ou le tag [SHOW_IMAGE]) a validée, sinon None."""
    from actions.modules.files import SHOW_IMAGE_TOOL
    if tool.get("name") != SHOW_IMAGE_TOOL or not tool.get("executed"):
        return None
    args = tool.get("arguments") or {}
    return str(args.get("args") or args.get("raw") or "") or None


def _requested_agent(raw: str, tools: list[dict]) -> Optional[str]:
    """Le LLM a relié la conversation à un agent externe : outil « agent » exécuté, ou tag [AGENT nom]."""
    from actions.modules.agent import AGENT_ACTION
    for t in tools:
        if t["name"] == AGENT_ACTION.tool_name and t.get("executed"):
            args = t.get("arguments") or {}
            return str(args.get("args") or args.get("raw") or "")
    match = AGENT_ACTION.pattern.search(raw or "")
    return (match.group(1) or "").strip() if match else None


@dataclass
class Reply:
    session_id: str
    transcript: str = ""          # ce que l'utilisateur a dit (ou écrit)
    text: str = ""                # réponse épurée, prête pour la voix
    tools: list[dict] = field(default_factory=list)
    audio_wav: Optional[bytes] = None
    interrupted: bool = False     # génération abandonnée (barge-in, bouton stop)
    end_conversation: bool = False  # l'utilisateur a pris congé : retour en veille (phrase de fin ou outil « sleep »)
    images: list[dict] = field(default_factory=list)  # images montrées par l'assistant (outil show_image)
    turn: str = ""                # numéro de l'échange dans l'historique
    timings: dict = field(default_factory=dict)  # latence par étape, en ms (core/metrics.py)


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
    agent: Optional[str] = None   # agent externe relié à la conversation (None : l'assistant répond)
    agent_sessions: dict[str, str] = field(default_factory=dict)  # identifiant de session de chaque agent
    clients: int = 0              # clients connectés (WebSocket) : une session suivie n'expire jamais


@dataclass
class _Speaker:
    """Phrases d'un tour : prononcées au fil de l'eau (on_sentence) et retenues pour savoir si tout a été dit."""
    on_sentence: Optional[Callable[[str], None]]
    spoken: list[str] = field(default_factory=list)
    timer: Optional[TurnTimer] = None

    def say(self, sentence: str):
        if self.on_sentence and sentence.strip():
            if self.timer:
                self.timer.mark("first_sentence")
            self.spoken.append(sentence)
            self.on_sentence(sentence)


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
        # Micro de l'ordinateur à l'écoute du mot-clé (main.py) : sans lui, WAKEWORD_ENABLED n'a pas d'effet
        self.local_microphone = False
        self._sessions: dict[str, Session] = {}
        self._sessions_lock = threading.Lock()
        # Historique persistant des comptes (PocketBase) ; inactif sans annuaire
        self.history = HistoryStore(self.settings)
        # Archive de tous les échanges et des notes (données d'entraînement, jamais purgée)
        self.archive = ConversationArchive(self.settings)
        # Agents externes (agents.json) que la conversation peut rejoindre
        self._agents: Optional[AgentDirectory] = None
        # Rappels et routines (outils remind / routine) : le fil d'échéances démarre avec start_scheduler()
        self.scheduler = Scheduler(self)
        # Souvenirs de chaque compte (outils remember / forget_memory), ajoutés au prompt système de ses tours
        self.memory = MemoryStore(self.settings)
        # Outils [GET_SETTINGS] / [SET_SETTING] : l'assistant modifie ses paramètres à travers ce cœur
        from core import settings_store
        settings_store.set_owner(self)

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

    def images_to_llm(self) -> bool:
        """True si le modèle actif lit les images jointes (capacité « vision », LLM_IMAGE_INPUT)."""
        try:
            return self.settings.IMAGES_ENABLED and self.llm.accepts_images()
        except Exception as e:
            print(f"⚠️ [ASSISTANT] Capacité de vision inconnue : {e}")
            return False

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

    @property
    def agents(self) -> AgentDirectory:
        if self._agents is None:
            self._agents = AgentDirectory(self.settings)
        return self._agents

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
        if any(name.startswith("AGENTS_") for name in changed):
            self._agents = None
        if "STT_FALLBACK_PROVIDER" in changed:
            self._fallback_stt = None
        self.memory.update_settings(settings)
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
                "audio_input": self.audio_to_llm(), "vision": self.images_to_llm(),
                "images": self.settings.IMAGES_ENABLED}

    # ---- Sessions ----
    def open_session(
        self,
        session_id: Optional[str] = None,
        confirm: Optional[ConfirmationHandler] = None,
        persistent: bool = False,
        user: Optional[User] = None,
        attach: bool = False,
    ) -> Session:
        """Retourne la session existante (en mettant à jour sa confirmation) ou en crée une nouvelle.
        Avec `user`, une session appartenant à quelqu'un d'autre n'est jamais reprise : une nouvelle est créée
        (un client ne peut pas lire l'historique d'un autre compte en devinant son identifiant de session).
        `attach` : un client connecté suit la session (WebSocket) ; elle n'expire pas avant `detach_confirmation`."""
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
            if attach:
                session.clients += 1
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
        """Voix de la session : celle de l'agent relié, sinon celle du compte si elle est encore installée
        (None : voix configurée)."""
        session = self.get_session(session_id)
        agent = self._current_agent(session) if session else None
        if agent is not None:
            return self._agent_voice(agent, session)
        voice = session.user.voice if session and session.user else ""
        return voice if voice and voice in {v["id"] for v in self.voices()} else None

    def _agent_voice(self, agent: AgentSpec, session: Optional[Session]) -> Optional[str]:
        """Voix de l'agent (sa fiche, AGENTS_DEFAULT_VOICE, sinon une autre voix installée que l'assistant)."""
        voices = self.voices()
        installed = [v["id"] for v in voices]
        for wanted in (agent.voice, self.settings.AGENTS_DEFAULT_VOICE):
            if wanted and wanted in installed:
                return wanted
        user_voice = session.user.voice if session and session.user else ""
        assistant = user_voice if user_voice in installed else next((v["id"] for v in voices if v.get("default")), "")
        return next((v for v in installed if v != assistant), None)

    # ---- Agents externes ----
    def agents_allowed(self, user: Optional[User]) -> bool:
        s = self.settings
        if not s.AGENTS_ENABLED:
            return False
        return user is None or user.superadmin or user.role in s.AGENTS_ROLES

    def available_agents(self, session_id: str) -> list[dict]:
        """Agents que le compte de la session peut rejoindre (pour la PWA)."""
        session = self.get_session(session_id)
        if session is None or not self.agents_allowed(session.user):
            return []
        # Un agent dont la commande n'est pas installée n'est pas proposé dans le menu de la PWA
        return [a.public() for a in self.agents.all() if a.executable(self.settings)]

    def _current_agent(self, session: Session) -> Optional[AgentSpec]:
        if not session.agent:
            return None
        spec = self.agents.get(session.agent)
        if spec is None or not self.agents_allowed(session.user):
            session.agent = None   # agent retiré de agents.json ou droits perdus
        return spec if session.agent else None

    def agent_info(self, session_id: str) -> Optional[dict]:
        """Agent relié à la session (fiche publique et voix), None si c'est l'assistant qui répond."""
        session = self.get_session(session_id)
        agent = self._current_agent(session) if session else None
        if agent is None:
            return None
        return {**agent.public(), "voice": self._agent_voice(agent, session)}

    def agent_error(self, agent: AgentSpec, error) -> str:
        return Template(self.settings.AGENTS_ERROR_MESSAGE).safe_substitute(AGENT=agent.label, ERROR=str(error))

    def set_agent(self, session_id: str, name: Optional[str]) -> Optional[AgentSpec]:
        """Relie la session à un agent (None : retour à l'assistant).
        Lève ValueError (inconnu, non autorisé, commande non installée : la session reste à l'assistant)."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError("Session inconnue.")
        spec = None
        if name:
            spec = self.agents.get(name)
            if spec is None:
                raise ValueError(f"Agent « {name} » inconnu.")
            if not self.agents_allowed(session.user):
                raise ValueError(Template(self.settings.AGENTS_DENIED_MESSAGE).safe_substitute(AGENT=spec.label))
            if spec.executable(self.settings) is None:
                print(f"⚠️ [AGENTS] {spec.label} : commande « {spec.command[0]} » introuvable")
                raise ValueError(self.agent_error(spec, f"commande « {spec.command[0]} » introuvable"))
        previous = session.agent
        session.agent = spec.name if spec else None
        if previous != session.agent:
            print(f"🤝 [ASSISTANT {session.id}] " + (f"Conversation reliée à {spec.label}" if spec
                                                      else "Retour à l'assistant"))
            self.events.emit("agent_changed", session.id, agent=self.agent_info(session.id))
        return spec

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
            session.clients = max(0, session.clients - 1)
            session.last_seen = time.monotonic()

    def _expire_sessions(self):
        limit = time.monotonic() - self.settings.GATEWAY_SESSION_TIMEOUT
        with self._sessions_lock:
            expired = [s.id for s in self._sessions.values()
                       if not s.persistent and not s.clients and s.last_seen < limit]
            for sid in expired:
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
        return self._with_feedback(self._format_messages_for_client(session), session.conversation_id, session.user)

    def _format_messages_for_client(self, session: Session) -> list[dict]:
        with session.lock:
            messages = list(session.conversation.older) + list(session.conversation.history)
        return self._clean_for_client(messages)

    @staticmethod
    def _clean_for_client(messages: list[dict]) -> list[dict]:
        """Messages pour l'affichage : [{role, content, turn?, tools?}], tags d'actions retirés des réponses."""
        from actions.manager import get_action_manager
        manager = get_action_manager()
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
        """Bascule la session sur une conversation existante et renvoie ses messages.
        Lève ValueError si l'identifiant n'est pas valide (il est ensuite écrit dans l'historique du compte)."""
        if not is_safe_id(conversation_id):
            raise ValueError("Identifiant de conversation invalide.")
        session = self.get_session(session_id)
        if session is None:
            return []
        with session.lock:
            session.conversation.clear()
            session.conversation_id = conversation_id
            messages = []
            if self.history.applies(session.user):
                _, messages = self.history.load_conversation(session.user, conversation_id)
            elif session.user is not None:
                # Sans historique PocketBase (jeton maître) : l'archive fait foi, sinon les messages de l'appareil
                messages = self.archive.load_conversation(conversation_id, SOURCE_PWA, session.user.id)
            if not messages and client_messages and not self.history.applies(session.user):
                messages = sanitize_messages(client_messages)
            session.conversation.older = messages
            session.conversation._fit_window()
            session.restored = True
            print(f"📜 [ASSISTANT {session.id}] Conversation {conversation_id} chargée ({len(messages)} message(s))")
        return self._with_feedback(self._format_messages_for_client(session), conversation_id, session.user)

    def list_conversations(self, session_id: str) -> list[dict]:
        """Conversations du compte (PocketBase, sinon l'archive pour le jeton maître), puis celles du micro de
        l'ordinateur si son rôle les voit (ARCHIVE_HOUSEHOLD_ROLES ; marquées « source »: « local »)."""
        session = self.get_session(session_id)
        if session is None or session.user is None:
            return []
        if self.history.applies(session.user):
            conversations = self.history.list_conversations(session.user)
        else:
            conversations = self.archive.list_conversations(SOURCE_PWA, session.user.id)
        if self.sees_household(session.user):
            conversations += self.archive.list_conversations(SOURCE_LOCAL)
        return conversations

    # ---- Conversations du micro de l'ordinateur & notes des réponses ----
    def sees_household(self, user: Optional[User]) -> bool:
        """La voix n'est pas identifiée : les conversations du micro appartiennent au foyer, visibles par ces rôles."""
        return (self.archive.enabled and user is not None and user.id != LOCAL_USER_ID
                and (user.superadmin or user.role in self.settings.ARCHIVE_HOUSEHOLD_ROLES))

    def household_conversation(self, session_id: str, conversation_id: str) -> list[dict]:
        """Messages d'une conversation tenue au micro, pour affichage seul (la session n'en change pas).
        Lève PermissionError si ce compte ne voit pas les conversations du foyer."""
        session = self.get_session(session_id)
        if not is_safe_id(conversation_id):
            raise ValueError("Identifiant de conversation invalide.")
        if session is None or not self.sees_household(session.user):
            raise PermissionError("Conversations du micro réservées aux rôles ARCHIVE_HOUSEHOLD_ROLES.")
        messages = self._clean_for_client(self.archive.load_conversation(conversation_id, SOURCE_LOCAL))
        return self._with_feedback(messages, conversation_id, session.user)

    def new_local_conversation(self, session_id: str):
        """Retour en veille du micro : l'échange suivant ouvre une nouvelle conversation dans l'archive (le contexte
        du LLM est gardé, comme avant)."""
        session = self.get_session(session_id)
        if session is not None:
            with session.lock:
                session.conversation_id = new_conversation_id()

    def _with_feedback(self, messages: list[dict], conversation_id: str, user: Optional[User]) -> list[dict]:
        if not self.settings.FEEDBACK_ENABLED or user is None or not messages:
            return messages
        notes = self.archive.feedback_for(conversation_id, user.id)
        for m in messages:
            if m.get("role") == "assistant" and m.get("turn") in notes:
                m["feedback"] = notes[m["turn"]]
        return messages

    def feedback_available(self) -> bool:
        return bool(self.settings.FEEDBACK_ENABLED and self.archive.enabled)

    def set_feedback(self, session_id: str, conversation_id: str, turn: str, rating, comment: str = "") -> dict:
        """Note (-2 à +2) et commentaire facultatif d'une réponse, enregistrés dans l'archive au nom du compte.
        On ne note que ce qu'on peut lire : ses propres conversations, ou celles du micro (ARCHIVE_HOUSEHOLD_ROLES).
        Lève ValueError (donnée invalide, notes désactivées) ou PermissionError."""
        if not self.feedback_available():
            raise ValueError("Les notes ne sont pas activées (FEEDBACK_ENABLED, ARCHIVE_ENABLED).")
        if not is_safe_id(conversation_id) or not is_safe_id(turn):
            raise ValueError("Réponse inconnue.")
        value = clean_rating(rating)
        if value is None:
            raise ValueError("La note doit être un entier de -2 à +2.")
        session = self.get_session(session_id)
        if session is None or session.user is None:
            raise PermissionError("Session inconnue.")
        user = session.user
        comment = str(comment or "").strip()[:self.settings.FEEDBACK_COMMENT_MAX_CHARS]
        row = self.archive.has_turn(conversation_id, turn)
        if row is not None:
            allowed = row["user_id"] == user.id or (row["source"] == SOURCE_LOCAL and self.sees_household(user))
        else:
            # Échange antérieur à l'archive : seulement s'il figure dans l'historique PocketBase du compte, copié alors
            # dans l'archive pour que la note y retrouve sa réponse
            allowed = False
            if self.history.applies(user):
                _, stored = self.history.load_conversation(user, conversation_id)
                exchange = [m for m in stored if m.get("turn") == turn]
                if any(m["role"] == "assistant" for m in exchange):
                    allowed = True
                    self.archive.append(conversation_id, exchange, SOURCE_PWA, session.id, user.id, user.name)
        if not allowed:
            raise PermissionError("Cette réponse ne peut pas être notée depuis ce compte.")
        if not self.archive.set_feedback(conversation_id, turn, user.id, user.name, value, comment):
            raise ValueError("Note non enregistrée (archive indisponible).")
        print(f"⭐ [ASSISTANT {session.id}] {user.name} note {value:+d} la réponse {turn}"
              f"{' (avec commentaire)' if comment else ''}")
        return {"conversation_id": conversation_id, "turn": turn, "rating": value, "comment": comment}

    @staticmethod
    def _source(session: Session) -> str:
        if session.user is None:
            return SOURCE_API
        return SOURCE_LOCAL if session.user.id == LOCAL_USER_ID else SOURCE_PWA

    def _archive_exchange(self, session: Session, messages: list[dict]):
        user = session.user
        source = self._source(session)
        try:
            model = self.llm.model
        except Exception:
            model = ""
        if self.archive.append(session.conversation_id, messages, source, session.id,
                               user.id if user else "", user.name if user else "", model) and source == SOURCE_LOCAL:
            # Les PWA ouvertes rafraîchissent leur liste (conversation au micro en cours)
            self.events.emit("history_updated", session.id, conversation_id=session.conversation_id, source=source)

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
        if session.user is not None and is_safe_id(conversation_id):
            # Masquée seulement : l'archive (données d'entraînement) la garde
            self.archive.hide_conversation(conversation_id, session.user.id)
        return True

    def reset(self, session_id: str):
        """Nouvelle conversation : l'historique en mémoire est vidé, l'ancienne conversation reste enregistrée."""
        session = self.get_session(session_id)
        if session:
            with session.lock:
                session.conversation.clear()
                session.conversation_id = new_conversation_id()
                session.agent_sessions.clear()
            self.set_agent(session_id, None)

    def forget(self, session_id: str, turns: Iterable[str], role: Optional[str] = None):
        """Retire de l'historique les messages de ces échanges (seulement ceux de `role` s'il est précisé)."""
        session = self.get_session(session_id)
        if session:
            turns = list(turns)
            with session.lock:
                session.conversation.forget(turns, role)
                self.history.forget(session.user, session.conversation_id, turns, role)
                self.archive.hide_turns(session.conversation_id, turns, role)

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
                self.archive.edit_answer(session.conversation_id, turn, text)
                self.archive.hide_turns(session.conversation_id, forget)

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
        images: Iterable[Image] = (),
        user: Optional[User] = None,
    ) -> Reply:
        """Traite une demande et mesure sa latence étape par étape (voir `_respond` et core/metrics.py)."""
        timer = TurnTimer()
        reply = self._respond(session_id, text, audio_wav, synthesize, on_sentence, turn, forget, images, user, timer)
        timer.mark("total")
        self._record_timings(reply, timer, turn)
        return reply

    # ---- Mémoire à long terme (vue de l'utilisateur : PWA) ----
    def _memory_owner(self, session_id: str) -> str:
        session = self.get_session(session_id)
        user = session.user if session is not None else None
        return user.id if user is not None else LOCAL_USER_ID

    def list_memories(self, session_id: str) -> list[dict]:
        if not self.memory.enabled:
            return []
        return [m.public() for m in self.memory.all(self._memory_owner(session_id))]

    def add_memory(self, session_id: str, text: str) -> dict:
        """Souvenir ajouté à la main (PWA). ValueError si vide, trop long ou mémoire pleine."""
        if not self.memory.enabled:
            raise ValueError("Mémoire désactivée (MEMORY_ENABLED=false).")
        memory, _ = self.memory.remember(self._memory_owner(session_id), text)
        return memory.public()

    def delete_memory(self, session_id: str, memory_id) -> bool:
        try:
            memory_id = int(memory_id)
        except (TypeError, ValueError):
            return False
        return self.memory.forget(self._memory_owner(session_id), memory_id)

    def start_scheduler(self):
        """Déclenche les rappels à l'échéance (main.py, python -m gateway). Un seul processus doit l'appeler."""
        self.scheduler.start()

    def stop_scheduler(self):
        self.scheduler.stop()

    def _record_timings(self, reply: Reply, timer: TurnTimer, turn: Optional[str]):
        """Publie et archive la latence d'un tour qui a produit une réponse (ni vide, ni interrompu)."""
        if not self.settings.METRICS_ENABLED or reply.interrupted or not (reply.text or reply.tools):
            return
        reply.timings = timer.as_ms()
        session = self.get_session(reply.session_id)
        if session is not None and session.agent:
            model = f"agent:{session.agent}"
        else:
            try:
                model = self.llm.model
            except Exception:
                model = ""
        print(f"⏱️ [METRICS {reply.session_id}] {format_timings(reply.timings)}")
        self.events.emit("timings", reply.session_id, timings=reply.timings, model=model,
                         **({"turn": turn} if turn else {}))
        if session is not None:
            self.archive.add_timings(session.conversation_id, reply.turn, self._source(session), model, reply.timings)

    def _respond(
        self,
        session_id: str,
        text: Optional[str],
        audio_wav: Optional[bytes],
        synthesize: bool,
        on_sentence: Optional[Callable[[str], None]],
        turn: Optional[str],
        forget: Iterable[str],
        images: Iterable[Image],
        user: Optional[User],
        timer: TurnTimer,
    ) -> Reply:
        """Traite une demande (texte ou enregistrement WAV) et retourne la réponse. Bloquant : à appeler
        depuis un thread pour un serveur asyncio. Les demandes d'une même session sont traitées une à une.
        `on_sentence` reçoit chaque phrase à prononcer dès qu'elle est complète (parole en streaming).
        `turn` identifie l'échange (repris dans les événements et l'historique) ; `forget` retire d'abord
        ces échanges de l'historique (relance d'un message : les suivants sont effacés).
        `images` (déjà validées, voir core.images.decode_uploads) accompagnent le message : envoyées au modèle s'il
        a la vision (sinon événement « warning » et seul le texte est traité), ou transmises par chemin à un agent.
        `user` : propriétaire attendu de la session. Les appelants qui servent un compte (passerelle) doivent le
        donner : une session disparue entre-temps est alors recréée avec les droits de ce compte, jamais sans
        propriétaire (une session sans propriétaire n'a aucune restriction d'outils)."""
        session = self.open_session(session_id, user=user)
        sid = session.id

        def emit(event_type: str, session_id: str, **data):
            self.events.emit(event_type, session_id, **data, **({"turn": turn} if turn else {}))

        images = list(images)
        # Les outils exécutés pendant ce tour savent pour quel compte ils agissent (rappels, souvenirs)
        with session.lock, session_context(session):
            session.last_seen = time.monotonic()
            session.cancel.clear()
            forget = list(forget)
            session.conversation.forget(forget)
            self.history.forget(session.user, session.conversation_id, forget)
            self.archive.hide_turns(session.conversation_id, forget)
            # Échange toujours numéroté dans l'historique (pour l'enregistrer, puis l'effacer ou le corriger)
            stored_turn = turn or uuid.uuid4().hex[:12]
            print(f"\n📥 [ASSISTANT {sid}] Nouveau tour (texte: « {text or ''} », audio: {len(audio_wav) if audio_wav else 0} octets)")
            reply = Reply(sid, transcript=(text or "").strip(), turn=stored_turn)
            llm_audio = None

            if audio_wav is not None:
                # Un agent externe ne reçoit que du texte : l'enregistrement est transcrit
                if self.audio_to_llm() and self._current_agent(session) is None:
                    llm_audio = audio_wav
                else:
                    try:
                        stt = self.fallback_stt if self.stt.passthrough else self.stt
                        reply.transcript = stt.transcribe(audio_wav)
                        timer.mark("stt")
                    except Exception as e:
                        emit("error", sid, message=f"Erreur de transcription : {e}")
                        return reply
                    emit("transcript", sid, text=reply.transcript)
                    print(f"🎙️ [STT {sid}] Transcription : « {reply.transcript} »")

            if not reply.transcript and llm_audio is None and not images:
                emit("response", sid, text="", tools=[])
                return reply

            # « Au revoir », « c'est tout »... : fin immédiate, sans solliciter le LLM
            s = self.settings
            if reply.transcript and matches_phrase(reply.transcript, s.CONVERSATION_END_PHRASES, s.CONVERSATION_END_FILLERS):
                reply.end_conversation = True
                if s.AGENTS_LEAVE_ON_SLEEP:
                    self.set_agent(sid, None)
                emit("response", sid, text="", tools=[], end_conversation=True)
                return reply

            speaker = _Speaker(on_sentence, timer=timer)
            # Agent externe relié, ou demande de mise en relation (« passe-moi Hermes ») : le LLM n'est pas appelé
            if self._route_to_agent(session, reply, emit, speaker, images):
                self._finish_speech(sid, reply, speaker, synthesize, emit)
                return reply

            # Modèle sans vision : l'utilisateur est prévenu, seul le texte (ou la voix) est traité
            if images and not self.images_to_llm():
                warning = Template(s.IMAGES_NO_VISION_MESSAGE).safe_substitute(MODEL=self.llm.model)
                print(f"🖼️ [ASSISTANT {sid}] {warning}")
                images = []
                if not reply.transcript and llm_audio is None:
                    # Image seule : l'alerte est la réponse (affichée et dite), le modèle n'est pas appelé
                    reply.text = warning
                    emit("response", sid, text=warning, tools=[])
                    self._finish_speech(sid, reply, speaker, synthesize, emit)
                    return reply
                emit("warning", sid, message=warning, kind="no_vision")

            splitter = SentenceSplitter(self.settings.TTS_STREAM_MIN_CHARS) if on_sentence else None
            spoken = speaker.spoken
            say = speaker.say

            def on_tool(tool_info: dict):
                emit("tool", sid, **tool_info)
                self._show_image(sid, tool_info, reply, emit)

            def on_token(token: str):
                timer.mark("first_token")
                if session.cancel.is_set():
                    raise ResponseInterrupted()
                emit("token", sid, text=token)
                if splitter:
                    for sentence in splitter.feed(token):
                        say(sentence)

            # Souvenirs du compte utiles à cette demande (en audio direct, faute de texte : les plus récents)
            session.conversation.memory_prompt = self.memory.prompt_for(session.user, reply.transcript)
            raw = session.conversation.ask(
                prompt=reply.transcript or None,
                audio_bytes=llm_audio,
                images=images or None,
                on_token=on_token,
                on_tool=lambda r: on_tool(_tool_summary(r)),
                turn=stored_turn,
            )
            timer.mark("llm")
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
                    on_tool(tool_info)
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

            exchange = [m for m in conversation.older + conversation.history if m.get("turn") == stored_turn]
            self.history.append(session.user, session.conversation_id, exchange)
            self._archive_exchange(session, exchange)
            if splitter:
                for sentence in splitter.flush():
                    say(sentence)

            reply.end_conversation = _asks_to_sleep(raw, reply.tools)
            print(f"📤 [ASSISTANT {sid}] Réponse : « {reply.text} » ({len(reply.tools)} outil(s))")
            emit("response", sid, text=reply.text, tools=reply.tools, end_conversation=reply.end_conversation)

            # Rien n'a été prononcé en direct (réponse non streamée, message d'erreur...) : on dit le texte final
            if on_sentence and not spoken and reply.text:
                say(reply.text)

            # Le LLM a choisi l'outil « agent » : la conversation passe à l'agent, qui s'annonce dans sa voix
            requested = _requested_agent(raw, reply.tools)
            if requested is not None and not reply.end_conversation:
                agent = self.agents.get(requested)
                if agent is not None and self.agents_allowed(session.user):
                    try:
                        self.set_agent(sid, agent.name)
                        announce = Template(s.AGENTS_SWITCH_MESSAGE).safe_substitute(AGENT=agent.label)
                    except ValueError as e:   # agent non installé : l'assistant garde la main
                        announce = str(e)
                    say(announce)
                    reply.text = f"{reply.text} {announce}".strip()

            self._finish_speech(sid, reply, speaker, synthesize, emit, live=False)
            return reply

    def _show_image(self, sid: str, tool_info: dict, reply: Reply, emit):
        """Outil « show_image » exécuté : l'image (relue et revérifiée) part vers le client."""
        path = _shown_image(tool_info)
        # L'action a déjà refusé le fichier (hors des dossiers permis...) : le LLM en est informé par sa sortie
        if path is None or str(tool_info.get("output", "")).startswith("Échec"):
            return
        try:
            image, shown = load_image(path, self.settings)
        except (ImageError, OSError) as e:
            emit("error", sid, message=f"Image non affichée : {e}")
            return
        data = image.public(path=shown)
        reply.images.append(data)
        print(f"🖼️ [ASSISTANT {sid}] Image montrée : {shown} ({len(image.data)} octets)")
        emit("image", sid, **data)

    def _finish_speech(self, sid: str, reply: Reply, speaker: _Speaker, synthesize: bool, emit, live: bool = True):
        """Fin d'un tour : dit le texte s'il n'a pas été prononcé au fil de l'eau (`live`), puis synthèse en un bloc."""
        if live and speaker.on_sentence and not speaker.spoken and reply.text:
            speaker.say(strip_markdown(reply.text))
        if synthesize and reply.text:
            try:
                samples, sample_rate = self.tts.synthesize(strip_markdown(reply.text), voice=self.session_voice(sid))
                if len(samples):
                    reply.audio_wav = to_wav_bytes(samples, sample_rate)
                if speaker.timer:
                    speaker.timer.mark("tts")
            except Exception as e:
                emit("error", sid, message=f"Erreur de synthèse vocale : {e}")

    def _route_to_agent(self, session: Session, reply: Reply, emit, speaker: _Speaker, images: list[Image] = ()) -> bool:
        """Traite le tour sans LLM quand un agent est relié ou demandé. False : l'assistant répond normalement."""
        s = self.settings
        sid = session.id
        text = reply.transcript
        current = self._current_agent(session)
        agents = self.agents.all()
        switch = detect_switch(text, agents, s) if text and agents else None
        if current is None and (switch is None or switch.target == ASSISTANT):
            return False

        def answer(message: str, **extra):
            reply.text = message
            emit("response", sid, text=message, tools=[], **extra)
            speaker.say(message)

        if current is not None and (
                (switch is not None and switch.target == ASSISTANT)
                or (text and matches_phrase(text, s.AGENTS_RETURN_PHRASES, s.CONVERSATION_END_FILLERS))):
            self.set_agent(sid, None)
            answer(s.AGENTS_RETURN_MESSAGE)
            return True

        message = text
        if images:
            # Un agent ne reçoit que du texte : les images sont copiées sur le disque et il reçoit leur chemin
            paths = ", ".join(str(save_upload(img, s)) for img in images)
            note = f"[Image(s) jointe(s) par l'utilisateur : {paths}]"
            message = f"{message}\n{note}".strip()
            if switch is not None and switch.target != ASSISTANT:
                # « Passe-moi Hermes » + image : l'image lui est transmise même sans autre demande
                switch = type(switch)(switch.target, f"{switch.rest or text}\n{note}".strip())
        if switch is not None and switch.target != ASSISTANT:
            target = self.agents.get(switch.target)
            if not self.agents_allowed(session.user):
                answer(Template(s.AGENTS_DENIED_MESSAGE).safe_substitute(AGENT=target.label))
                return True
            if current is None or current.name != target.name or not switch.rest:
                try:
                    self.set_agent(sid, target.name)
                except ValueError as e:   # agent non installé : l'assistant garde (ou reprend) la main
                    self.set_agent(sid, None)
                    answer(str(e), error=True)
                    return True
                speaker.say(Template(s.AGENTS_SWITCH_MESSAGE).safe_substitute(AGENT=target.label))
            if not switch.rest:
                reply.text = Template(s.AGENTS_SWITCH_MESSAGE).safe_substitute(AGENT=target.label)
                emit("response", sid, text=reply.text, tools=[], agent=target.name)
                return True
            current, message = target, switch.rest
        if not message:
            emit("response", sid, text="", tools=[], agent=current.name)
            return True
        self._agent_turn(session, current, message, reply, emit, speaker)
        return True

    def _agent_turn(self, session: Session, agent: AgentSpec, message: str, reply: Reply, emit, speaker: _Speaker):
        """Transmet le message à l'agent et relaie sa réponse au fil de l'eau (texte et voix)."""
        sid = session.id
        splitter = SentenceSplitter(self.settings.TTS_STREAM_MIN_CHARS) if speaker.on_sentence else None

        def on_text(fragment: str):
            if session.cancel.is_set():
                raise ResponseInterrupted()
            emit("token", sid, text=fragment)
            if splitter:
                for sentence in splitter.feed(fragment):
                    speaker.say(strip_markdown(sentence))

        try:
            result = AgentRunner(self.settings).run(agent, message, session.agent_sessions.get(agent.name, ""),
                                                    on_text=on_text, cancel=session.cancel)
        except (AgentCancelled, ResponseInterrupted):
            reply.interrupted = True
            emit("interrupted", sid)
            return
        except AgentError as e:
            # L'agent ne répond pas : la conversation revient à l'assistant (sinon chaque phrase suivante échouerait)
            print(f"⚠️ [AGENTS] {agent.label} : {e} — retour à l'assistant")
            self.set_agent(sid, None)
            reply.text = self.agent_error(agent, e)
            emit("response", sid, text=reply.text, tools=[], error=True)
            speaker.say(reply.text)
            return
        if result.session:
            session.agent_sessions[agent.name] = result.session
        if splitter:
            for sentence in splitter.flush():
                speaker.say(strip_markdown(sentence))
        reply.text = result.text
        print(f"📤 [AGENTS {sid}] {agent.label} : « {reply.text[:200]} »")
        emit("response", sid, text=reply.text, tools=[], agent=agent.name)


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
