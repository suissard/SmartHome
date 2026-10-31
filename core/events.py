"""
Bus d'événements de l'assistant : les composants publient ce qui se passe (transcription, fragments de
réponse, outils, réponse finale...) et les abonnés (console locale, clients WebSocket...) réagissent.

Types d'événements émis par AssistantCore :
- "transcript"       : {"text"}                                   texte reconnu dans l'audio reçu
- "token"            : {"text"}                                   fragment de réponse (streaming)
- "tool"             : {"name", "arguments", "executed", "output"} outil exécuté ou refusé
- "confirm_request"  : {"id", "question"}                         confirmation demandée (session distante)
- "response"         : {"text", "tools"}                          réponse finale épurée pour la voix
- "error"            : {"message"}
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Event:
    type: str
    session_id: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"type": self.type, "session": self.session_id, **self.data}


Subscriber = Callable[[Event], None]


class EventBus:
    """Diffusion synchrone et thread-safe ; un abonné peut filtrer sur une session."""

    def __init__(self):
        self._subscribers: list[tuple[Optional[str], Subscriber]] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Subscriber, session_id: Optional[str] = None) -> Callable[[], None]:
        """Abonne `callback` (à toutes les sessions si session_id est None). Retourne la fonction de désabonnement."""
        entry = (session_id, callback)
        with self._lock:
            self._subscribers.append(entry)

        def unsubscribe():
            with self._lock:
                if entry in self._subscribers:
                    self._subscribers.remove(entry)
        return unsubscribe

    def emit(self, event_type: str, session_id: str, **data) -> Event:
        event = Event(event_type, session_id, data)
        with self._lock:
            targets = [cb for sid, cb in self._subscribers if sid is None or sid == session_id]
        for callback in targets:
            try:
                callback(event)
            except Exception as e:
                print(f"⚠️ [EVENTS] Abonné en erreur sur '{event_type}' : {e}")
        return event


if __name__ == "__main__":
    bus = EventBus()
    bus.subscribe(lambda e: print(f"  • tous     : {e.to_dict()}"))
    bus.subscribe(lambda e: print(f"  • session a: {e.to_dict()}"), session_id="a")
    print("🧪 [DEBUG] Émission de deux événements :")
    bus.emit("token", "a", text="Bonjour")
    bus.emit("token", "b", text="Salut")
