"""
Historique persistant des conversations des comptes (PWA), dans la collection PocketBase POCKETBASE_MESSAGES_COLLECTION.

Projet local : tout est conservé, sans limite de durée. Chaque compte ne lit, n'écrit et n'efface que ses propres
messages (règles de la collection, appliquées avec le jeton du compte) ; l'administrateur de PocketBase voit tout.

- À la connexion, la dernière conversation du compte est rechargée (contexte du LLM et affichage de la PWA).
- Chaque échange terminé est ajouté ; supprimer, relancer ou corriger un message est répercuté.
- « Nouvelle conversation » ouvre une nouvelle conversation : l'ancienne reste enregistrée.

Les écritures passent par un seul fil d'exécution (ordre conservé, réponse jamais retardée) ;
un échec est affiché sans interrompre l'assistant.
"""

import re
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings
from core.users import AuthError, DirectoryUnavailable, User, pb_request

# Identifiants acceptés dans un filtre PocketBase (les numéros d'échange viennent du client)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PAGE_SIZE = 500


def new_conversation_id() -> str:
    return uuid.uuid4().hex


def _record_id(user: User) -> str:
    return user.id.removeprefix("pb_")


class HistoryStore:
    """Historique dans PocketBase (désactivé sans annuaire PocketBase : rien n'est conservé)."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.enabled = self.settings.AUTH_PROVIDER in ("pocketbase", "pb")
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history") if self.enabled else None
        self._seq = 0
        self._seq_lock = threading.Lock()

    def applies(self, user: Optional[User]) -> bool:
        return self.enabled and user is not None and user.has_profile and bool(user.token)

    # ---- Requêtes ----
    def _request(self, user: User, path: str = "", **kwargs) -> dict:
        collection = self.settings.POCKETBASE_MESSAGES_COLLECTION
        return pb_request(self.settings, f"{collection}/records{path}", token=user.token, **kwargs)

    def _list(self, user: User, filter_: str, sort: str = "seq", limit: Optional[int] = None) -> list[dict]:
        items, page = [], 1
        while True:
            data = self._request(user, method="GET", query={
                "filter": filter_, "sort": sort, "page": page, "perPage": min(limit or PAGE_SIZE, PAGE_SIZE),
                "skipTotal": "true"})
            batch = data.get("items") or []
            items += batch
            if len(batch) < PAGE_SIZE or (limit and len(items) >= limit):
                return items[:limit] if limit else items
            page += 1

    def _next_seq(self) -> int:
        # Croissant même pour deux messages créés dans la même milliseconde
        with self._seq_lock:
            self._seq = max(self._seq + 1, time.time_ns() // 1000)
            return self._seq

    # ---- Lecture (bloquante, à appeler hors de la boucle asyncio) ----
    def load_latest(self, user: User) -> tuple[Optional[str], list[dict]]:
        """Dernière conversation du compte : (identifiant, messages [{role, content, turn}] dans l'ordre).
        (None, []) si le compte n'a encore rien dit ou si PocketBase ne répond pas."""
        if not self.applies(user):
            return None, []
        try:
            owner = f'user = "{_record_id(user)}"'
            last = self._list(user, owner, sort="-seq", limit=1)
            if not last:
                return None, []
            conversation = last[0]["conversation"]
            if not _SAFE_ID.match(conversation):
                return None, []
            records = self._list(user, f'{owner} && conversation = "{conversation}"')
        except (AuthError, DirectoryUnavailable) as e:
            print(f"⚠️ [HISTORIQUE] Lecture impossible pour {user.name} : {e}")
            return None, []
        messages = [{"role": r["role"], "content": r.get("content") or "", **({"turn": r["turn"]} if r.get("turn") else {})}
                    for r in records if r.get("role") in ("user", "assistant")]
        return conversation, messages

    # ---- Écritures (en arrière-plan, dans l'ordre) ----
    def _submit(self, label: str, user: User, fn, *args) -> Optional[Future]:
        if not self.applies(user):
            return None

        def run():
            try:
                fn(user, *args)
            except (AuthError, DirectoryUnavailable) as e:
                print(f"⚠️ [HISTORIQUE] {label} non enregistré pour {user.name} : {e}")
        return self._writer.submit(run)

    def append(self, user: User, conversation: str, messages: Iterable[dict]) -> Optional[Future]:
        """Ajoute les messages d'un échange terminé ({role, content, turn})."""
        if not self.applies(user):
            return None
        rows = [{"user": _record_id(user), "conversation": conversation, "turn": m.get("turn", ""),
                 "role": m["role"], "content": m.get("content") or "", "seq": self._next_seq()}
                for m in messages if m.get("role") in ("user", "assistant")]

        def write(user: User):
            for row in rows:
                self._request(user, body=row)
        return self._submit("Échange", user, write)

    def _turn_filter(self, user: User, conversation: str, turns: Iterable[str], role: Optional[str]) -> Optional[str]:
        turns = [t for t in turns if t and _SAFE_ID.match(t)]
        if not turns or not _SAFE_ID.match(conversation):
            return None
        filter_ = (f'user = "{_record_id(user)}" && conversation = "{conversation}" && ('
                   + " || ".join(f'turn = "{t}"' for t in turns) + ")")
        if role in ("user", "assistant"):
            filter_ += f' && role = "{role}"'
        return filter_

    def forget(self, user: User, conversation: str, turns: Iterable[str], role: Optional[str] = None) -> Optional[Future]:
        """Efface les messages de ces échanges (seulement ceux de `role` s'il est précisé)."""
        if not self.applies(user):
            return None
        filter_ = self._turn_filter(user, conversation, list(turns), role)
        if filter_ is None:
            return None

        def delete(user: User):
            for record in self._list(user, filter_):
                self._request(user, f"/{record['id']}", method="DELETE", not_found_is_refusal=True)
        return self._submit("Effacement", user, delete)

    def edit_answer(self, user: User, conversation: str, turn: str, text: str) -> Optional[Future]:
        """Remplace la réponse de l'assistant pour cet échange."""
        if not self.applies(user):
            return None
        filter_ = self._turn_filter(user, conversation, [turn], "assistant")
        if filter_ is None:
            return None

        def edit(user: User):
            for record in self._list(user, filter_):
                self._request(user, f"/{record['id']}", body={"content": text}, method="PATCH",
                              not_found_is_refusal=True)
        return self._submit("Correction", user, edit)

    def flush(self, timeout: float = 10.0):
        """Attend la fin des écritures en cours (arrêt, tests)."""
        if self._writer:
            self._writer.submit(lambda: None).result(timeout)


if __name__ == "__main__":
    import getpass
    from core.users import create_directory

    s = get_settings()
    store = HistoryStore(s)
    print(f"🧪 [DEBUG] Historique : {'PocketBase, collection ' + s.POCKETBASE_MESSAGES_COLLECTION if store.enabled else 'désactivé (AUTH_PROVIDER)'}")
    if store.enabled:
        try:
            user = create_directory(s).login(input("Identifiant (email) : ").strip(), getpass.getpass("Mot de passe : "))
            conversation, messages = store.load_latest(user)
            print(f"Dernière conversation : {conversation or 'aucune'} ({len(messages)} message(s))")
            for m in messages:
                print(f"  {'🧑' if m['role'] == 'user' else '🤖'} {m['content'][:100]}")
        except (AuthError, DirectoryUnavailable) as e:
            print(f"❌ {e}")
        except (KeyboardInterrupt, EOFError):
            pass
