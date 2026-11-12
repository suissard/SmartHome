#!/usr/bin/env python3
"""
Tests des comptes utilisateurs : droits par rôle (ToolPolicy), sessions liées à leur propriétaire,
connexion à la passerelle par compte (annuaire factice), accès aux paramètres réservé aux administrateurs,
et client PocketBase (serveur HTTP local factice).
"""

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import Settings
from core.tools import ToolPolicy
from core.users import (
    USER_DIRECTORIES, AuthError, DirectoryUnavailable, PocketBaseDirectory, User, UserDirectory, admin_user,
    is_admin, local_user, tool_policy,
)
from gateway.app import create_app
from tests.test_gateway import SETTINGS, TOKEN, collect_until_done, make_core

PASSWORDS = {"marie@foyer": ("secret", "member"), "leo@foyer": ("1234", "guest"), "boss@foyer": ("super", "admin")}


@USER_DIRECTORIES.register("fake_test")
class FakeDirectory(UserDirectory):
    """Annuaire en mémoire : jeton de compte = « tok-<identifiant> »."""

    def __init__(self, settings):
        super().__init__(settings)
        self.managed_users = [
            {"id": "u1", "email": "marie@foyer", "name": "Marie", "role": "member", "superadmin": False, "created": "", "updated": ""},
        ]

    def _user(self, identity):
        is_super = identity == "boss@foyer"
        return User(
            f"pb_{identity}",
            identity.split("@")[0].title(),
            PASSWORDS[identity][1],
            f"tok-{identity}",
            email=identity,
            superadmin=is_super,
        )

    def login(self, identity, password):
        if PASSWORDS.get(identity, (None,))[0] != password:
            raise AuthError("Identifiants refusés.")
        return self._user(identity)

    def refresh(self, token):
        identity = token.removeprefix("tok-")
        if identity not in PASSWORDS:
            raise AuthError("Identifiants refusés.")
        return self._user(identity)

    def update_profile(self, user, name, instructions, voice="", assistant_name=None):
        from core.users import clean_profile
        name, instructions = clean_profile(name, instructions, self.settings)
        assistant = user.assistant_name if assistant_name is None else assistant_name
        return User(user.id, name, user.role, user.token, instructions, voice, email=user.email,
                    superadmin=user.superadmin, assistant_name=assistant)

    def list_users(self, user):
        if not user.superadmin:
            raise AuthError("Réservé aux superadmins.")
        return list(self.managed_users)

    def create_user(self, user, email, password, name="", role="member"):
        if not user.superadmin:
            raise AuthError("Réservé aux superadmins.")
        item = {"id": f"u{len(self.managed_users)+1}", "email": email, "name": name or email, "role": role, "superadmin": False, "created": "", "updated": ""}
        self.managed_users.append(item)
        return item

    def update_user_role(self, user, record_id, role, name=None):
        if not user.superadmin:
            raise AuthError("Réservé aux superadmins.")
        for item in self.managed_users:
            if item["id"] == record_id:
                item["role"] = role
                if name:
                    item["name"] = name
                return item
        raise AuthError("Introuvable.")

    def delete_user(self, user, record_id):
        if not user.superadmin:
            raise AuthError("Réservé aux superadmins.")
        self.managed_users = [u for u in self.managed_users if u["id"] != record_id]


ACCOUNT_SETTINGS = Settings(**{**SETTINGS.model_dump(), "GATEWAY_AUTH_TOKEN": TOKEN, "AUTH_PROVIDER": "fake_test"})


class TestToolPolicy(unittest.TestCase):
    def test_rules(self):
        policy = ToolPolicy.parse("safe, shutdown")
        self.assertTrue(policy.allows("volume", "safe"))
        self.assertTrue(policy.allows("shutdown", "confirm"))
        self.assertFalse(policy.allows("reboot", "confirm"))
        everything_but = ToolPolicy.parse("*,-shutdown")
        self.assertTrue(everything_but.allows("reboot", "confirm"))
        self.assertFalse(everything_but.allows("SHUTDOWN", "confirm"))
        self.assertFalse(ToolPolicy.parse("").allows("volume", "safe"))

    def test_roles(self):
        s = Settings(MCP_CLIENT_ENABLED=False)
        self.assertTrue(is_admin(admin_user(s), s))
        self.assertTrue(is_admin(local_user(s), s))
        guest = User("pb_x", "X", "guest")
        self.assertFalse(is_admin(guest, s))
        self.assertTrue(tool_policy(guest, s).allows("volume", "safe"))
        self.assertFalse(tool_policy(guest, s).allows("shutdown", "confirm"))
        self.assertFalse(tool_policy(User("pb_y", "Y", "inconnu"), s).allows("volume", "safe"))
        self.assertIsNone(tool_policy(None, s))

    def test_tag_mode_respects_policy(self):
        from actions.manager import ActionManager
        manager = ActionManager()
        guest = ToolPolicy.parse("safe")
        prompt = manager.build_dynamic_system_prompt("Base.", policy=guest)
        self.assertNotIn("[SHUTDOWN]", prompt)
        self.assertIn("[VOLUME", prompt)
        with mock.patch("actions.base.BaseAction.execute", return_value=True) as execute:
            text = manager.process_response("D'accord. [SHUTDOWN]", policy=guest)
        self.assertEqual(text, "D'accord.")
        execute.assert_not_called()


