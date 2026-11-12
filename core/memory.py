"""
Mémoire à long terme par compte (MEMORY_ENABLED) : ce que l'assistant doit retenir d'une conversation à l'autre.

- Outils `remember` (« retiens que ma fille s'appelle Léa »), `list_memories`, `forget_memory`
  (actions/modules/memory.py) ; la PWA liste et efface aussi les souvenirs de son compte (réglages).
- À chaque tour, `MemoryStore.prompt_for()` ajoute au prompt système les souvenirs utiles du compte : tous s'il en a
  peu (MEMORY_ALWAYS_INCLUDE, aucun calcul), sinon les MEMORY_RECALL_LIMIT plus proches de la demande.
- Proximité : embeddings locaux d'Ollama si MEMORY_EMBED_MODEL est installé (ex: nomic-embed-text), sinon mots
  communs (accents et mots vides ignorés). Un souvenir presque identique à un existant le remplace.

Chaque compte a ses souvenirs (le micro de l'ordinateur : ceux du foyer). Base SQLite locale (MEMORY_DB_PATH),
bibliothèque standard uniquement. Diagnostic : `python core/memory.py [compte] [question]`.
"""

import json
import math
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

# Dossier de référence d'un MEMORY_DB_PATH relatif (les tests le redirigent vers un dossier temporaire)
MEMORY_ROOT = _ROOT_DIR

_STOPWORDS = set("""
au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me meme mes moi mon ne nos notre
nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous est sont suis ai as a
avons avez ont etre avoir fait faire plus tres bien tout tous toute toutes cette cet quel quelle quels quelles comment
quoi dont ici aussi alors donc car si oui non the and est-ce rappelle retiens souviens sais savoir
""".split())

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    text        TEXT NOT NULL,
    embedding   TEXT,
    model       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    deleted_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories (user_id, deleted_at);
"""


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("’", "'"))
    return "".join(c for c in text if not unicodedata.combining(c))


def keywords(text: str) -> set[str]:
    """Mots porteurs de sens (sans accents, mots vides retirés, pluriel simple ramené au singulier)."""
    words = re.findall(r"[a-z0-9]+", fold(text))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if len(w) > 1 and w not in _STOPWORDS}


def lexical_score(query: set[str], memory: set[str]) -> float:
    if not query or not memory:
        return 0.0
    common = query & memory
    return len(common) / math.sqrt(len(query) * len(memory))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Memory:
    id: int
    user_id: str
    text: str
    updated_at: float
    embedding: Optional[list[float]] = None

    def public(self) -> dict:
        return {"id": self.id, "text": self.text, "updated_at": self.updated_at}


class OllamaEmbedder:
    """Embeddings locaux d'Ollama (/api/embed). En cas d'échec (modèle absent...), désactivé MEMORY_EMBED_RETRY s."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.MEMORY_EMBED_MODEL.strip()
        self._disabled_until = 0.0

    @property
    def available(self) -> bool:
        return bool(self.model) and time.monotonic() >= self._disabled_until

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        if not self.available or not texts:
            return None
        host = (self.settings.OLLAMA_HOST or "http://localhost:11434").rstrip("/")
        body = json.dumps({"model": self.model, "input": texts}).encode()
        request = urllib.request.Request(f"{host}/api/embed", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.settings.MEMORY_EMBED_TIMEOUT) as response:
                vectors = json.loads(response.read()).get("embeddings")
            if not vectors or len(vectors) != len(texts):
                raise ValueError("réponse sans embeddings")
            return vectors
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._disabled_until = time.monotonic() + self.settings.MEMORY_EMBED_RETRY
            print(f"⚠️ [MEMORY] Embeddings « {self.model} » indisponibles ({e}) : recherche par mots communs.")
            return None


