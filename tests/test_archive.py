#!/usr/bin/env python3
"""
Tests de l'archive des conversations (core/archive.py) : tout échange est conservé (micro, PWA), une suppression ou
une correction ne fait que masquer, les conversations du micro sont visibles dans la PWA par les rôles du foyer,
et les notes de satisfaction (-2 à +2, commentaire) sont validées puis enregistrées.
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.archive import SOURCE_LOCAL, SOURCE_PWA, ConversationArchive, clean_rating
from core.config import Settings
from core.users import User, admin_user, local_user
from gateway.app import create_app
from tests.test_gateway import SETTINGS, collect_until_done, make_core
from tests.test_users import ACCOUNT_SETTINGS, MemoryHistory


class TestArchiveStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = ConversationArchive(SETTINGS, path=Path(self.tmp.name) / "a.sqlite3")

    def tearDown(self):
        self.archive.close()
        self.tmp.cleanup()

    def exchange(self, turn, question, answer):
        return [{"role": "user", "content": question, "turn": turn},
                {"role": "assistant", "content": answer, "turn": turn, "tools": [{"name": "volume"}]}]

    def test_hidden_and_edited_messages_stay_in_the_export(self):
        a = self.archive
        a.append("c1", self.exchange("t1", "Bonjour", "Salut"), SOURCE_PWA, "s", "pb_m", "Marie", "gemma")
        a.append("c1", self.exchange("t2", "Météo ?", "Il pleut"), SOURCE_PWA, "s", "pb_m", "Marie", "gemma")
        a.hide_turns("c1", ["t1"])
        a.edit_answer("c1", "t2", "Il fait beau")
        self.assertEqual([m["content"] for m in a.load_conversation("c1", SOURCE_PWA, "pb_m")],
                         ["Météo ?", "Il fait beau"])
        out = io.StringIO()
        self.assertEqual(a.export_jsonl(out), 1)
        messages = json.loads(out.getvalue())["messages"]
        self.assertEqual([m["content"] for m in messages], ["Bonjour", "Salut", "Météo ?", "Il pleut", "Il fait beau"])
        self.assertTrue(messages[0]["deleted_at"])
        self.assertTrue(messages[3]["superseded"])
        self.assertEqual(messages[4]["model"], "edit")
        self.assertEqual(messages[1]["tools"], [{"name": "volume"}])
        visible = io.StringIO()
        a.export_jsonl(visible, include_hidden=False)
        self.assertEqual(len(json.loads(visible.getvalue())["messages"]), 2)

    def test_feedback_is_one_per_person_and_exported(self):
        a = self.archive
        a.append("c1", self.exchange("t1", "Bonjour", "Salut"), SOURCE_LOCAL, "local", "local", "Foyer")
        a.set_feedback("c1", "t1", "pb_m", "Marie", -1, "trop court")
        a.set_feedback("c1", "t1", "pb_m", "Marie", 2, "")
        a.set_feedback("c1", "t1", "pb_l", "Léo", 0)
        self.assertEqual(a.feedback_for("c1", "pb_m"), {"t1": {"rating": 2, "comment": ""}})
        out = io.StringIO()
        a.export_jsonl(out)
        notes = json.loads(out.getvalue())["messages"][1]["feedback"]
        self.assertEqual(sorted(n["rating"] for n in notes), [0, 2])

    def test_household_list(self):
        a = self.archive
        a.append("c1", self.exchange("t1", "Allume la lumière", "C'est fait"), SOURCE_LOCAL, "local", "local", "Foyer")
        a.append("c2", self.exchange("t1", "Secret", "Ok"), SOURCE_PWA, "s", "pb_m", "Marie")
        convs = a.list_conversations(SOURCE_LOCAL)
        self.assertEqual([c["id"] for c in convs], ["c1"])
        self.assertEqual(convs[0]["title"], "Allume la lumière")
        self.assertEqual(convs[0]["source"], "local")
        self.assertEqual(convs[0]["tools"], ["volume"])

    def test_rating_validation(self):
        for good in (-2, 0, 2):
            self.assertEqual(clean_rating(good), good)
        for bad in (3, -3, 1.5, "1", None, True):
            self.assertIsNone(clean_rating(bad))

    def test_disabled_archive_writes_nothing(self):
        off = ConversationArchive(Settings(**{**SETTINGS.model_dump(), "ARCHIVE_ENABLED": False}),
                                  path=Path(self.tmp.name) / "off.sqlite3")
        self.assertFalse(off.append("c1", self.exchange("t1", "a", "b"), SOURCE_PWA))
        self.assertFalse((Path(self.tmp.name) / "off.sqlite3").exists())


class TestCoreArchive(unittest.TestCase):
    def setUp(self):
        self.marie = User("pb_marie@foyer", "Marie", "member", "tok-marie@foyer")
        self.leo = User("pb_leo@foyer", "Leo", "guest", "tok-leo@foyer")

    def core(self, history=None):
        core = make_core([])
        if history is not None:
            core.history = history
        return core

    def test_local_conversations_are_archived_and_rotate_on_sleep(self):
        core = self.core()
        events = []
        core.events.subscribe(lambda e: events.append(e) if e.type == "history_updated" else None)
        local = core.open_session("local", persistent=True, user=local_user(SETTINGS))
        core.respond(local.id, text="Bonjour", turn="t1")
        first = local.conversation_id
        core.new_local_conversation(local.id)
        core.respond(local.id, text="Encore", turn="t2")
        convs = core.archive.list_conversations(SOURCE_LOCAL)
        self.assertEqual({c["id"] for c in convs}, {first, local.conversation_id})
        self.assertEqual([e.data["conversation_id"] for e in events], [first, local.conversation_id])

    def test_household_visible_by_roles_and_read_only(self):
        core = self.core(MemoryHistory())
        local = core.open_session("local", persistent=True, user=local_user(SETTINGS))
        core.respond(local.id, text="Bonjour", turn="t1")
        marie = core.open_session(None, user=self.marie)
        before = marie.conversation_id
        listed = core.list_conversations(marie.id)
        self.assertEqual([c["source"] for c in listed], ["local"])
        messages = core.household_conversation(marie.id, local.conversation_id)
        self.assertEqual([m["content"] for m in messages], ["Bonjour", "Écho : Bonjour"])
        self.assertEqual(marie.conversation_id, before)  # simple lecture : la session ne change pas
        leo = core.open_session(None, user=self.leo)
        self.assertEqual(core.list_conversations(leo.id), [])
        with self.assertRaises(PermissionError):
            core.household_conversation(leo.id, local.conversation_id)

    def test_delete_and_forget_only_hide(self):
        core = self.core(MemoryHistory())
        session = core.open_session(None, user=self.marie)
        core.respond(session.id, text="Un", turn="t1")
        core.respond(session.id, text="Deux", turn="t2")
        core.forget(session.id, ["t1"])
        cid = session.conversation_id
        core.delete_conversation(session.id, cid)
        self.assertEqual(core.archive.load_conversation(cid, SOURCE_PWA, self.marie.id), [])
        out = io.StringIO()
        core.archive.export_jsonl(out)
        self.assertEqual(len(json.loads(out.getvalue())["messages"]), 4)

    def test_feedback_permissions(self):
        core = self.core(MemoryHistory())
        local = core.open_session("local", persistent=True, user=local_user(SETTINGS))
        core.respond(local.id, text="Bonjour", turn="t1")
        marie = core.open_session(None, user=self.marie)
        core.respond(marie.id, text="À moi", turn="m1")
        leo = core.open_session(None, user=self.leo)

        saved = core.set_feedback(marie.id, marie.conversation_id, "m1", 2, "  parfait  ")
        self.assertEqual((saved["rating"], saved["comment"]), (2, "parfait"))
        core.set_feedback(marie.id, local.conversation_id, "t1", -2)  # conversation du foyer
        with self.assertRaises(PermissionError):
            core.set_feedback(leo.id, marie.conversation_id, "m1", 1)  # celle d'un autre compte
        with self.assertRaises(PermissionError):
            core.set_feedback(leo.id, local.conversation_id, "t1", 1)  # invité : foyer non visible
        with self.assertRaises(ValueError):
            core.set_feedback(marie.id, marie.conversation_id, "m1", 5)
        with self.assertRaises(ValueError):
            core.set_feedback(marie.id, 'x" OR 1', "m1", 1)
        # Note renvoyée avec la conversation rechargée
        loaded = core.load_conversation(marie.id, marie.conversation_id)
        self.assertEqual(loaded[1]["feedback"], {"rating": 2, "comment": "parfait"})

    def test_feedback_on_exchange_older_than_the_archive(self):
        history = MemoryHistory()
        history.rows = [{"user": self.marie.id, "conversation": "ancienne", "turn": "o1", "role": "user", "content": "Hier"},
                        {"user": self.marie.id, "conversation": "ancienne", "turn": "o1", "role": "assistant",
                         "content": "Réponse d'hier"}]
        core = self.core(history)
        marie = core.open_session(None, user=self.marie)
        core.set_feedback(marie.id, "ancienne", "o1", 1, "ok")
        self.assertEqual(core.archive.feedback_for("ancienne", self.marie.id)["o1"]["rating"], 1)
        self.assertEqual(len(core.archive.load_conversation("ancienne", SOURCE_PWA, self.marie.id)), 2)

    def test_master_token_conversations_come_from_the_archive(self):
        core = self.core()
        admin = admin_user(SETTINGS)
        session = core.open_session(None, user=admin)
        core.respond(session.id, text="Bonjour", turn="t1")
        cid = session.conversation_id
        core.reset(session.id)
        self.assertIn(cid, [c["id"] for c in core.list_conversations(session.id)])
        self.assertEqual([m["content"] for m in core.load_conversation(session.id, cid)], ["Bonjour", "Écho : Bonjour"])


class TestGatewayFeedback(unittest.TestCase):
    def test_feedback_round_trip_and_household_view(self):
        core = make_core([])
        core.history = MemoryHistory()
        local = core.open_session("local", persistent=True, user=local_user(SETTINGS))
        core.respond(local.id, text="Bonjour", turn="t1")
        client = TestClient(create_app(core, ACCOUNT_SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "identity": "marie@foyer", "password": "secret"})
            ready = ws.receive_json()
            self.assertTrue(ready["feedback"]["enabled"])
            self.assertTrue(ready["household"])
            ws.send_json({"type": "text", "text": "Salut", "turn": "w1"})
            collect_until_done(ws)
            ws.send_json({"type": "feedback", "conversation_id": ready["conversation_id"], "turn": "w1",
                          "rating": -1, "comment": "bof"})
            saved = ws.receive_json()
            self.assertEqual((saved["type"], saved["rating"], saved["comment"]), ("feedback_saved", -1, "bof"))
            ws.send_json({"type": "feedback", "conversation_id": ready["conversation_id"], "turn": "w1", "rating": 9})
            self.assertEqual(ws.receive_json()["type"], "feedback_error")
            ws.send_json({"type": "load_conversation", "conversation_id": local.conversation_id, "source": "local"})
            loaded = ws.receive_json()
            self.assertTrue(loaded["readonly"])
            self.assertEqual([m["content"] for m in loaded["history"]], ["Bonjour", "Écho : Bonjour"])
            # Échange au micro pendant que la PWA est ouverte : elle est prévenue
            core.respond(local.id, text="Encore", turn="t2")
            update = ws.receive_json()
            self.assertEqual((update["type"], update["conversation_id"]), ("history_updated", local.conversation_id))


if __name__ == "__main__":
    unittest.main()
