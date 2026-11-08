"""
Garde « voix distante » : quand quelqu'un parle à l'assistant par le micro d'un client distant (PWA du
téléphone), le micro de l'ordinateur entend la même voix. Il ne doit alors ni se déclencher sur le mot-clé
ni continuer d'écouter : la conversation se passe sur le téléphone, l'ordinateur reste (ou repasse) en veille.

Signaux (bus d'événements, sessions autres que la session locale) :
- "remote_listening" {"active": bool} : micro du client ouvert / fermé (message WS {"type": "listening"})
- "transcript"                        : audio reçu d'un client (tout client, même sans message "listening")
La garde reste active tant qu'un micro distant est ouvert, puis REMOTE_VOICE_HOLD secondes.
"""

import threading
import time
from typing import Callable, Optional

from core.events import Event, EventBus


class RemoteVoiceGuard:
    def __init__(self, bus: Optional[EventBus], local_session: str, hold: float = 3.0, enabled: bool = True,
                 clock: Callable[[], float] = time.monotonic):
        self.local_session = local_session
        self.hold = max(0.0, float(hold))
        self.enabled = enabled
        self._clock = clock
        self._lock = threading.Lock()
        self._open: set[str] = set()   # sessions dont le micro est ouvert
        self._until = 0.0
        self._unsubscribe = bus.subscribe(self.on_event) if bus is not None and enabled else None

    def on_event(self, event: Event):
        if event.session_id in (None, self.local_session):
            return
        if event.type == "remote_listening":
            with self._lock:
                if event.data.get("active", True):
                    self._open.add(event.session_id)
                else:
                    self._open.discard(event.session_id)
                self._until = self._clock() + self.hold
        elif event.type == "transcript":
            with self._lock:
                self._until = self._clock() + self.hold

    def active(self) -> bool:
        """Vrai si un client distant écoute (ou vient d'écouter) : le micro local doit rester en veille."""
        if not self.enabled:
            return False
        with self._lock:
            return bool(self._open) or self._clock() < self._until

    def close(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None


if __name__ == "__main__":
    bus = EventBus()
    guard = RemoteVoiceGuard(bus, "local", hold=0.5)
    print(f"🧪 [DEBUG] Au repos           : actif={guard.active()}")
    bus.emit("remote_listening", "pwa-1", active=True)
    print(f"🧪 [DEBUG] Micro du téléphone : actif={guard.active()}")
    bus.emit("remote_listening", "pwa-1", active=False)
    print(f"🧪 [DEBUG] Micro refermé      : actif={guard.active()} (encore {guard.hold}s)")
    time.sleep(0.6)
    print(f"🧪 [DEBUG] Après le délai     : actif={guard.active()}")
