#!/usr/bin/env python3
"""Tests de [GET_SETTINGS] / [SET_SETTING] : l'assistant lit et modifie ses paramètres, toujours avec confirmation."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.modules.assistant_settings import GET_SETTINGS_ACTION, SET_SETTING_ACTION
from core import settings_store
from core.assistant import AssistantCore
from core.config import Settings
from core.tools import ToolCall, ToolRegistry, _action_tool
from core.users import User, admin_user, local_user, tool_policy


class _Base(unittest.TestCase):
    confirm_dangerous = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text("# Vitesse\nTTS_SPEECH_SPEED=1.0\n", encoding="utf-8")
        self.s = Settings(MCP_CLIENT_ENABLED=False, TTS_SPEECH_SPEED=1.0, LLM_HISTORY_MESSAGES=5,
                          ACTIONS_CONFIRM_DANGEROUS=self.confirm_dangerous)
        self.tools = ToolRegistry(self.s)
        for action in (GET_SETTINGS_ACTION, SET_SETTING_ACTION):
            self.tools.add(_action_tool(action, self.s))
        self.core = AssistantCore(self.s, tools=self.tools, env_file=self.env)
        self.events = []
        self.core.events.subscribe(self.events.append)
        self.questions = []

    def tearDown(self):
        settings_store.set_owner(None)
        self.tmp.cleanup()

    def call(self, args, answer=True):
        def confirm(question):
            self.questions.append(question)
            return answer
        return self.tools.call(ToolCall("set_setting", {"args": args}), confirm=confirm)


class TestSetSetting(_Base):
    def test_confirmed_change_is_saved_and_applied(self):
        result = self.call("LLM_HISTORY_MESSAGES=8")
        self.assertTrue(result.executed, result.output)
        self.assertEqual(len(self.questions), 1)
        self.assertIn("« Messages gardés en mémoire »", self.questions[0])
        self.assertIn("« 5 » à « 8 »", self.questions[0])
        self.assertEqual(self.core.settings.LLM_HISTORY_MESSAGES, 8)
        self.assertIn("LLM_HISTORY_MESSAGES=8", self.env.read_text(encoding="utf-8"))
        self.assertTrue(any(e.type == "settings_changed" for e in self.events))

    def test_refused_change_writes_nothing(self):
        result = self.call("TTS_SPEECH_SPEED=1.3", answer=False)
        self.assertFalse(result.executed)
        self.assertEqual(self.core.settings.TTS_SPEECH_SPEED, 1.0)
        self.assertEqual(self.env.read_text(encoding="utf-8"), "# Vitesse\nTTS_SPEECH_SPEED=1.0\n")

    def test_restart_fields_reported(self):
        result = self.call("TTS_SPEECH_SPEED=1.3")
        self.assertIn("(au redémarrage)", self.questions[0])
        self.assertIn("prochain redémarrage", result.output)
        self.assertIn("TTS_SPEECH_SPEED=1.3", self.env.read_text(encoding="utf-8"))

    def test_several_fields_as_json(self):
        result = self.call('{"LLM_HISTORY_MESSAGES": 3, "LLM_THINK": true}')
        self.assertTrue(result.executed, result.output)
        self.assertEqual(len(self.questions), 1)
        self.assertIn(" et ", self.questions[0])
        self.assertEqual((self.core.settings.LLM_HISTORY_MESSAGES, self.core.settings.LLM_THINK), (3, True))

    def test_invalid_or_forbidden_refused_without_asking(self):
        for args in ("LLM_HISTORY_MESSAGES=beaucoup", "OPENROUTER_API_KEY=sk-pirate", "ACTIONS_CONFIRM_DANGEROUS=false",
                     "MCP_AUTH_TOKEN=x", "GATEWAY_HOST=0.0.0.0", "pas un réglage", "LLM_HISTORY_MESSAGES=5"):
            with self.subTest(args=args):
                result = self.call(args)
                self.assertFalse(result.executed)
                self.assertTrue(result.output.startswith("Refusé"), result.output)
        self.assertEqual(self.questions, [])
        self.assertNotIn("sk-pirate", self.env.read_text(encoding="utf-8"))

    def test_without_core_refused(self):
        settings_store.set_owner(None)
        code, _, err = SET_SETTING_ACTION.apply("LLM_HISTORY_MESSAGES=8")
        self.assertEqual(code, 1)
        self.assertIn("indisponible", err)


class TestConfirmationAlwaysAsked(_Base):
    confirm_dangerous = False

    def test_forced_even_when_confirmation_disabled(self):
        result = self.call("LLM_HISTORY_MESSAGES=8", answer=False)
        self.assertFalse(result.executed)
        self.assertEqual(len(self.questions), 1)
        self.assertEqual(self.core.settings.LLM_HISTORY_MESSAGES, 5)

    def test_no_handler_means_refusal(self):
        result = self.tools.call(ToolCall("set_setting", {"args": "LLM_HISTORY_MESSAGES=8"}))
        self.assertFalse(result.executed)
        self.assertEqual(self.core.settings.LLM_HISTORY_MESSAGES, 5)


class TestGetSettings(_Base):
    def test_listing_hides_blocked_fields(self):
        result = self.tools.call(ToolCall("get_settings", {}))
        self.assertTrue(result.executed)
        self.assertIn("LLM_HISTORY_MESSAGES = 5", result.output)
        self.assertNotIn("OPENROUTER_API_KEY", result.output)
        self.assertNotIn("ACTIONS_CONFIRM_DANGEROUS", result.output)
        self.assertEqual(self.questions, [])

    def test_filter(self):
        output = GET_SETTINGS_ACTION.listing("vitesse", self.s)
        self.assertIn("TTS_SPEECH_SPEED", output)
        self.assertNotIn("LLM_HISTORY_MESSAGES", output)

    def test_optional_argument(self):
        self.assertEqual(GET_SETTINGS_ACTION.parameters["required"], [])


class TestTagMode(_Base):
    def test_tag_asks_confirmation_with_values(self):
        from actions.manager import ActionManager
        manager = ActionManager()
        self.assertTrue(manager.process_response("[SET_SETTING LLM_HISTORY_MESSAGES=7] C'est noté.",
                                                 confirm=lambda q: self.questions.append(q) or True))
        self.assertIn("« 5 » à « 7 »", self.questions[0])
        self.assertEqual(self.core.settings.LLM_HISTORY_MESSAGES, 7)


class TestAdminOnly(unittest.TestCase):
    def test_reserved_to_admins(self):
        s = Settings(MCP_CLIENT_ENABLED=False)
        for user in (User("pb_a", "Admin", "admin"), User("pb_s", "Sam", "member", superadmin=True),
                     admin_user(s), local_user(s)):
            with self.subTest(user=user.name):
                policy = tool_policy(user, s)
                self.assertTrue(policy.allows("set_setting", "confirm"))
                self.assertTrue(policy.allows("get_settings", "safe"))
        for user in (User("pb_m", "Marie", "member"), User("pb_g", "Invité", "guest")):
            with self.subTest(user=user.name):
                policy = tool_policy(user, s)
                self.assertFalse(policy.allows("set_setting", "confirm"))
                self.assertFalse(policy.allows("get_settings", "safe"))
                self.assertTrue(policy.allows("volume", "safe"))

    def test_local_microphone_follows_its_role(self):
        s = Settings(MCP_CLIENT_ENABLED=False, AUTH_LOCAL_ROLE="member")
        self.assertFalse(tool_policy(local_user(s), s).allows("set_setting", "confirm"))


if __name__ == "__main__":
    unittest.main()
