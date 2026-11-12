#!/usr/bin/env python3
"""Tests des rappels et routines (core/scheduler.py, actions/modules/reminder.py) : aucune voix, aucun LLM."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.modules.reminder import CancelReminderAction, ListRemindersAction, RemindAction, parse_request
from core.config import Settings
from core.events import EventBus
from core.scheduler import (REPEAT_DAILY, REPEAT_NONE, REPEAT_WEEKDAYS, REPEAT_WEEKLY, ReminderStore, Scheduler,
                            describe_due, next_occurrence, parse_repeat, parse_when, split_repeat)
from core.turn_context import session_context
from core.users import LOCAL_USER_ID, User

SETTINGS = Settings()
# Jeudi 12 novembre 2026, 10:00 (heure locale)
NOW = datetime(2026, 11, 12, 10, 0).astimezone()


def at(day: int, hour: int, minute: int = 0, month: int = 11, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute).astimezone()


class TestParseWhen(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(parse_when(text, NOW), expected, text)

    def test_relative(self):
        self.check("dans 10 minutes", NOW + timedelta(minutes=10))
        self.check("dans 1h30", NOW + timedelta(minutes=90))
        self.check("dans 2 heures et 15 minutes", NOW + timedelta(minutes=135))
        self.check("dans une heure et demie", NOW + timedelta(minutes=90))
        self.check("dans un quart d'heure", NOW + timedelta(minutes=15))
        self.check("dans une demi-heure", NOW + timedelta(minutes=30))
        self.check("dans 3 jours", NOW + timedelta(days=3))

    def test_clock_today_or_tomorrow(self):
        self.check("à 18h30", at(12, 18, 30))
        self.check("à 7h", at(13, 7))           # 7h est passée : demain
        self.check("18:45", at(12, 18, 45))
        self.check("à midi", at(12, 12))
        self.check("à 7 heures et demie", at(13, 7, 30))
        self.check("ce soir à 8h", at(12, 20))
        self.check("à 3h de l'après-midi", at(12, 15))

    def test_days(self):
        self.check("demain à 7h", at(13, 7))
        self.check("après-demain", at(14, SETTINGS.SCHEDULER_DEFAULT_HOUR))
        self.check("lundi à 9h15", at(16, 9, 15))
        self.check("jeudi à 9h", at(19, 9))     # jeudi 9h est passé : la semaine prochaine
        self.check("jeudi à 11h", at(12, 11))
        self.check("le 24 décembre à 20h", at(24, 20, month=12))
        self.check("le 1er janvier à 0h", at(1, 0, month=1, year=2027))
        self.check("15/11 à 8h", at(15, 8))
        self.check("2026-11-20T08:30", at(20, 8, 30))

    def test_errors(self):
        for text in ("", "bientôt", "dans 0 minute", "hier à 8h", "2020-01-01T00:00", "à 25h"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_when(text, NOW)

    def test_repeat(self):
        self.assertEqual(split_repeat("tous les jours à 7h"), ("a 7h", REPEAT_DAILY))
        self.assertEqual(split_repeat("en semaine à 6h45")[1], REPEAT_WEEKDAYS)
        self.assertEqual(split_repeat("tous les lundis à 9h"), ("lundis a 9h", REPEAT_WEEKLY))
        self.assertEqual(split_repeat("tous les soirs à 10h"), ("a 10h soir", REPEAT_DAILY))
        self.assertEqual(split_repeat("demain 8h")[1], REPEAT_NONE)
        self.assertEqual(parse_repeat("toutes les semaines"), REPEAT_WEEKLY)
        self.assertEqual(parse_repeat(""), REPEAT_NONE)
        with self.assertRaises(ValueError):
            parse_repeat("tous les siècles")

    def test_next_occurrence(self):
        friday = at(13, 7)
        self.assertEqual(next_occurrence(friday, REPEAT_DAILY, friday), at(14, 7))
        self.assertEqual(next_occurrence(friday, REPEAT_WEEKDAYS, friday), at(16, 7))  # saute le week-end
        self.assertEqual(next_occurrence(friday, REPEAT_WEEKLY, friday), at(20, 7))
        self.assertIsNone(next_occurrence(friday, REPEAT_NONE, friday))
        # Après un long arrêt : prochaine échéance future, pas une rafale de rattrapage
        self.assertEqual(next_occurrence(at(1, 7), REPEAT_DAILY, NOW), at(13, 7))

    def test_describe(self):
        self.assertEqual(describe_due(at(12, 18, 30), NOW), "aujourd'hui à 18:30")
        self.assertEqual(describe_due(at(13, 7), NOW), "demain à 07:00")
        self.assertEqual(describe_due(at(16, 9), NOW), "lundi 16 novembre à 09:00")


class FakeCore:
    def __init__(self, settings=SETTINGS):
        self.settings = settings
        self.events = EventBus()
        self.asked = []

    def respond(self, session_id, text=None, user=None):
        self.asked.append((session_id, text, user))
        return SimpleNamespace(text=f"Réponse à « {text} »")


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.clock = [NOW.timestamp()]
        self.store = ReminderStore(SETTINGS)
        self.scheduler = Scheduler(self.core, store=self.store, clock=lambda: self.clock[0])
        self.events = []
        self.core.events.subscribe(lambda e: self.events.append(e))
        self.marie = User("u1", "Marie", "member")

    def test_reminder_fires_once_at_due_time(self):
        r = self.store.add("reminder", "sortir le linge", NOW + timedelta(minutes=10), user=self.marie)
        self.assertEqual(self.scheduler.run_due(), [])
        self.clock[0] += 600
        fired = self.scheduler.run_due()
        self.assertEqual([f["id"] for f in fired], [r.id])
        self.assertEqual(fired[0]["text"], "Petit rappel : sortir le linge")
        self.assertEqual(self.events[-1].type, "reminder")
        self.assertEqual(self.events[-1].data["user_id"], "u1")
        self.assertEqual(self.store.active(), [])
        self.assertEqual(self.scheduler.run_due(), [])

    def test_repeated_reminder_is_rescheduled(self):
        r = self.store.add("reminder", "médicaments", NOW + timedelta(hours=1), REPEAT_DAILY)
        self.clock[0] += 3600
        self.scheduler.run_due()
        again = self.store.get(r.id)
        self.assertEqual(again.due, NOW + timedelta(days=1, hours=1))
        self.assertEqual(again.fired_count, 1)

    def test_late_and_missed_reminders(self):
        self.store.add("reminder", "un peu tard", NOW + timedelta(minutes=1))
        self.store.add("reminder", "beaucoup trop tard", NOW - timedelta(seconds=SETTINGS.SCHEDULER_MISSED_GRACE + 60))
        self.clock[0] += 3600
        fired = self.scheduler.run_due()
        self.assertEqual([f["message"] for f in fired], ["un peu tard"])
        self.assertTrue(fired[0]["late"])
        self.assertTrue(fired[0]["text"].startswith("Rappel prévu à"))
        self.assertEqual(self.store.active(), [])

    def test_routine_asks_the_assistant_with_owner_rights(self):
        self.store.add("routine", "donne-moi la météo", NOW + timedelta(minutes=5), user=self.marie)
        self.store.add("routine", "quelle heure est-il", NOW + timedelta(minutes=5))
        self.clock[0] += 300
        fired = self.scheduler.run_due()
        self.assertEqual(fired[0]["text"], "Réponse à « donne-moi la météo »")
        (sid, text, user), (_, _, household) = self.core.asked
        self.assertTrue(sid.startswith("routine-"))
        self.assertEqual((user.id, user.role), ("u1", "member"))
        self.assertEqual(household.id, LOCAL_USER_ID)  # jamais une session sans propriétaire (sans restriction)

    def test_per_user_limit(self):
        store = ReminderStore(Settings(SCHEDULER_MAX_PER_USER=1))
        store.add("reminder", "un", NOW + timedelta(hours=1), user=self.marie)
        store.add("reminder", "autre compte", NOW + timedelta(hours=1))
        with self.assertRaises(ValueError):
            store.add("reminder", "deux", NOW + timedelta(hours=1), user=self.marie)

    def test_thread_start_and_stop(self):
        scheduler = Scheduler(self.core, store=self.store)
        scheduler.start()
        self.assertTrue(scheduler.running)
        scheduler.stop()
        self.assertFalse(scheduler.running)


class TestReminderTools(unittest.TestCase):
    def setUp(self):
        from core import settings_store
        self.previous_owner = settings_store.get_owner()
        self.core = FakeCore()
        self.core.scheduler = Scheduler(self.core, store=ReminderStore(SETTINGS))
        settings_store.set_owner(self.core)
        self.marie = SimpleNamespace(user=User("u1", "Marie", "member"))
        self.leo = SimpleNamespace(user=User("u2", "Léo", "member"))

    def tearDown(self):
        from core import settings_store
        settings_store.set_owner(self.previous_owner)

    def test_parse_request_formats(self):
        due, message, repeat = parse_request("dans 10 minutes | sortir le linge", SETTINGS)
        self.assertEqual((message, repeat), ("sortir le linge", REPEAT_NONE))
        _, message, repeat = parse_request("tous les lundis à 9h : réunion d'équipe", SETTINGS)
        self.assertEqual((message, repeat), ("réunion d'équipe", REPEAT_WEEKLY))
        _, message, _ = parse_request("dans 20 minutes de sortir le gâteau", SETTINGS)
        self.assertEqual(message, "sortir le gâteau")
        _, message, repeat = parse_request('{"when": "demain 8h", "message": "pain", "repeat": "en semaine"}', SETTINGS)
        self.assertEqual((message, repeat), ("pain", REPEAT_WEEKDAYS))
        for bad in ("", "dans 10 minutes", "quand tu veux | truc", "dans 1h | " + "x" * 600):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_request(bad, SETTINGS)

    def test_each_account_sees_and_cancels_only_its_reminders(self):
        remind, listing, cancel = RemindAction(), ListRemindersAction(), CancelReminderAction()
        with session_context(self.marie):
            code, out, _ = remind.execute_sync("dans 1 heure | appeler le plombier")
            self.assertEqual(code, 0)
            self.assertIn("programmé", out)
        with session_context(self.leo):
            self.assertEqual(listing.execute_sync()[1], "Aucun rappel en attente.")
            self.assertEqual(cancel.execute_sync("plombier")[0], 1)
        with session_context(self.marie):
            self.assertIn("appeler le plombier", listing.execute_sync()[1])
            code, out, _ = cancel.execute_sync("plombier")
            self.assertEqual(code, 0)
            self.assertEqual(listing.execute_sync()[1], "Aucun rappel en attente.")

    def test_outside_a_turn_reminders_belong_to_the_household(self):
        code, _, _ = RemindAction().execute_sync("dans 5 minutes | fermer les volets")
        self.assertEqual(code, 0)
        self.assertEqual(self.core.scheduler.store.active()[0].user_id, LOCAL_USER_ID)

    def test_invalid_request_is_an_error_not_an_exception(self):
        code, _, err = RemindAction().execute_sync("un jour peut-être")
        self.assertEqual(code, 1)
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()


class TestGatewayReminders(unittest.TestCase):
    def test_reminder_reaches_only_its_owner_and_the_household(self):
        from starlette.testclient import TestClient
        from gateway.app import create_app
        from tests.test_gateway import make_core
        from tests.test_users import ACCOUNT_SETTINGS

        core = make_core([])
        client = TestClient(create_app(core, ACCOUNT_SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "identity": "marie@foyer", "password": "secret"})
            ready = ws.receive_json()
            marie = ready["user"]["id"]
            core.events.emit("reminder", "scheduler", id=1, text="pour quelqu'un d'autre", user_id="autre")
            core.events.emit("reminder", "scheduler", id=2, text="pour le foyer", user_id=LOCAL_USER_ID)
            core.events.emit("reminder", "scheduler", id=3, text="pour Marie", user_id=marie)
            received = [ws.receive_json() for _ in range(2)]
            self.assertEqual([(m["type"], m["id"]) for m in received], [("reminder", 2), ("reminder", 3)])
