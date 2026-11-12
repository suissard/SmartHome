#!/usr/bin/env python3
"""Tests de la mémoire à long terme (core/memory.py, actions/modules/memory.py) : aucun modèle n'est appelé."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.modules.memory import ForgetMemoryAction, ListMemoriesAction, RememberAction
from core.config import Settings
from core.memory import MemoryStore, keywords, lexical_score
from core.turn_context import session_context
from core.users import LOCAL_USER_ID, User

SETTINGS = Settings(MEMORY_EMBED_MODEL="")


class FakeEmbedder:
    """Vecteurs « par thème » : deux textes du même thème sont proches."""
    model = "fake"
    available = True
    THEMES = ("boisson", "famille", "voiture")

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[1.0 if theme in t.lower() else 0.0 for theme in self.THEMES] + [0.01] for t in texts]


class TestKeywords(unittest.TestCase):
    def test_keywords_ignore_accents_stopwords_and_plurals(self):
        self.assertEqual(keywords("Ma fille s'appelle Léa"), {"fille", "appelle", "lea"})
        self.assertEqual(keywords("Les chats"), {"chat"})
        self.assertGreater(lexical_score(keywords("comment s'appelle ma fille ?"), keywords("Sa fille s'appelle Léa")), 0.5)


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(SETTINGS)

    def test_remember_dedupe_and_forget_per_account(self):
        m, created = self.store.remember("u1", "Préfère le thé au café.")
        self.assertTrue(created)
        again, created = self.store.remember("u1", "préfère le thé au café")
        self.assertFalse(created)
        self.assertEqual(again.id, m.id)
        self.store.remember("u2", "Préfère le café")
        self.assertEqual([x.text for x in self.store.all("u1")], ["préfère le thé au café"])
        self.assertFalse(self.store.forget("u2", m.id))   # pas le sien
        self.assertTrue(self.store.forget("u1", m.id))
        self.assertEqual(self.store.all("u1"), [])

    def test_limits(self):
        store = MemoryStore(Settings(MEMORY_MAX_PER_USER=1, MEMORY_MAX_CHARS=20))
        with self.assertRaises(ValueError):
            store.remember("u1", "  ")
        with self.assertRaises(ValueError):
            store.remember("u1", "x" * 21)
        store.remember("u1", "un souvenir")
        with self.assertRaises(ValueError):
            store.remember("u1", "un autre")

    def test_few_memories_are_all_given_many_are_ranked(self):
        store = MemoryStore(Settings(MEMORY_ALWAYS_INCLUDE=2, MEMORY_RECALL_LIMIT=2))
        store.remember("u1", "Sa fille s'appelle Léa")
        store.remember("u1", "Il conduit une Clio rouge")
        self.assertEqual(len(store.recall("u1", "bonjour")), 2)   # peu de souvenirs : tous
        store.remember("u1", "Il préfère le thé")
        recalled = [m.text for m in store.recall("u1", "Comment s'appelle ma fille ?")]
        self.assertEqual(recalled, ["Sa fille s'appelle Léa"])
        self.assertEqual(len(store.recall("u1", "")), 2)  # audio direct, sans texte : les plus récents

    def test_embeddings_when_available(self):
        embedder = FakeEmbedder()
        store = MemoryStore(Settings(MEMORY_ALWAYS_INCLUDE=0, MEMORY_RECALL_LIMIT=1), embedder=embedder)
        store.remember("u1", "boisson préférée : thé")
        store.remember("u1", "famille : une fille, Léa")
        self.assertEqual([m.text for m in store.recall("u1", "une boisson ?")], ["boisson préférée : thé"])
        # Même thème : le nouveau souvenir remplace l'ancien
        _, created = store.remember("u1", "boisson préférée : café")
        self.assertFalse(created)
        self.assertEqual(len(store.all("u1")), 2)

    def test_prompt(self):
        user = User("u1", "Marie", "member")
        self.assertEqual(self.store.prompt_for(user, "salut"), "")
        self.store.remember("u1", "Préfère le thé")
        prompt = self.store.prompt_for(user, "salut")
        self.assertIn("Marie", prompt)
        self.assertIn("- Préfère le thé", prompt)
        self.assertEqual(MemoryStore(Settings(MEMORY_ENABLED=False)).prompt_for(user, "x"), "")


class TestMemoryTools(unittest.TestCase):
    def setUp(self):
        from core import settings_store
        self.previous = settings_store.get_owner()
        self.owner = SimpleNamespace(settings=SETTINGS, memory=MemoryStore(SETTINGS))
        settings_store.set_owner(self.owner)
        self.marie = SimpleNamespace(user=User("u1", "Marie", "member"))

    def tearDown(self):
        from core import settings_store
        settings_store.set_owner(self.previous)

    def test_remember_list_forget(self):
        with session_context(self.marie):
            code, out, _ = RememberAction().execute_sync("Sa fille s'appelle Léa")
            self.assertEqual(code, 0)
            self.assertIn("Retenu", out)
            self.assertIn("Léa", ListMemoriesAction().execute_sync()[1])
            self.assertEqual(ForgetMemoryAction().execute_sync("voiture")[0], 1)
            self.assertEqual(ForgetMemoryAction().execute_sync("fille")[0], 0)
            self.assertEqual(ListMemoriesAction().execute_sync()[1], "Aucun souvenir enregistré.")
        # Hors d'un tour : souvenirs du foyer
        RememberAction().execute_sync("Le code du portail est dans le tiroir")
        self.assertEqual(len(self.owner.memory.all(LOCAL_USER_ID)), 1)


class TestMemoryInCore(unittest.TestCase):
    def test_memories_reach_the_system_prompt_and_the_pwa(self):
        from starlette.testclient import TestClient
        from gateway.app import create_app
        from tests.test_gateway import make_core
        from tests.test_users import ACCOUNT_SETTINGS

        core = make_core([])
        client = TestClient(create_app(core, ACCOUNT_SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "identity": "marie@foyer", "password": "secret"})
            ready = ws.receive_json()
            self.assertTrue(ready["memory"]["enabled"])
            ws.send_json({"type": "add_memory", "text": "Préfère le thé"})
            listed = ws.receive_json()
            self.assertEqual(listed["type"], "memories")
            self.assertEqual([m["text"] for m in listed["memories"]], ["Préfère le thé"])
            ws.send_json({"type": "add_memory", "text": ""})
            self.assertEqual(ws.receive_json()["type"], "memory_error")

            session = core.get_session(ready["session"])
            core.respond(session.id, text="Que boire ?", user=session.user)
            self.assertIn("Préfère le thé", session.conversation.memory_prompt)

            ws.send_json({"type": "delete_memory", "id": listed["memories"][0]["id"]})
            # Les événements du tour (fragments, réponse, latence) arrivent d'abord
            reply = ws.receive_json()
            while reply["type"] != "memories":
                reply = ws.receive_json()
            self.assertEqual(reply["memories"], [])
            ws.send_json({"type": "delete_memory", "id": "abc"})
            self.assertEqual(ws.receive_json()["type"], "memory_error")


class TestMemoryBackgroundBackfill(unittest.TestCase):
    def test_recall_schedules_nonblocking_backfill_and_close_joins(self):
        import threading

        started = threading.Event()
        release = threading.Event()

        class BlockingEmbedder(FakeEmbedder):
            def embed(self, texts):
                # Backfill passe toutes les entrées sans embedding (2) ; la requête de recall n'a qu'1 texte.
                if len(texts) >= 2:
                    started.set()
                    release.wait(timeout=3.0)
                return [[1.0, 0.0, 0.0, 0.01] for _ in texts]

        # On insère d'abord sans embedder (embedding=None en base), puis on rattache un embedder bloquant.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            store_no_emb = MemoryStore(
                Settings(MEMORY_EMBED_MODEL="", MEMORY_ALWAYS_INCLUDE=0),
                path=db_path,
            )
            store_no_emb.remember("u1", "Aime le café noir")
            store_no_emb.remember("u1", "Habite à Lyon")
            store_no_emb.close()

            embedder = BlockingEmbedder()
            store = MemoryStore(
                Settings(MEMORY_EMBED_MODEL="fake", MEMORY_ALWAYS_INCLUDE=0),
                path=db_path,
                embedder=embedder,
            )
            # recall() déclenche le backfill asynchrone pour les entrées sans embedding mais retourne tout de suite
            recalled = store.recall("u1", "café")
            self.assertGreaterEqual(len(recalled), 1)
            self.assertTrue(started.wait(timeout=1.5), "Le backfill en arrière-plan ne s'est pas lancé")
            release.set()
            store.close()
            self.assertTrue(store._backfill_thread is None or not store._backfill_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
