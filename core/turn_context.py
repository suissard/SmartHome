"""
Contexte du tour en cours : la session (et donc le compte) pour laquelle un outil s'exécute.

`AssistantCore._respond()` le pose pendant tout le tour ; les outils appelés par le LLM (function calling, exécutés
dans le même fil) le lisent pour savoir à qui appartient un rappel ou un souvenir. Hors d'un tour (serveur MCP,
tests), `current_session()` vaut None.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

_CURRENT_SESSION: ContextVar[Optional[Any]] = ContextVar("smarthome_current_session", default=None)


def current_session() -> Optional[Any]:
    return _CURRENT_SESSION.get()


def current_user() -> Optional[Any]:
    session = current_session()
    return getattr(session, "user", None) if session is not None else None


@contextmanager
def session_context(session):
    token = _CURRENT_SESSION.set(session)
    try:
        yield session
    finally:
        _CURRENT_SESSION.reset(token)


if __name__ == "__main__":
    from types import SimpleNamespace
    print(f"🧪 [DEBUG] Hors tour : {current_session()}")
    with session_context(SimpleNamespace(id="demo", user=SimpleNamespace(name="Foyer"))):
        print(f"🧪 [DEBUG] Pendant le tour : session {current_session().id}, compte {current_user().name}")
    print(f"🧪 [DEBUG] Après : {current_session()}")