class TestSessionOwnership(unittest.TestCase):
    def test_guest_sees_only_allowed_tools_and_cannot_take_other_sessions(self):
        executed = []
        core = make_core(executed)
        marie, leo = User("pb_m", "Marie", "member"), User("pb_l", "Léo", "guest")
        mine = core.open_session("s1", user=marie)
        self.assertEqual({t.name for t in mine.conversation.tools.all()}, {"volume", "shutdown"})

        other = core.open_session("s1", user=leo)
        self.assertNotEqual(other.id, "s1")
        self.assertEqual([t.name for t in other.conversation.tools.all()], ["volume"])
        # Le micro (session interne sans propriétaire) n'est pas repris non plus
        core.open_session("local", persistent=True)
        self.assertNotEqual(core.open_session("local", user=marie).id, "local")

        # Outil non permis : jamais exécuté, même demandé par le LLM
        reply = core.respond(other.id, text="éteins tout")
        self.assertEqual(executed, [])
        self.assertFalse(reply.tools[0]["executed"])

    def test_expired_session_is_recreated_with_its_owner_rights(self):
        # Session disparue (expiration) avant la demande : jamais recréée sans propriétaire (aucune restriction)
        executed = []
        core = make_core(executed)
        leo = User("pb_l", "Léo", "guest")
        session = core.open_session("s9", user=leo)
        core.close_session(session.id)
        reply = core.respond("s9", text="éteins tout", user=leo)
        self.assertEqual(executed, [])
        self.assertFalse(reply.tools[0]["executed"])
        self.assertEqual(core.get_session("s9").user, leo)
        self.assertEqual([t.name for t in core.get_session("s9").conversation.tools.all()], ["volume"])


class TestUserProfile(unittest.TestCase):
    def test_prompt_lines(self):
        from core.users import user_prompt
        s = Settings(MCP_CLIENT_ENABLED=False)
        self.assertEqual(user_prompt(User("pb_m", "Marie", "member"), s), "Tu t'appelles Jarvis.\nTu parles avec Marie.")
        with_prefs = user_prompt(User("pb_m", "Marie", "member", instructions="Tutoie-moi."), s)
        self.assertIn("Tutoie-moi.", with_prefs)
        # Sans profil : seul le nom de l'assistant est donné
        self.assertEqual(user_prompt(admin_user(s), s), "Tu t'appelles Jarvis.")
        self.assertEqual(user_prompt(local_user(s), s), "Tu t'appelles Jarvis.")
        self.assertEqual(user_prompt(None, s), "Tu t'appelles Jarvis.")

    def test_assistant_name(self):
        from core.users import assistant_name, clean_assistant_name, user_prompt
        s = Settings(MCP_CLIENT_ENABLED=False, ASSISTANT_NAME="Alfred")
        self.assertEqual(assistant_name(None, s), "Alfred")
        marie = User("pb_m", "Marie", "member", assistant_name="Nova")
        self.assertEqual(assistant_name(marie, s), "Nova")
        self.assertIn("Tu t'appelles Nova.", user_prompt(marie, s))
        self.assertEqual(marie.public(s)["assistant_name"], "Nova")
        self.assertEqual(clean_assistant_name("  Ma   Nova " + "x" * 50), ("Ma Nova " + "x" * 50)[:40])

    def test_clean_profile(self):
        from core.users import clean_profile
        s = Settings(MCP_CLIENT_ENABLED=False, AUTH_INSTRUCTIONS_MAX_CHARS=5)
        self.assertEqual(clean_profile("  Marie   Curie ", " abcdefgh ", s), ("Marie Curie", "abcde"))
        with self.assertRaises(ValueError):
            clean_profile("   ", "", s)

    def test_session_prompt_follows_profile(self):
        seen = []
        core = make_core([])
        original = core.llm.chat

        def chat(messages, **kwargs):
            seen.append(messages[0]["content"])
            return original(messages, **kwargs)

        core.llm.chat = chat
        marie = User("pb_m", "Marie", "member", instructions="Tutoie-moi.")
        session = core.open_session("p", user=marie)
        core.respond(session.id, text="Bonjour")
        self.assertIn("Tu parles avec Marie.", seen[-1])
        self.assertIn("Tutoie-moi.", seen[-1])

        core.set_session_user(session.id, User("pb_m", "Marie", "member", instructions="Vouvoie-moi."))
        core.respond(session.id, text="Encore")
        self.assertIn("Vouvoie-moi.", seen[-1])
        self.assertNotIn("Tutoie-moi.", seen[-1])
        with self.assertRaises(ValueError):
            core.set_session_user(session.id, User("pb_x", "Autre", "member"))