class MemoryStore:
    def __init__(self, settings: Optional[Settings] = None, path: Optional[Path] = None, embedder=None):
        self._settings = settings
        raw = Path(path or self.settings.MEMORY_DB_PATH)
        self.path = raw if raw.is_absolute() else MEMORY_ROOT / raw
        self.embedder = embedder if embedder is not None else OllamaEmbedder(self.settings)
        self._lock = threading.Lock()
        self._ready = False

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    def update_settings(self, settings: Settings):
        self._settings = settings
        if getattr(self.embedder, "model", None) != settings.MEMORY_EMBED_MODEL.strip() and isinstance(
                self.embedder, OllamaEmbedder):
            self.embedder = OllamaEmbedder(settings)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.MEMORY_ENABLED)

    # ---- Base ----
    def _execute(self, sql: str, params=()) -> tuple[list[sqlite3.Row], Optional[int]]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                if not self._ready:
                    conn.executescript(_SCHEMA)
                    self._ready = True
                with conn:
                    cur = conn.execute(sql, tuple(params))
                    return cur.fetchall(), cur.lastrowid
            finally:
                conn.close()

    @staticmethod
    def _row(r: sqlite3.Row) -> Memory:
        return Memory(r["id"], r["user_id"], r["text"], r["updated_at"],
                      json.loads(r["embedding"]) if r["embedding"] else None)

    def all(self, user_id: str) -> list[Memory]:
        """Souvenirs du compte, le plus récent d'abord."""
        rows, _ = self._execute("SELECT * FROM memories WHERE user_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC",
                                (user_id,))
        return [self._row(r) for r in rows]

    def _embedding(self, text: str) -> Optional[list[float]]:
        vectors = self.embedder.embed([text]) if self.embedder is not None else None
        return vectors[0] if vectors else None

    def _ensure_embeddings(self, memories: list[Memory]):
        """Calcule les embeddings manquants (souvenirs enregistrés avant l'installation du modèle)."""
        missing = [m for m in memories if m.embedding is None]
        if not missing or self.embedder is None or not self.embedder.available:
            return
        vectors = self.embedder.embed([m.text for m in missing])
        if not vectors:
            return
        for memory, vector in zip(missing, vectors):
            memory.embedding = vector
            self._execute("UPDATE memories SET embedding = ?, model = ? WHERE id = ?",
                          (json.dumps(vector), self.embedder.model, memory.id))

    def _similarity(self, query: str, query_vector, memory: Memory) -> float:
        if query_vector is not None and memory.embedding is not None and len(memory.embedding) == len(query_vector):
            return cosine(query_vector, memory.embedding)
        return lexical_score(keywords(query), keywords(memory.text))

    # ---- Écriture ----
    def remember(self, user_id: str, text: str) -> tuple[Memory, bool]:
        """Enregistre un souvenir ; retourne (souvenir, False) si un souvenir presque identique a été remplacé."""
        s = self.settings
        text = re.sub(r"\s+", " ", (text or "").strip().rstrip("."))
        if not text:
            raise ValueError("Que faut-il retenir ?")
        if len(text) > s.MEMORY_MAX_CHARS:
            raise ValueError(f"Souvenir trop long ({len(text)} caractères, {s.MEMORY_MAX_CHARS} au plus).")
        existing = self.all(user_id)
        vector = self._embedding(text)
        if vector is not None:
            self._ensure_embeddings(existing)
        now = time.time()
        for memory in existing:
            same = fold(memory.text) == fold(text)
            if same or self._similarity(text, vector, memory) >= s.MEMORY_DUPLICATE_SIMILARITY:
                self._execute("UPDATE memories SET text = ?, embedding = ?, model = ?, updated_at = ? WHERE id = ?",
                              (text, json.dumps(vector) if vector else None,
                               getattr(self.embedder, "model", "") if vector else "", now, memory.id))
                return Memory(memory.id, user_id, text, now, vector), False
        if len(existing) >= s.MEMORY_MAX_PER_USER:
            raise ValueError(f"Mémoire pleine ({s.MEMORY_MAX_PER_USER} souvenirs) : oublie-en avant d'en ajouter.")
        _, new_id = self._execute(
            "INSERT INTO memories (user_id, text, embedding, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, text, json.dumps(vector) if vector else None,
             getattr(self.embedder, "model", "") if vector else "", now, now))
        return Memory(new_id, user_id, text, now, vector), True

    def forget(self, user_id: str, memory_id: int) -> bool:
        """Efface un souvenir du compte (réellement : la mémoire est la vue de l'utilisateur, pas une archive)."""
        rows, _ = self._execute("SELECT id FROM memories WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                                (memory_id, user_id))
        if not rows:
            return False
        self._execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return True

    def find(self, user_id: str, words: str) -> list[Memory]:
        """Souvenirs du compte désignés par leur numéro ou par des mots de leur texte."""
        needle = re.sub(r"^(n°|no|num[eé]ro|#)\s*", "", (words or "").strip(), flags=re.IGNORECASE)
        memories = self.all(user_id)
        if needle.isdigit():
            return [m for m in memories if m.id == int(needle)]
        wanted = keywords(needle)
        return [m for m in memories if wanted and wanted <= keywords(m.text)]

    # ---- Lecture pour le LLM ----
    def recall(self, user_id: str, query: str) -> list[Memory]:
        """Souvenirs à donner au LLM pour cette demande (tous s'ils sont peu nombreux)."""
        s = self.settings
        memories = self.all(user_id)
        if len(memories) <= s.MEMORY_ALWAYS_INCLUDE:
            return memories
        if not (query or "").strip():  # audio envoyé directement au modèle : pas de texte, les plus récents
            return memories[:s.MEMORY_RECALL_LIMIT]
        vector = self._embedding(query) if query else None
        if vector is not None:
            self._ensure_embeddings(memories)
        threshold = s.MEMORY_MIN_SIMILARITY if vector is not None else s.MEMORY_MIN_KEYWORD_SCORE
        scored = sorted(((self._similarity(query, vector, m), m) for m in memories), key=lambda x: -x[0])
        return [m for score, m in scored[:s.MEMORY_RECALL_LIMIT] if score >= threshold]

    def prompt_for(self, user, query: str) -> str:
        """Lignes ajoutées au prompt système de ce tour (vide sans souvenir utile)."""
        if not self.enabled or user is None:
            return ""
        try:
            memories = self.recall(user.id, query or "")
        except (sqlite3.Error, OSError) as e:
            print(f"⚠️ [MEMORY] Lecture impossible ({self.path}) : {e}")
            return ""
        if not memories:
            return ""
        lines = "\n".join(f"- {m.text}" for m in memories)
        return Template(self.settings.MEMORY_PROMPT).safe_substitute(NAME=user.name, MEMORIES=lines)


if __name__ == "__main__":
    store = MemoryStore()
    user_id = sys.argv[1] if len(sys.argv) > 1 else "local"
    question = " ".join(sys.argv[2:])
    embed = store.embedder.model or "aucun (mots communs)"
    print(f"🧪 [DEBUG] Mémoire : {store.path} — compte « {user_id} » — embeddings : {embed}")
    for m in store.all(user_id):
        print(f"  🧠 n°{m.id} {m.text}")
    if question:
        print(f"\n🔎 « {question} » →")
        for m in store.recall(user_id, question):
            print(f"  • {m.text}")
