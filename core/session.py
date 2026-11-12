"""
Structures de session, réponse et utilitaires audio/outils associés à un tour d'AssistantCore.
"""

import io
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.history import new_conversation_id
from core.metrics import TurnTimer
from core.tools import ToolResult
from core.users import User
from llm.llm import Conversation


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
    transcript: str = ""            # ce que l'utilisateur a dit (ou écrit)
    text: str = ""                  # réponse épurée, prête pour la voix
    tools: list[dict] = field(default_factory=list)
    audio_wav: Optional[bytes] = None
    interrupted: bool = False       # génération abandonnée (barge-in, bouton stop)
    end_conversation: bool = False  # l'utilisateur a pris congé : retour en veille (phrase de fin ou outil « sleep »)
    images: list[dict] = field(default_factory=list)  # images montrées par l'assistant (outil show_image)
    turn: str = ""                  # numéro de l'échange dans l'historique
    timings: dict = field(default_factory=dict)  # latence par étape, en ms (core/metrics.py)


@dataclass
class Session:
    id: str
    conversation: Conversation
    persistent: bool = False        # jamais expirée (session locale)
    user: Optional[User] = None     # propriétaire (None : session interne, sans restriction d'outils)
    conversation_id: str = field(default_factory=new_conversation_id)  # conversation enregistrée (historique)
    restored: bool = False          # dernière conversation du compte déjà rechargée
    last_seen: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    agent: Optional[str] = None     # agent externe relié à la conversation (None : l'assistant répond)
    agent_sessions: dict[str, str] = field(default_factory=dict)  # identifiant de session de chaque agent
    clients: int = 0                # clients connectés (WebSocket) : une session suivie n'expire jamais
    _confirms: list = field(default_factory=list, repr=False)  # pile de callbacks de confirmation par client attaché


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
