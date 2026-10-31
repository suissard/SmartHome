#!/usr/bin/env python3
"""
Tests du registre d'outils unifié, de la politique de confirmation et de la boucle de function calling
(fournisseur LLM factice : aucun modèle n'est appelé, aucune action réelle n'est exécutée).
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import Settings
from core.tools import (
    Tool, ToolCall, ToolRegistry, build_tool_registry, parse_arguments,
    request_confirmation, set_confirmation_handler, _mcp_danger, _expose_mcp_server,
)
from audio.confirm import is_affirmative
from actions.manager import ActionManager
from actions.registry import get_command_by_tag
from llm.llm import Conversation
from llm.providers import LLMProvider, LLMResponse, ToolsNotSupportedError

SETTINGS = Settings(ACTIONS_DYNAMIC_PROMPT=True, LLM_STREAM=False, LLM_TOOL_CALLING="auto", MCP_CLIENT_ENABLED=False)


class ScriptedLLM(LLMProvider):
    """Renvoie une suite de réponses prédéfinies et mémorise les messages reçus."""

    def __init__(self, responses, settings=SETTINGS):
        super().__init__(settings)
        self.responses, self.calls = list(responses), []

    @classmethod
    def describe(cls, settings):
        return "Scripted"

    def chat(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def make_registry(log):
    registry = ToolRegistry(SETTINGS)
    registry.add(Tool("volume", "Régler le volume", {"type": "object", "properties": {}},
                      lambda a: log.append(("volume", a)) or "Succès."))
    registry.add(Tool("shutdown", "Éteindre l'ordinateur", {"type": "object", "properties": {}},
                      lambda a: log.append(("shutdown", a)) or "Succès.", danger="confirm"))
    return registry


class TestConfirmationPolicy(unittest.TestCase):
    def tearDown(self):
        set_confirmation_handler(None)

    def test_dangerous_tool_refused_without_handler(self):
        log = []
        result = make_registry(log).call(ToolCall("shutdown"))
        self.assertFalse(result.executed)
        self.assertEqual(log, [])

    def test_dangerous_tool_runs_only_when_confirmed(self):
        log, asked = [], []
        registry = make_registry(log)
        set_confirmation_handler(lambda d: asked.append(d) or False)
        self.assertFalse(registry.call(ToolCall("shutdown")).executed)
        set_confirmation_handler(lambda d: True)
        self.assertTrue(registry.call(ToolCall("shutdown")).executed)
        self.assertEqual(asked, ["Éteindre l'ordinateur"])
        self.assertEqual([name for name, _ in log], ["shutdown"])

    def test_safe_tool_needs_no_confirmation(self):
        log = []
        self.assertTrue(make_registry(log).call(ToolCall("volume", {"args": "40"})).executed)
        self.assertEqual(log, [("volume", {"args": "40"})])

    def test_confirmation_can_be_disabled(self):
        self.assertTrue(request_confirmation("x", Settings(ACTIONS_CONFIRM_DANGEROUS=False)))

    @patch("subprocess.Popen")
    def test_dangerous_tag_in_text_needs_confirmation(self, mock_popen):
        manager = ActionManager(enabled=True)
        action = {"tag": "SHUTDOWN", "args": "", "definition": get_command_by_tag("SHUTDOWN")}
        self.assertFalse(manager.execute_action(action))
        mock_popen.assert_not_called()

    def test_affirmative_parsing(self):
        words = SETTINGS.ACTIONS_CONFIRM_WORDS
        cancel = SETTINGS.ACTIONS_CANCEL_WORDS
        self.assertTrue(is_affirmative("Oui, vas-y.", words, cancel))
        self.assertFalse(is_affirmative("Oui... non attends", words, cancel))
        self.assertFalse(is_affirmative("Bonjour", words, cancel))


class TestToolRegistry(unittest.TestCase):
    def test_local_actions_exposed_with_danger(self):
        registry = build_tool_registry(SETTINGS, include_mcp=False)
        self.assertEqual(registry.get("shutdown").danger, "confirm")
        self.assertEqual(registry.get("volume").danger, "safe")
        self.assertIn("args", registry.get("volume").parameters["properties"])
        self.assertEqual(registry.get("volume").schema()["function"]["name"], "volume")

    def test_name_collision_is_prefixed(self):
        registry = ToolRegistry(SETTINGS)
        registry.add(Tool("search", "a", {}, lambda a: "", source="local"))
        second = registry.add(Tool("search", "b", {}, lambda a: "", source="web.srv"))
        self.assertEqual(second.name, "web_srv__search")

    def test_mcp_danger_from_annotations_and_config(self):
        ro = SimpleNamespace(annotations=SimpleNamespace(read_only_hint=True, destructive_hint=None))
        non_destructive = SimpleNamespace(annotations=SimpleNamespace(read_only_hint=False, destructive_hint=False))
        unannotated = SimpleNamespace(annotations=None)
        self.assertEqual(_mcp_danger(ro, {}), "safe")
        self.assertEqual(_mcp_danger(non_destructive, {}), "safe")
        self.assertEqual(_mcp_danger(unannotated, {}), "confirm")
        self.assertEqual(_mcp_danger(unannotated, {"tool_danger": "safe"}), "safe")

    def test_smarthome_own_server_not_exposed(self):
        self.assertFalse(_expose_mcp_server("self", {"args": ["mcp_server.py", "--transport", "stdio"]}))
        self.assertFalse(_expose_mcp_server("x", {"expose_to_llm": False}))
        self.assertTrue(_expose_mcp_server("weather", {"command": "npx", "args": ["server-weather"]}))

    def test_parse_arguments(self):
        self.assertEqual(parse_arguments('{"args": "40"}'), {"args": "40"})
        self.assertEqual(parse_arguments(""), {})
        self.assertEqual(parse_arguments("40"), {"args": 40})


class TestToolLoop(unittest.TestCase):
    def test_tool_call_then_final_answer(self):
        log = []
        llm = ScriptedLLM([
            LLMResponse(tool_calls=[ToolCall("volume", {"args": "40"}, id="c1")]),
            LLMResponse(text="Volume réglé à 40%."),
        ])
        conv = Conversation(llm, SETTINGS, tools=make_registry(log))
        self.assertEqual(conv.ask("Mets le volume à 40"), "Volume réglé à 40%.")
        self.assertEqual(log, [("volume", {"args": "40"})])
        second_messages = llm.calls[1][0]
        self.assertEqual(second_messages[-2]["role"], "assistant")
        self.assertEqual(second_messages[-1], {"role": "tool", "tool_call_id": "c1", "content": "Succès."})
        self.assertIsNotNone(llm.calls[0][1]["tools"])
        self.assertIn("OUTILS", llm.calls[0][0][0]["content"])
        # L'historique ne garde que la demande et la réponse finale
        self.assertEqual([m["role"] for m in conv.history], ["user", "assistant"])

    def test_max_rounds_stops_loop(self):
        log = []
        looping = [LLMResponse(tool_calls=[ToolCall("volume", {}, id=str(i))]) for i in range(SETTINGS.LLM_MAX_TOOL_ROUNDS)]
        conv = Conversation(ScriptedLLM(looping), SETTINGS, tools=make_registry(log))
        self.assertIn("volume", conv.ask("boucle"))
        self.assertEqual(len(log), SETTINGS.LLM_MAX_TOOL_ROUNDS)

    def test_fallback_to_tags_when_tools_unsupported(self):
        llm = ScriptedLLM([ToolsNotSupportedError("does not support tools"), LLMResponse(text="[VOLUME 40] C'est fait.")])
        conv = Conversation(llm, SETTINGS, tools=make_registry([]))
        self.assertEqual(conv.ask("volume 40"), "[VOLUME 40] C'est fait.")
        self.assertEqual(conv.tool_mode, "tags")
        self.assertIsNone(llm.calls[1][1]["tools"])
        self.assertIn("[VOLUME", llm.calls[1][0][0]["content"])

    def test_tools_can_be_disabled_per_call(self):
        llm = ScriptedLLM([LLMResponse(text="ok")])
        Conversation(llm, SETTINGS, tools=make_registry([])).ask("x", use_tools=False)
        self.assertIsNone(llm.calls[0][1]["tools"])


if __name__ == "__main__":
    unittest.main()