class TestGatewayAccounts(unittest.TestCase):
    def setUp(self):
        self.executed = []
        self.core = make_core(self.executed)
        self.client = TestClient(create_app(self.core, ACCOUNT_SETTINGS))

    def connect(self, ws, **auth):
        ws.send_json({"type": "auth", **auth})
        return ws.receive_json()

    def test_login_then_token_reuse(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, identity="marie@foyer", password="secret", session="m")
        self.assertEqual(ready["type"], "ready")
        self.assertEqual((ready["user"]["name"], ready["user"]["role"], ready["user"]["admin"]), ("Marie", "member", False))
        self.assertTrue(ready["accounts"])
        self.assertEqual(ready["user"]["token"], "tok-marie@foyer")
        with self.client.websocket_connect("/ws") as ws:
            again = self.connect(ws, user_token=ready["user"]["token"], session="m")
        self.assertEqual(again["session"], "m")  # même compte : la conversation est reprise

    def test_bad_credentials_are_refused(self):
        for auth in ({"identity": "marie@foyer", "password": "faux"}, {"user_token": "tok-inconnu"}, {}):
            with self.client.websocket_connect("/ws") as ws:
                event = self.connect(ws, **auth)
                self.assertEqual(event["type"], "error")
                self.assertTrue(event["accounts"])
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    ws.receive_json()
                self.assertEqual(ctx.exception.code, 4401)

    def test_unavailable_directory_is_reported(self):
        with mock.patch.object(FakeDirectory, "login", side_effect=DirectoryUnavailable("PocketBase injoignable")):
            with self.client.websocket_connect("/ws") as ws:
                event = self.connect(ws, identity="marie@foyer", password="secret")
        self.assertIn("injoignable", event["message"])

    def test_settings_and_restart_are_admin_only(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, identity="leo@foyer", password="1234")
            self.assertEqual(ready["tools"], ["volume"])
            for kind in ("get_settings", "update_settings", "list_models", "restart"):
                ws.send_json({"type": kind, "values": {"LLM_HISTORY_MESSAGES": 3}})
                self.assertEqual(ws.receive_json(), {"type": "settings_error", "message": "Réservé aux administrateurs."})
            ws.send_json({"type": "text", "text": "éteins tout"})
            collect_until_done(ws)
        self.assertEqual(self.executed, [])

    def test_profile_update(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, identity="marie@foyer", password="secret")
            self.assertTrue(ready["user"]["profile"])
            ws.send_json({"type": "update_profile", "name": " Marie  C ", "instructions": "Réponds en une phrase."})
            event = ws.receive_json()
            self.assertEqual(event["type"], "profile_saved")
            self.assertEqual((event["user"]["name"], event["user"]["instructions"]), ("Marie C", "Réponds en une phrase."))
            self.assertNotIn("token", event["user"])
            self.assertEqual(event["assistant"]["name"], self.core.settings.ASSISTANT_NAME)
            # Nom de l'assistant choisi par le compte : affiché (assistant.name) et donné au LLM
            ws.send_json({"type": "update_profile", "name": "Marie C", "instructions": "Réponds en une phrase.",
                          "assistant_name": "Nova"})
            event = ws.receive_json()
            self.assertEqual((event["user"]["assistant_name"], event["assistant"]["name"]), ("Nova", "Nova"))
            ws.send_json({"type": "update_profile", "name": "", "instructions": ""})
            self.assertEqual(ws.receive_json()["type"], "profile_error")
        self.assertIn("wakeword", ready)
        session = self.core.get_session(ready["session"])
        self.assertIn("Réponds en une phrase.", session.conversation.user_prompt)
        self.assertIn("Tu t'appelles Nova.", session.conversation.user_prompt)

    def test_master_token_has_no_profile(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, token=TOKEN)
            self.assertFalse(ready["user"]["profile"])
            ws.send_json({"type": "update_profile", "name": "Moi", "instructions": ""})
            self.assertEqual(ws.receive_json()["type"], "profile_error")

    def test_master_token_is_admin(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, token=TOKEN)
            self.assertTrue(ready["user"]["admin"])
            ws.send_json({"type": "get_settings"})
            self.assertEqual(ws.receive_json()["type"], "settings")

    def test_explicit_login_wins_over_stored_master_token(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, token=TOKEN, identity="leo@foyer", password="1234")
        self.assertEqual(ready["user"]["role"], "guest")

    def test_pocketbase_superadmin_ws_commands(self):
        # Un membre non-superadmin est refusé
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, identity="marie@foyer", password="secret")
            self.assertFalse(ready["user"]["superadmin"])
            ws.send_json({"type": "pb_list_users"})
            self.assertEqual(ws.receive_json()["type"], "pb_admin_error")

        # Un superadmin PocketBase peut lister, créer, modifier et supprimer des utilisateurs
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws, identity="boss@foyer", password="super")
            self.assertTrue(ready["user"]["superadmin"])
            self.assertTrue(ready["user"]["admin"])
            self.assertEqual(ready["user"]["email"], "boss@foyer")

            ws.send_json({"type": "pb_list_users"})
            listed = ws.receive_json()
            self.assertEqual(listed["type"], "pb_users")
            self.assertEqual(len(listed["users"]), 1)

            ws.send_json({"type": "pb_create_user", "email": "paul@foyer", "password": "password123", "name": "Paul", "role": "guest"})
            created = ws.receive_json()
            self.assertEqual(created["type"], "pb_user_saved")
            self.assertEqual(len(created["users"]), 2)
            paul_id = created["user"]["id"]

            ws.send_json({"type": "pb_update_user", "id": paul_id, "role": "admin"})
            updated = ws.receive_json()
            self.assertEqual(updated["type"], "pb_user_saved")
            self.assertEqual(updated["user"]["role"], "admin")

            ws.send_json({"type": "pb_delete_user", "id": paul_id})
            deleted = ws.receive_json()
            self.assertEqual(deleted["type"], "pb_user_deleted")
            self.assertEqual(len(deleted["users"]), 1)


