"""
Archive des conversations : données d'entraînement conservées indéfiniment, dans une base SQLite locale (ARCHIVE_DB_PATH).

Tout échange terminé y est ajouté, quelle que soit son origine : micro de l'ordinateur (« Foyer »), PWA (comptes ou
jeton maître), POST /api/ask. Rien n'en est jamais retiré :
- supprimer un message ou une conversation dans la PWA le masque (`deleted_at`) ;
- corriger une réponse ajoute une nouvelle version, l'ancienne reste (`superseded_by`).
Les notes de satisfaction (-2 à +2, commentaire facultatif) sont rangées avec elles, une par personne et par réponse.

L'archive sert aussi l'affichage des conversations du micro dans la PWA (ARCHIVE_HOUSEHOLD_ROLES) : la voix n'étant pas
identifiée, elles appartiennent au foyer. Export pour l'entraînement : `python core/archive.py export fichier.jsonl`.

Bibliothèque standard uniquement ; une connexion par fil d'exécution, écritures sérialisées par un verrou.
"""

import json
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

# Origine d'une conversation (colonne « source »)
SOURCE_LOCAL = "local"   # micro de l'ordinateur
SOURCE_PWA = "pwa"       # passerelle WebSocket (comptes, jeton maître)
SOURCE_API = "api"       # POST /api/ask, appels internes

RATING_MIN, RATING_MAX = -2, 2

# Dossier de référence d'un ARCHIVE_DB_PATH relatif (les tests le redirigent vers un dossier temporaire)
ARCHIVE_ROOT = _ROOT_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation  TEXT NOT NULL,
    turn          TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL,
    content       TEXT NOT NULL DEFAULT '',
    tools         TEXT,
    source        TEXT NOT NULL,
    session       TEXT NOT NULL DEFAULT '',
    user_id       TEXT NOT NULL DEFAULT '',
    user_name     TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    deleted_at    TEXT,
    superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation, id);
