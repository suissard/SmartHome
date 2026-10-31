#!/usr/bin/env python3
"""
Tests des modèles de décision (llm/decision.py), des paramètres modifiables à chaud (core/settings_store.py)
et de leurs messages WebSocket, avec un modèle de décision factice : aucun modèle appelé, aucune action réelle.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.registry import get_command_by_tag
from core import settings_store
from core.assistant import AssistantCore
from core.config import Settings, load_settings
from core.tools import Tool, ToolRegistry, _action_tool
from gateway.app import create_app
from llm.decision import NO_COMMAND, argument_questions, decidable_tools, tool_label
from llm.llm import Conversation
from llm.providers import LLMProvider, LLMResponse, _in_decision_list

SETTINGS = Settings(MCP_CLIENT_ENABLED=False, OLLAMA_MODEL="nimble", LLM_DECISION_MODELS="nimble")


class FakeDecider(LLMProvider):
    """Modèle de décision : répond aux questions d'après une table {question: réponse}, et mémorise les questions."""

    def __init__(self, answers, settings=SETTINGS):
        super().__init__(settings)
        self.model = settings.OLLAMA_MODEL
        self.answers, self.asked = answers, []

    @classmethod
    def describe(cls, settings):
        return "FakeDecider"

    def is_decision_model(self, model=None):
        return _in_decision_list(model or self.model, self.settings)

    def decide(self, state, questions):
        self.asked.append(questions)
        return {name: self.answers[name] for name in questions}

    def chat(self, messages, **kwargs):
        return LLMResponse(text="réponse rédigée")


def registry(executed):
    tools = ToolRegistry(SETTINGS)
    tools.add(Tool("volume", "Régler le volume sonore : monter ou baisser.", {
        "type": "object", "properties": {"args": {"type": "string"}}, "required": ["args"],
    }, lambda a: executed.append(("volume", a)) or "Succès.", decision_choices={"40": "40 %", "up": "plus fort"}))
    tools.add(Tool("notify", "Afficher une notification.", {
        "type": "object", "properties": {"args": {"type": "string"}}, "required": ["args"],
    }, lambda a: executed.append(("notify", a)) or "Succès."))
    tools.add(Tool("shutdown", "Éteindre l'ordinateur.", {"type": "object", "properties": {}},
                   lambda a: executed.append(("shutdown", a)) or "Succès.", danger="confirm"))
    tools.add(Tool("lights", "Allumer une pièce.", {"type": "object", "properties": {
        "room": {"type": "string", "enum": ["salon", "cuisine"]},
        "on": {"type": "boolean"},
        "level": {"type": "integer", "minimum": 1, "maximum": 5},
        "note": {"type": "string"},  # libre mais facultatif : ignoré
    }, "required": ["room"]}, lambda a: executed.append(("lights", a)) or "Succès."))
    return tools


def choice(key, p=0.9):
    return {"type": "choice", "choice": key, "probabilities": {key: p}}