class VoiceTTS:
    """Fournisseur TTS factice avec deux voix ; retient la voix de chaque synthèse."""
    used: list = []

    def __new__(cls, settings):
        import numpy as np
        from audio.tts import TTSProvider

        class _Provider(TTSProvider):
            @classmethod
            def describe(cls, s):
                return "Voix factices"

            def voices(self):
                return [{"id": "fr_FR-tom-medium", "label": "tom", "default": True},
                        {"id": "fr_FR-upmc-medium", "label": "upmc", "default": False}]

            def synthesize(self, text, voice=None):
                VoiceTTS.used.append(voice)
                return np.zeros(100, dtype=np.int16), 8000

        return _Provider(settings)


class TestVoices(unittest.TestCase):
    def setUp(self):
        from audio.tts import TextToSpeech
        VoiceTTS.used = []
        self.core = make_core([])
        self.core._tts = TextToSpeech(SETTINGS, provider=VoiceTTS(SETTINGS))
        self.client = TestClient(create_app(self.core, ACCOUNT_SETTINGS))

    def test_list_piper_voices(self):
        import tempfile
        import audio.tts as tts
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tts, "VOICES_DIR", Path(tmp)):
            for name in ("fr_FR-siwis-medium", "fr_FR-tom-medium", "sans-config"):
                (Path(tmp) / f"{name}.onnx").write_bytes(b"")
            for name in ("fr_FR-siwis-medium", "fr_FR-tom-medium"):
                (Path(tmp) / f"{name}.onnx.json").write_text("{}")
            voices = tts.list_piper_voices(f"{tmp}/fr_FR-tom-medium.onnx")
        self.assertEqual([v["id"] for v in voices], ["fr_FR-siwis-medium", "fr_FR-tom-medium"])
        self.assertEqual(voices[0]["label"], "siwis (fr_FR, medium)")
        self.assertEqual([v["default"] for v in voices], [False, True])

    def test_piper_voice_cache(self):
        import audio.tts as tts
        piper = tts.PiperTTS.__new__(tts.PiperTTS)
        piper.settings = Settings(MCP_CLIENT_ENABLED=False, TTS_VOICE_CACHE_SIZE=1)
        piper.voice, piper.default_id = "voix-défaut", "a"
        piper._cache = tts.OrderedDict()
        loads = []
        piper._load = lambda path, config_path: loads.append(Path(path).stem) or f"modèle-{Path(path).stem}"
        voices = [{"id": i, "label": i, "default": i == "a"} for i in ("a", "b", "c")]
        with mock.patch.object(tts.PiperTTS, "voices", return_value=voices):
            self.assertEqual(piper._voice(None), "voix-défaut")
            self.assertEqual(piper._voice("a"), "voix-défaut")
            self.assertEqual(piper._voice("../../etc/passwd"), "voix-défaut")  # jamais un chemin
            self.assertEqual(piper._voice("b"), "modèle-b")
            self.assertEqual(piper._voice("b"), "modèle-b")
            piper._voice("c")
            self.assertEqual(list(piper._cache), ["c"])  # une seule voix supplémentaire gardée
        self.assertEqual(loads, ["b", "c"])

    def test_profile_voice_is_used_for_spoken_replies(self):
        with self.client.websocket_connect("/ws") as ws:
            ready = self.connect(ws)
            self.assertEqual([v["id"] for v in ready["voices"]], ["fr_FR-tom-medium", "fr_FR-upmc-medium"])
            ws.send_json({"type": "update_profile", "name": "Marie", "instructions": "", "voice": "inconnue"})
            self.assertEqual(ws.receive_json()["type"], "profile_error")
            ws.send_json({"type": "update_profile", "name": "Marie", "instructions": "", "voice": "fr_FR-upmc-medium"})
            self.assertEqual(ws.receive_json()["user"]["voice"], "fr_FR-upmc-medium")
            ws.send_json({"type": "text", "text": "Bonjour", "speak": True})
            collect_until_done(ws)
            ws.send_json({"type": "preview_voice", "voice": "fr_FR-tom-medium"})
            event = ws.receive_json()
            self.assertEqual((event["type"], event["voice"]), ("voice_preview", "fr_FR-tom-medium"))
        self.assertIn("fr_FR-upmc-medium", VoiceTTS.used)
        self.assertEqual(VoiceTTS.used[-1], "fr_FR-tom-medium")

    def test_uninstalled_voice_falls_back_to_default(self):
        session = self.core.open_session("v", user=User("pb_m", "Marie", "member", voice="supprimée"))
        self.assertIsNone(self.core.session_voice(session.id))
        self.core.set_session_user("v", User("pb_m", "Marie", "member", voice="fr_FR-upmc-medium"))
        self.assertEqual(self.core.session_voice("v"), "fr_FR-upmc-medium")

    def test_master_token_gets_no_voice_list(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": TOKEN})
            self.assertEqual(ws.receive_json()["voices"], [])

    def connect(self, ws):
        ws.send_json({"type": "auth", "identity": "marie@foyer", "password": "secret"})
        return ws.receive_json()


class MemoryHistory:
    """Historique factice (même interface que core.history.HistoryStore), en mémoire."""

    def __init__(self):
        self.rows = []

    def applies(self, user):
        return user is not None and user.has_profile

    def load_latest(self, user):
        mine = [r for r in self.rows if r["user"] == user.id]
        if not mine:
            return None, []
        conversation = mine[-1]["conversation"]
        return conversation, [{k: r[k] for k in ("role", "content", "turn", "tools") if k in r} for r in mine if r["conversation"] == conversation]

    def load_conversation(self, user, conversation_id):
        mine = [r for r in self.rows if r["user"] == getattr(user, "id", None) and r["conversation"] == conversation_id]
        return conversation_id, [{k: r[k] for k in ("role", "content", "turn", "tools") if k in r} for r in mine]

    def list_conversations(self, user, limit=300):
        conv_map = {}
        for r in self.rows:
            if r["user"] != getattr(user, "id", None):
                continue
            cid = r["conversation"]
            if cid not in conv_map:
                conv_map[cid] = {"id": cid, "title": "", "created": "", "updated": "", "message_count": 0, "tools": [], "_msgs": []}
            conv_map[cid]["message_count"] += 1
            conv_map[cid]["_msgs"].append(r)
        res = []
        for cid, entry in conv_map.items():
            first_user = next((m.get("content", "") for m in entry.pop("_msgs") if m.get("role") == "user"), "")
            entry["title"] = first_user or "Nouvelle conversation"
            res.append(entry)
        return res

    def delete_conversation(self, user, conversation_id):
        self.rows = [r for r in self.rows if not (r["user"] == getattr(user, "id", None) and r["conversation"] == conversation_id)]

    def append(self, user, conversation, messages):
        if self.applies(user):
            self.rows += [{"user": user.id, "conversation": conversation, **m} for m in messages]

    def forget(self, user, conversation, turns, role=None):
        turns = set(turns)
        self.rows = [r for r in self.rows if not (r["user"] == getattr(user, "id", None) and r["turn"] in turns
                                                  and (role is None or r["role"] == role))]

    def edit_answer(self, user, conversation, turn, text):
        for r in self.rows:
            if r["user"] == getattr(user, "id", None) and r["turn"] == turn and r["role"] == "assistant":
                r["content"] = text

    def flush(self, timeout=0):
        pass


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.store = MemoryHistory()
        self.marie = User("pb_m", "Marie", "member", "tok-marie@foyer")

    def core(self):
        core = make_core([])
        core.history = self.store
        return core

    def test_conversation_survives_a_new_session(self):
        core = self.core()
        session = core.open_session(None, user=self.marie)
        self.assertEqual(core.restore_history(session.id), [])
        core.respond(session.id, text="Bonjour", turn="t1")
        core.respond(session.id, text="Il pleut", turn="t2")
        core.respond(session.id, text="Sans numéro")  # numéro attribué par le serveur pour l'enregistrer
        core.edit_answer(session.id, "t2", "Réponse corrigée.")
        core.forget(session.id, ["t1"])

        other = self.core()
        restored = other.open_session(None, user=self.marie)
        messages = other.restore_history(restored.id)
        self.assertEqual([m["content"] for m in messages],
                         ["Il pleut", "Réponse corrigée.", "Sans numéro", "Écho : Sans numéro"])
        self.assertTrue(messages[2]["turn"])
        self.assertEqual(restored.conversation_id, session.conversation_id)
        self.assertEqual(len(restored.conversation.older + restored.conversation.history), 4)

    def test_new_conversation_keeps_the_old_one(self):
        core = self.core()
        session = core.open_session(None, user=self.marie)
        core.respond(session.id, text="Ancien sujet", turn="a")
        old = session.conversation_id
        core.reset(session.id)
        self.assertNotEqual(session.conversation_id, old)
        core.respond(session.id, text="Nouveau sujet", turn="b")
        self.assertEqual({r["conversation"] for r in self.store.rows}, {old, session.conversation_id})
        fresh = self.core()
        s2 = fresh.open_session(None, user=self.marie)
        self.assertEqual([m["content"] for m in fresh.restore_history(s2.id)], ["Nouveau sujet", "Écho : Nouveau sujet"])

    def test_sessions_without_account_are_not_stored(self):
        core = self.core()
        core.respond("anonyme", text="Bonjour")
        local = core.open_session("local", persistent=True, user=local_user(SETTINGS))
        core.respond(local.id, text="Bonjour")
        self.assertEqual(self.store.rows, [])
        # La conversation en mémoire est tout de même renvoyée (rechargement de la page)
        self.assertEqual(len(core.restore_history("anonyme")), 2)

    def test_ready_carries_the_conversation(self):
        core = self.core()
        session = core.open_session(None, user=User("pb_marie@foyer", "Marie", "member", "tok-marie@foyer"))
        core.respond(session.id, text="Bonjour", turn="t1")
        app_core = self.core()
        client = TestClient(create_app(app_core, ACCOUNT_SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "identity": "marie@foyer", "password": "secret"})
            ready = ws.receive_json()
        self.assertEqual([m["content"] for m in ready["history"]], ["Bonjour", "Écho : Bonjour"])

    def test_list_load_delete_conversations(self):
        core = self.core()
        session = core.open_session(None, user=self.marie)
        core.respond(session.id, text="Première conversation", turn="c1_t1")
        c1_id = session.conversation_id

        core.reset(session.id)
        c2_id = session.conversation_id
        core.respond(session.id, text="Deuxième conversation", turn="c2_t1")

        convs = core.list_conversations(session.id)
        self.assertEqual(len(convs), 2)
        conv_ids = {c["id"] for c in convs}
        self.assertIn(c1_id, conv_ids)
        self.assertIn(c2_id, conv_ids)

        # Basculer vers c1
        loaded = core.load_conversation(session.id, c1_id)
        self.assertEqual(session.conversation_id, c1_id)
        self.assertEqual(loaded[0]["content"], "Première conversation")

        # Supprimer c1
        core.delete_conversation(session.id, c1_id)
        convs_after = core.list_conversations(session.id)
        self.assertEqual(len(convs_after), 1)
        self.assertEqual(convs_after[0]["id"], c2_id)

    def test_filters_reject_unsafe_turns(self):
        from core.history import HistoryStore
        store = HistoryStore(Settings(MCP_CLIENT_ENABLED=False, AUTH_PROVIDER="pocketbase"))
        self.assertIsNone(store._turn_filter(self.marie, "c1", ['" || user != "'], None))
        self.assertEqual(store._turn_filter(self.marie, "c1", ["t-1"], "assistant"),
                         'user = "m" && conversation = "c1" && (turn = "t-1") && role = "assistant"')
        self.assertIsNone(HistoryStore(Settings(MCP_CLIENT_ENABLED=False)).append(self.marie, "c1", []))


class _PocketBaseStub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/collections/users/records") and self.headers.get("Authorization") in ("super-jwt-1", "super-jwt-2"):
            record = {"id": "sup_usr", "email": "root@foyer", "name": "Root", "role": "admin"}
            self._reply(200, {"items": [record]})
        else:
            self._reply(404, {"message": "Not found."})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        record = {"id": "abc", "email": "marie@foyer", "name": "Marie", "role": ""}
        if self.path == "/api/collections/users/auth-with-password" and body == {"identity": "marie@foyer", "password": "secret"}:
            status, data = 200, {"token": "jwt-1", "record": record}
        elif self.path == "/api/collections/users/auth-refresh" and self.headers.get("Authorization") == "jwt-1":
            status, data = 200, {"token": "jwt-2", "record": {**record, "role": "admin"}}
        elif self.path == "/api/collections/_superusers/auth-with-password" and body == {"identity": "root@foyer", "password": "rootpass"}:
            status, data = 200, {"token": "super-jwt-1", "record": {"id": "s1", "email": "root@foyer"}}
        elif self.path == "/api/collections/_superusers/auth-refresh" and self.headers.get("Authorization") == "super-jwt-1":
            status, data = 200, {"token": "super-jwt-2", "record": {"id": "s1", "email": "root@foyer"}}
        elif self.path == "/api/collections/users/records" and self.headers.get("Authorization") == "super-jwt-1":
            status, data = 200, {"id": "new_u", "email": body.get("email", ""), "name": body.get("name", ""), "role": body.get("role", "member")}
        elif self.path.startswith("/api/collections/users/") or self.path.startswith("/api/collections/_superusers/"):
            status, data = 400, {"message": "Failed to authenticate."}
        else:
            status, data = 404, {"message": "Missing collection."}
        self._reply(status, data)

    def do_PATCH(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/collections/users/records/abc" and self.headers.get("Authorization") in ("jwt-1", "super-jwt-1"):
            self._reply(200, {"id": "abc", "email": "marie@foyer", "role": "member", **body})
        else:
            self._reply(404, {"message": "The requested resource wasn't found."})

    def do_DELETE(self):
        if self.path == "/api/collections/users/records/abc" and self.headers.get("Authorization") == "super-jwt-1":
            self.send_response(204)
            self.end_headers()
        else:
            self._reply(404, {"message": "Not found."})

    def _reply(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class TestPocketBaseDirectory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _PocketBaseStub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def directory(self, **overrides):
        return PocketBaseDirectory(Settings(POCKETBASE_URL=self.url, MCP_CLIENT_ENABLED=False, **overrides))

    def test_login_and_refresh(self):
        user = self.directory().login("marie@foyer", "secret")
        self.assertEqual((user.id, user.name, user.role, user.token), ("pb_abc", "Marie", "member", "jwt-1"))
        refreshed = self.directory().refresh("jwt-1")
        self.assertEqual((refreshed.role, refreshed.token), ("admin", "jwt-2"))

    def test_superadmin_login_refresh_and_management(self):
        directory = self.directory()
        super_user = directory.login("root@foyer", "rootpass")
        self.assertTrue(super_user.superadmin)
        self.assertEqual((super_user.id, super_user.role, super_user.email, super_user.token),
                         ("pb_sup_usr", "admin", "root@foyer", "super-jwt-1"))

        refreshed = directory.refresh("super-jwt-1")
        self.assertTrue(refreshed.superadmin)
        self.assertEqual(refreshed.token, "super-jwt-2")

        users = directory.list_users(super_user)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["email"], "root@foyer")

        created = directory.create_user(super_user, "nouveau@foyer", "motdepasse8", "Nouveau", "member")
        self.assertEqual(created["email"], "nouveau@foyer")

        updated = directory.update_user_role(super_user, "abc", "admin")
        self.assertEqual(updated["role"], "admin")

        directory.delete_user(super_user, "abc")

    def test_update_profile(self):
        directory = self.directory()
        user = directory.login("marie@foyer", "secret")
        updated = directory.update_profile(user, "Marie C", "Court.")
        self.assertEqual((updated.name, updated.instructions, updated.token), ("Marie C", "Court.", "jwt-1"))
        with self.assertRaises(AuthError):  # 404 = règle d'accès refusée, pas un annuaire absent
            directory.update_profile(User("pb_abc", "Marie", "member", "expiré"), "Marie", "")

    def test_errors(self):
        with self.assertRaises(AuthError):
            self.directory().login("marie@foyer", "faux")
        with self.assertRaises(AuthError):
            self.directory().refresh("expiré")
        with self.assertRaises(DirectoryUnavailable):
            self.directory(POCKETBASE_USERS_COLLECTION="absente").login("marie@foyer", "secret")
        with self.assertRaises(DirectoryUnavailable):
            PocketBaseDirectory(Settings(POCKETBASE_URL="http://127.0.0.1:9", MCP_CLIENT_ENABLED=False)).login("a", "b")


class TestPocketBaseLauncher(unittest.TestCase):
    """core/pocketbase.py : nom d'archive, vérification de l'archive, conditions de lancement (sans vrai binaire)."""

    def test_asset_name(self):
        import core.pocketbase as pb
        with mock.patch.object(pb.sys, "platform", "linux"), mock.patch.object(pb.platform, "machine", return_value="x86_64"):
            self.assertEqual(pb.asset_name("0.40.6"), "pocketbase_0.40.6_linux_amd64.zip")
        with mock.patch.object(pb.sys, "platform", "win32"), mock.patch.object(pb.platform, "machine", return_value="ARM64"):
            self.assertEqual(pb.asset_name("0.40.6"), "pocketbase_0.40.6_windows_arm64.zip")
        with mock.patch.object(pb.platform, "machine", return_value="mips"), self.assertRaises(RuntimeError):
            pb.asset_name("0.40.6")

    def test_install_rejects_bad_checksum(self):
        import hashlib, io, tempfile, zipfile
        import core.pocketbase as pb
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(pb.binary_path().name, b"binaire")
        archive = buf.getvalue()
        name = pb.asset_name("9.9.9")
        s = Settings(POCKETBASE_VERSION="9.9.9", MCP_CLIENT_ENABLED=False)

        def fake_download(digest):
            return lambda url: f"{digest}  {name}\n".encode() if url.endswith("checksums.txt") else archive

        binary = pb.binary_path().name  # pocketbase.exe sous Windows
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pb, "PB_DIR", Path(tmp)), \
                mock.patch.object(pb, "binary_path", return_value=Path(tmp) / binary), \
                mock.patch.object(pb, "installed_version", return_value=None):
            with mock.patch.object(pb, "_download", fake_download("0" * 64)), self.assertRaises(RuntimeError):
                pb.install(s)
            self.assertFalse((Path(tmp) / binary).exists())
            with mock.patch.object(pb, "_download", fake_download(hashlib.sha256(archive).hexdigest())):
                target = pb.install(s)
            self.assertEqual(target.read_bytes(), b"binaire")

    def test_ensure_running_conditions(self):
        import core.pocketbase as pb
        base = dict(MCP_CLIENT_ENABLED=False, AUTH_PROVIDER="pocketbase")
        with mock.patch.object(pb.subprocess, "Popen") as popen:
            self.assertIsNone(pb.ensure_running(Settings(MCP_CLIENT_ENABLED=False)))  # comptes désactivés
            self.assertIsNone(pb.ensure_running(Settings(**base, POCKETBASE_AUTOSTART=False)))
            with mock.patch.object(pb, "is_running", return_value=True):
                self.assertIsNone(pb.ensure_running(Settings(**base)))  # déjà lancé : réutilisé
            with mock.patch.object(pb, "is_running", return_value=False):
                self.assertIsNone(pb.ensure_running(Settings(**base, POCKETBASE_URL="http://nas.local:8090")))
            popen.assert_not_called()

    def test_serve_command(self):
        import core.pocketbase as pb
        cmd = pb.serve_command(Settings(POCKETBASE_URL="http://127.0.0.1:8091", MCP_CLIENT_ENABLED=False))
        self.assertEqual(cmd[1:4], ["serve", "--http", "127.0.0.1:8091"])
        self.assertIn("--automigrate=false", cmd)


class TestHistoryStoreWrites(unittest.TestCase):
    """Écritures de HistoryStore : repli sans « tools » seulement si PocketBase refuse l'enregistrement."""

    def setUp(self):
        from core.history import HistoryStore
        self.store = HistoryStore(Settings(AUTH_PROVIDER="pocketbase", MCP_CLIENT_ENABLED=False))
        self.user = User("pb_m", "Marie", "member", token="jeton")
        self.message = [{"role": "assistant", "content": "ok", "turn": "t1", "tools": [{"name": "volume"}]}]

    def run_append(self, errors):
        bodies = []

        def request(user, path="", **kwargs):
            bodies.append(kwargs.get("body"))
            if errors:
                raise errors.pop(0)
            return {}
        with mock.patch.object(type(self.store), "_request", side_effect=request, autospec=False):
            self.store.append(self.user, "c1", self.message).result(5)
        return bodies

    def test_refused_record_retried_without_tools(self):
        from core.users import AuthError
        bodies = self.run_append([AuthError("400")])
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("tools", bodies[1])

    def test_unreachable_server_not_retried(self):
        from core.users import DirectoryUnavailable
        self.assertEqual(len(self.run_append([DirectoryUnavailable("injoignable")])), 1)


if __name__ == "__main__":
    unittest.main()