CREATE INDEX IF NOT EXISTS idx_messages_owner ON messages (source, user_id, id);
CREATE TABLE IF NOT EXISTS feedback (
    conversation  TEXT NOT NULL,
    turn          TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    user_name     TEXT NOT NULL DEFAULT '',
    rating        INTEGER NOT NULL CHECK (rating BETWEEN -2 AND 2),
    comment       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (conversation, turn, user_id)
);
CREATE TABLE IF NOT EXISTS timings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation  TEXT NOT NULL DEFAULT '',
    turn          TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    timings       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timings_created ON timings (created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clean_rating(value) -> Optional[int]:
    """Note reçue d'un client : entier de -2 à +2 (None si invalide ; un booléen n'est pas une note)."""
    if isinstance(value, bool):
        return None
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return None
    return rating if RATING_MIN <= rating <= RATING_MAX and rating == value else None


class ConversationArchive:
    """Archive SQLite (désactivée par ARCHIVE_ENABLED=false : rien n'est écrit, rien n'est lu)."""

    def __init__(self, settings: Optional[Settings] = None, path: Optional[Path] = None):
        self.settings = settings or get_settings()
        self.enabled = bool(self.settings.ARCHIVE_ENABLED)
        raw = Path(path or self.settings.ARCHIVE_DB_PATH)
        self.path = raw if raw.is_absolute() else ARCHIVE_ROOT / raw
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._ready = False

    # ---- Connexion ----
    def _db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            if not self._ready:
                with self._write_lock:
                    conn.executescript(_SCHEMA)
                self._ready = True
            self._local.conn = conn
        return conn

    def close(self):
        """Ferme la connexion de ce fil d'exécution (arrêt, tests)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _write(self, sql_fn) -> bool:
        """Exécute une écriture ; un échec est affiché sans jamais interrompre l'assistant."""
        if not self.enabled:
            return False
        try:
            with self._write_lock:
                conn = self._db()
                with conn:
                    sql_fn(conn)
            return True
        except (sqlite3.Error, OSError) as e:
            print(f"⚠️ [ARCHIVE] Écriture impossible ({self.path}) : {e}")
            return False

    def _read(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        if not self.enabled:
            return []
        try:
            return self._db().execute(sql, tuple(params)).fetchall()
        except (sqlite3.Error, OSError) as e:
            print(f"⚠️ [ARCHIVE] Lecture impossible ({self.path}) : {e}")
            return []

    # ---- Écritures ----
    def append(self, conversation: str, messages: Iterable[dict], source: str, session: str = "",
               user_id: str = "", user_name: str = "", model: str = "") -> bool:
        """Ajoute les messages d'un échange terminé ({role, content, turn, tools})."""
        rows = [m for m in messages if m.get("role") in ("user", "assistant")]
        if not rows or not conversation:
            return False
        now = _now()

        def write(conn):
            conn.executemany(
                "INSERT INTO messages (conversation, turn, role, content, tools, source, session, user_id, user_name,"
                " model, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(conversation, m.get("turn") or "", m["role"], m.get("content") or "",
                  json.dumps(m["tools"], ensure_ascii=False, default=str) if m.get("tools") else None,
                  source, session, user_id, user_name, model if m["role"] == "assistant" else "", now)
                 for m in rows])
        return self._write(write)

    def add_timings(self, conversation: str, turn: str, source: str, model: str, timings: dict) -> bool:
        """Latence d'un tour, étape par étape (voir core/metrics.py)."""
        if not timings:
            return False
        payload = json.dumps(timings)
        return self._write(lambda conn: conn.execute(
            "INSERT INTO timings (conversation, turn, source, model, timings, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation, turn, source, model, payload, _now())))

    def timings_since(self, days: float = 7) -> list[dict]:
        """Mesures des `days` derniers jours : [{conversation, turn, model, source, timings: {étape: ms}, at}]."""
        since = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat(timespec="milliseconds")
        return [{"conversation": r["conversation"], "turn": r["turn"], "model": r["model"], "source": r["source"], "timings": json.loads(r["timings"]), "at": r["created_at"]}
                for r in self._read("SELECT * FROM timings WHERE created_at >= ? ORDER BY id", (since,))]

    def hide_turns(self, conversation: str, turns: Iterable[str], role: Optional[str] = None) -> bool:
        """Masque les messages de ces échanges (suppression dans la PWA) : ils restent dans l'archive."""
        turns = [t for t in turns if t]
        if not turns:
            return False
        marks = ",".join("?" * len(turns))
        sql = f"UPDATE messages SET deleted_at = ? WHERE conversation = ? AND deleted_at IS NULL AND turn IN ({marks})"
        params = [_now(), conversation, *turns]
        if role in ("user", "assistant"):
            sql += " AND role = ?"
            params.append(role)
        return self._write(lambda conn: conn.execute(sql, params))

    def hide_conversation(self, conversation: str, user_id: str) -> bool:
        """Masque une conversation supprimée par son propriétaire (jamais effacée)."""
        return self._write(lambda conn: conn.execute(
            "UPDATE messages SET deleted_at = ? WHERE conversation = ? AND user_id = ? AND deleted_at IS NULL",
            (_now(), conversation, user_id)))

    def edit_answer(self, conversation: str, turn: str, text: str) -> bool:
        """Nouvelle version de la réponse d'un échange ; l'ancienne reste, marquée comme remplacée."""
        def write(conn):
            old = conn.execute(
                "SELECT * FROM messages WHERE conversation = ? AND turn = ? AND role = 'assistant'"
                " AND deleted_at IS NULL AND superseded_by IS NULL ORDER BY id DESC LIMIT 1",
                (conversation, turn)).fetchone()
            if old is None:
                return
            cur = conn.execute(
                "INSERT INTO messages (conversation, turn, role, content, tools, source, session, user_id, user_name,"
                " model, created_at) VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, 'edit', ?)",
                (conversation, turn, text, old["tools"], old["source"], old["session"], old["user_id"],
                 old["user_name"], _now()))
            conn.execute("UPDATE messages SET superseded_by = ? WHERE id = ?", (cur.lastrowid, old["id"]))
        return self._write(write)

    def set_feedback(self, conversation: str, turn: str, user_id: str, user_name: str, rating: int,
                     comment: str = "") -> bool:
        """Note (-2 à +2) et commentaire d'une personne sur une réponse ; une nouvelle note remplace la précédente."""
        now = _now()
        return self._write(lambda conn: conn.execute(
            "INSERT INTO feedback (conversation, turn, user_id, user_name, rating, comment, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (conversation, turn, user_id) DO UPDATE SET"
            " rating = excluded.rating, comment = excluded.comment, user_name = excluded.user_name,"
            " updated_at = excluded.updated_at",
            (conversation, turn, user_id, user_name, rating, comment, now, now)))

    # ---- Lectures ----
    def has_turn(self, conversation: str, turn: str) -> Optional[sqlite3.Row]:
        """Réponse archivée de cet échange (source et propriétaire, pour vérifier qui peut la noter)."""
        rows = self._read("SELECT source, user_id FROM messages WHERE conversation = ? AND turn = ? AND role = 'assistant'"
                          " LIMIT 1", (conversation, turn))
        return rows[0] if rows else None

    def feedback_for(self, conversation: str, user_id: str) -> dict[str, dict]:
        """Notes données par cette personne dans une conversation : {turn: {rating, comment}}."""
        return {r["turn"]: {"rating": r["rating"], "comment": r["comment"]}
                for r in self._read("SELECT turn, rating, comment FROM feedback WHERE conversation = ? AND user_id = ?",
                                    (conversation, user_id))}

    def _visible(self, conversation: str) -> list[sqlite3.Row]:
        return self._read("SELECT * FROM messages WHERE conversation = ? AND deleted_at IS NULL AND superseded_by IS NULL"
                          " ORDER BY id", (conversation,))

    def load_conversation(self, conversation: str, source: str, user_id: str = "") -> list[dict]:
        """Messages visibles d'une conversation de cette origine (et de ce propriétaire, si précisé)."""
        rows = [r for r in self._visible(conversation)
                if r["source"] == source and (not user_id or r["user_id"] == user_id)]
        return [{"role": r["role"], "content": r["content"],
                 **({"turn": r["turn"]} if r["turn"] else {}),
                 **({"tools": json.loads(r["tools"])} if r["tools"] else {})} for r in rows]

    def list_conversations(self, source: str, user_id: str = "", limit: int = 300) -> list[dict]:
        """Conversations d'une origine, les plus récentes d'abord, au format du tiroir de la PWA."""
        params: list = [source]
        owner = ""
        if user_id:
            owner = " AND user_id = ?"
            params.append(user_id)
        heads = self._read(
            "SELECT conversation, MIN(created_at) AS created, MAX(created_at) AS updated, COUNT(*) AS n, MAX(id) AS last"
            f" FROM messages WHERE source = ?{owner} AND deleted_at IS NULL AND superseded_by IS NULL"
            " GROUP BY conversation ORDER BY last DESC LIMIT ?", (*params, limit))
        if not heads:
            return []
        conv_ids = [head["conversation"] for head in heads]
        placeholders = ",".join("?" for _ in conv_ids)
        all_rows = self._read(
            "SELECT id, conversation, role, content, tools FROM messages"
            f" WHERE conversation IN ({placeholders}) AND deleted_at IS NULL AND superseded_by IS NULL"
            " ORDER BY conversation, id",
            conv_ids,
        )
        by_conv: dict[str, list[sqlite3.Row]] = {}
        for r in all_rows:
            by_conv.setdefault(r["conversation"], []).append(r)
        result = []
        for head in heads:
            rows = by_conv.get(head["conversation"], [])
            first_user = next((r["content"] for r in rows if r["role"] == "user" and r["content"].strip()), "")
            title = first_user.strip()
            tools: list[str] = []
            for r in rows:
                for t in json.loads(r["tools"]) if r["tools"] else []:
                    name = t.get("name") if isinstance(t, dict) else str(t)
                    if name and name not in tools:
                        tools.append(name)
            result.append({
                "id": head["conversation"],
                "title": (title[:57] + "…") if len(title) > 60 else (title or "Conversation au micro"),
                "last_message": rows[-1]["content"] if rows else "",
                "created": head["created"],
                "updated": head["updated"],
                "message_count": head["n"],
                "tools": tools,
                "source": source,
            })
        return result

    def stats(self) -> dict:
        rows = self._read("SELECT (SELECT COUNT(*) FROM messages) AS messages,"
                          " (SELECT COUNT(DISTINCT conversation) FROM messages) AS conversations,"
                          " (SELECT COUNT(*) FROM feedback) AS feedback")
        return dict(rows[0]) if rows else {"messages": 0, "conversations": 0, "feedback": 0}

    def export_jsonl(self, out, include_hidden: bool = True) -> int:
        """Une ligne JSON par conversation (messages dans l'ordre, versions corrigées et masquées comprises si
        `include_hidden`, chaque réponse avec ses notes). Retourne le nombre de conversations écrites."""
        feedback: dict[tuple, list] = {}
        for r in self._read("SELECT * FROM feedback ORDER BY updated_at"):
            feedback.setdefault((r["conversation"], r["turn"]), []).append(
                {"rating": r["rating"], "comment": r["comment"], "user": r["user_name"] or r["user_id"],
                 "at": r["updated_at"]})
        rows = self._read("SELECT * FROM messages ORDER BY conversation, id")
        count, current, messages = 0, None, []

        def flush():
            nonlocal count
            if current is not None and messages:
                out.write(json.dumps({"conversation": current, "messages": messages}, ensure_ascii=False) + "\n")
                count += 1

        for r in rows:
            if r["conversation"] != current:
                flush()
                current, messages = r["conversation"], []
            hidden = r["deleted_at"] is not None or r["superseded_by"] is not None
            if hidden and not include_hidden:
                continue
            entry = {"role": r["role"], "content": r["content"], "turn": r["turn"], "source": r["source"],
                     "user": r["user_name"] or r["user_id"], "at": r["created_at"]}
            if r["model"]:
                entry["model"] = r["model"]
            if r["tools"]:
                entry["tools"] = json.loads(r["tools"])
            if r["deleted_at"]:
                entry["deleted_at"] = r["deleted_at"]
            if r["superseded_by"] is not None:
                entry["superseded"] = True
            if r["role"] == "assistant" and (r["conversation"], r["turn"]) in feedback and r["superseded_by"] is None:
                entry["feedback"] = feedback[(r["conversation"], r["turn"])]
            messages.append(entry)
        flush()
        return count


if __name__ == "__main__":
    archive = ConversationArchive()
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(f"🧪 [DEBUG] Archive : {archive.path} ({'active' if archive.enabled else 'désactivée (ARCHIVE_ENABLED)'})")
    if command == "export":
        target = sys.argv[2] if len(sys.argv) > 2 else "-"
        visible_only = "--visible" in sys.argv
        start = time.monotonic()
        if target == "-":
            n = archive.export_jsonl(sys.stdout, include_hidden=not visible_only)
        else:
            with open(target, "w", encoding="utf-8") as f:
                n = archive.export_jsonl(f, include_hidden=not visible_only)
        print(f"✅ {n} conversation(s) exportée(s) vers {target} en {time.monotonic() - start:.2f} s", file=sys.stderr)
    else:
        print(f"  • Contenu : {archive.stats()}")
        for conv in archive.list_conversations(SOURCE_LOCAL, limit=5):
            print(f"  🏠 {conv['updated']} — {conv['title']} ({conv['message_count']} message(s))")
        print("  Export : python core/archive.py export conversations.jsonl [--visible]")