class TestDecisionModel(unittest.TestCase):
    def test_decision_list_matches_base_name(self):
        self.assertTrue(_in_decision_list("nimble:latest", SETTINGS))
        self.assertTrue(_in_decision_list("Nimble", SETTINGS))
        self.assertFalse(_in_decision_list("qwen2.5:7b", SETTINGS))

    def test_free_text_required_argument_excludes_tool(self):
        candidates = decidable_tools(registry([]).all())
        self.assertEqual(sorted(candidates), ["lights", "shutdown", "volume"])
        questions = argument_questions(registry([]).get("lights"))
        self.assertEqual(sorted(questions), ["level", "on", "room"])
        self.assertEqual(questions["level"].question["criteria"], ["1", "2", "3", "4", "5"])

    def test_command_and_arguments_are_chosen_then_summarized(self):
        executed = []
        decider = FakeDecider({"command": choice("volume", 0.98), "args": choice("40")})
        conversation = Conversation(decider, SETTINGS, tools=registry(executed))
        text = conversation.ask("mets le volume à 40")
        self.assertEqual(executed, [("volume", {"args": "40"})])
        self.assertEqual(text, "Compris : régler le volume sonore (40 %).")
        self.assertIn(NO_COMMAND, decider.asked[0]["command"]["criteria"])
        self.assertEqual(conversation.history[-1]["content"], text)
        self.assertTrue(conversation.last_tool_results[0].executed)

    def test_typed_arguments(self):
        executed = []
        decider = FakeDecider({
            "command": choice("lights"), "room": choice("cuisine"),
            "on": {"type": "noul", "noul": 0.8}, "level": {"type": "score", "score": 2.6},
        })
        Conversation(decider, SETTINGS, tools=registry(executed)).ask("allume la cuisine assez fort")
        self.assertEqual(executed, [("lights", {"room": "cuisine", "on": True, "level": 4})])

    def test_no_command_or_low_confidence_is_not_understood(self):
        for answer in (choice(NO_COMMAND), choice("volume", 0.3)):
            executed = []
            decider = FakeDecider({"command": answer, "args": choice("40")})
            text = Conversation(decider, SETTINGS, tools=registry(executed)).ask("quelle heure est-il ?")
            self.assertEqual(text, SETTINGS.LLM_DECISION_UNKNOWN_TEXT)
            self.assertEqual(executed, [])
            self.assertEqual(len(decider.asked), 1)  # pas de question sur les arguments

    def test_dangerous_command_goes_through_confirmation(self):
        executed = []
        decider = FakeDecider({"command": choice("shutdown")})
        conversation = Conversation(decider, SETTINGS, tools=registry(executed), confirm=lambda description: False)
        self.assertEqual(conversation.ask("éteins"), "Commande non exécutée : éteindre l'ordinateur.")
        self.assertEqual(executed, [])

    def test_provider_error_becomes_message(self):
        class Broken(FakeDecider):
            def decide(self, state, questions):
                raise RuntimeError("modèle absent")
        text = Conversation(Broken({}), SETTINGS, tools=registry([])).ask("mets le volume")
        self.assertTrue(text.startswith("⚠️") and "modèle absent" in text)

    def test_chat_model_is_unaffected(self):
        decider = FakeDecider({}, Settings(**{**SETTINGS.model_dump(), "OLLAMA_MODEL": "qwen2.5:7b"}))
        decider.model = "qwen2.5:7b"
        self.assertEqual(Conversation(decider, decider.settings, tools=ToolRegistry(SETTINGS)).ask("bonjour"), "réponse rédigée")

    def test_local_actions_expose_closed_choices(self):
        volume = _action_tool(get_command_by_tag("VOLUME"), SETTINGS)
        self.assertIn("40", volume.decision_choices)
        self.assertEqual(tool_label(volume), "régler le volume sonore")
        timer = get_command_by_tag("TIMER")
        for value in timer.decision_choices():
            self.assertTrue(timer.build_args(value), value)  # chaque choix est une durée valide
        self.assertIsNone(_action_tool(get_command_by_tag("NOTIFY"), SETTINGS).decision_choices)


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text("# Modèle\nOLLAMA_MODEL=qwen2.5:7b\nLLM_THINK=false\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_describe_exposes_no_secret_and_types(self):
        fields = {f["name"]: f for g in settings_store.describe(SETTINGS) for f in g["fields"]}
        self.assertFalse(any("TOKEN" in n or "KEY" in n or n.startswith(("GATEWAY_", "MCP_")) for n in fields))
        self.assertEqual(fields["LLM_THINK"]["kind"], "bool")
        self.assertEqual(fields["LLM_TOOL_CALLING"]["options"], ["auto", "native", "tags"])
        self.assertEqual(fields["LLM_DECISION_MIN_CONFIDENCE"]["max"], 1.0)
        self.assertEqual(fields["OLLAMA_MODEL"]["kind"], "model")
        self.assertTrue(fields["LLM_DECISION_MODELS"]["help"])  # commentaire de .env.example

    def test_validation_rejects_unknown_and_invalid(self):
        with self.assertRaises(ValueError):
            settings_store.validate_changes(SETTINGS, {"GATEWAY_AUTH_TOKEN": "x"})
        with self.assertRaises(ValueError):
            settings_store.validate_changes(SETTINGS, {"LLM_DECISION_MIN_CONFIDENCE": 3})
        same, changed = settings_store.validate_changes(SETTINGS, {"OLLAMA_MODEL": "nimble"})
        self.assertEqual((same, changed), (SETTINGS, []))

    def test_saved_values_reload_identically(self):
        new, changed = settings_store.validate_changes(SETTINGS, {
            "OLLAMA_MODEL": "gemma4:12b", "LLM_THINK": True, "LLM_DECISION_MODELS": ["nimble", "tev1"],
            "LLM_DECISION_DONE_TEMPLATE": 'C\'est "fait" : {command} # ok',
        })
        settings_store.save_to_env(new, changed, self.env)
        text = self.env.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Modèle\nOLLAMA_MODEL=gemma4:12b\nLLM_THINK=true\n"))
        reloaded = load_settings(self.env)
        for name in changed:
            self.assertEqual(getattr(reloaded, name), getattr(new, name), name)

    def test_core_applies_live_settings_to_sessions(self):
        decider = FakeDecider({"command": choice("volume"), "args": choice("up")},
                              Settings(**{**SETTINGS.model_dump(), "OLLAMA_MODEL": "qwen2.5:7b"}))
        core = AssistantCore(decider.settings, tools=registry([]), llm=decider, env_file=self.env)
        session = core.open_session("s")
        self.assertEqual(core.respond("s", text="monte le son").text, "réponse rédigée")

        result = core.update_settings({"OLLAMA_MODEL": "nimble", "LLM_HISTORY_MESSAGES": 2, "VAD_ENGINE": "energy"})
        self.assertEqual(sorted(result["changed"]), ["LLM_HISTORY_MESSAGES", "OLLAMA_MODEL", "VAD_ENGINE"])
        self.assertEqual(result["restart"], ["VAD_ENGINE"])
        self.assertIn("OLLAMA_MODEL=nimble", self.env.read_text(encoding="utf-8"))
        decider.model = core.settings.OLLAMA_MODEL  # un vrai fournisseur serait recréé avec le nouveau modèle
        self.assertEqual(session.conversation.max_messages, 2)
        self.assertEqual(core.respond("s", text="monte le son").text, "Compris : régler le volume sonore (plus fort).")
        self.assertTrue(core.model_info()["decision"])


class TestSettingsOverWebSocket(unittest.TestCase):
    def test_get_update_and_list_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            decider = FakeDecider({})
            decider.list_models = lambda: [{"name": "nimble:latest", "capabilities": ["decision"], "size": 1}]
            core = AssistantCore(SETTINGS, tools=registry([]), llm=decider, env_file=env)
            client = TestClient(create_app(core, SETTINGS))
            with client.websocket_connect("/ws") as ws:
                ready = ws.receive_json()
                self.assertEqual(ready["llm"], {"provider": "ollama", "model": "nimble", "decision": True})

                ws.send_json({"type": "list_models"})
                self.assertEqual(ws.receive_json()["models"][0]["name"], "nimble:latest")

                ws.send_json({"type": "get_settings"})
                settings = ws.receive_json()
                self.assertEqual(settings["type"], "settings")
                self.assertTrue(any(g["title"] == "Modèle de décision" for g in settings["groups"]))

                ws.send_json({"type": "update_settings", "values": {"LLM_DECISION_MIN_CONFIDENCE": 0.7}})
                messages = [ws.receive_json() for _ in range(3)]
                kinds = sorted(m["type"] for m in messages)
                self.assertEqual(kinds, ["settings", "settings_changed", "settings_saved"])
                self.assertEqual(core.settings.LLM_DECISION_MIN_CONFIDENCE, 0.7)

                ws.send_json({"type": "update_settings", "values": {"MCP_AUTH_TOKEN": "pirate"}})
                self.assertEqual(ws.receive_json()["type"], "settings_error")


if __name__ == "__main__":
    unittest.main()
