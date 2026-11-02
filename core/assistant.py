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
from typing import Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import ENV_FILE, Settings, get_settings, set_settings
from core.events import EventBus
from core.sentences import SentenceSplitter, matches_phrase
from core.tools import ConfirmationHandler, ToolRegistry, ToolResult, build_tool_registry
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
            settings_store.save_to_env(new, changed, self.env_file)
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
    ) -> Session:
        """Retourne la session existante (en mettant à jour sa confirmation) ou en crée une nouvelle."""
        self._expire_sessions()
        with self._sessions_lock:
            sid = session_id or uuid.uuid4().hex[:12]
            session = self._sessions.get(sid)
            if session is None:
                conversation = Conversation(self.llm, self.settings, tools=self.tools, confirm=confirm)
                session = Session(sid, conversation, persistent=persistent)
                self._sessions[sid] = session
            elif confirm is not None:
                session.conversation.confirm = confirm
            session.last_seen = time.monotonic()
            return session

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

    # ---- Pipeline ----
    def respond(
        self,
        session_id: str,
        text: Optional[str] = None,
        audio_wav: Optional[bytes] = None,
        synthesize: bool = False,
        on_sentence: Optional[Callable[[str], None]] = None,
    ) -> Reply:
        """Traite une demande (texte ou enregistrement WAV) et retourne la réponse. Bloquant : à appeler
        depuis un thread pour un serveur asyncio. Les demandes d'une même session sont traitées une à une.
        `on_sentence` reçoit chaque phrase à prononcer dès qu'elle est complète (parole en streaming)."""
        session = self.open_session(session_id)
        emit = self.events.emit
        sid = session.id

        with session.lock:
            session.last_seen = time.monotonic()
            session.cancel.clear()
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
            )
            reply.tools = [_tool_summary(r) for r in session.conversation.last_tool_results]

            if session.cancel.is_set():
                reply.interrupted = True
                emit("interrupted", sid)
                return reply
            if splitter:
                for sentence in splitter.flush():
                    say(sentence)

            # Mode tags (ou tag égaré) : exécution des [ACTION] du texte et nettoyage pour la voix
            reply.text = raw
            if raw and self.settings.ACTIONS_ENABLED:
                from actions.manager import get_action_manager
                reply.text = get_action_manager().process_response(raw, confirm=session.conversation.confirm)

            reply.end_conversation = _asks_to_sleep(raw, reply.tools)
            emit("response", sid, text=reply.text, tools=reply.tools, end_conversation=reply.end_conversation)

            # Rien n'a été prononcé en direct (réponse non streamée, message d'erreur...) : on dit le texte final
            if on_sentence and not spoken and reply.text:
                say(reply.text)

            if synthesize and reply.text:
                try:
                    samples, sample_rate = self.tts.synthesize(reply.text)
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
