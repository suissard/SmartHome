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

PASSWORDS = {"marie@foyer": ("secret", "member"), "leo@foyer": ("1234", "guest")}


@USER_DIRECTORIES.register("fake_test")
class FakeDirectory(UserDirectory):
    """Annuaire en mémoire : jeton de compte = « tok-<identifiant> »."""

    def _user(self, identity):
        return User(f"pb_{identity}", identity.split("@")[0].title(), PASSWORDS[identity][1], f"tok-{identity}")

    def login(self, identity, password):
        if PASSWORDS.get(identity, (None,))[0] != password:
            raise AuthError("Identifiants refusés.")
        return self._user(identity)

    def refresh(self, token):
        identity = token.removeprefix("tok-")
        if identity not in PASSWORDS:
            raise AuthError("Identifiants refusés.")
        return self._user(identity)


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


class _PocketBaseStub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        record = {"id": "abc", "email": "marie@foyer", "name": "Marie", "role": ""}
        if self.path == "/api/collections/users/auth-with-password" and body == {"identity": "marie@foyer", "password": "secret"}:
            status, data = 200, {"token": "jwt-1", "record": record}
        elif self.path == "/api/collections/users/auth-refresh" and self.headers.get("Authorization") == "jwt-1":
            status, data = 200, {"token": "jwt-2", "record": {**record, "role": "admin"}}
        elif self.path.startswith("/api/collections/users/"):
            status, data = 400, {"message": "Failed to authenticate."}
        else:
            status, data = 404, {"message": "Missing collection."}
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

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pb, "PB_DIR", Path(tmp)), \
                mock.patch.object(pb, "binary_path", return_value=Path(tmp) / "pocketbase"), \
                mock.patch.object(pb, "installed_version", return_value=None):
            with mock.patch.object(pb, "_download", fake_download("0" * 64)), self.assertRaises(RuntimeError):
                pb.install(s)
            self.assertFalse((Path(tmp) / "pocketbase").exists())
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


if __name__ == "__main__":
    unittest.main()
