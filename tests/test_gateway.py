#!/usr/bin/env python3
"""
Tests du cœur AssistantCore (sessions, pipeline, événements) et de la passerelle WebSocket / HTTP,
avec des composants factices (aucun modèle chargé, aucune action réelle).
"""

import base64
import sys
import threading
import unittest
from pathlib import Path

import numpy as np
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.assistant import AssistantCore
from core.config import Settings
from core.tools import Tool, ToolCall, ToolRegistry
from gateway.app import create_app
from llm.providers import LLMProvider, LLMResponse
from audio.tts import TextToSpeech, TTSProvider

SETTINGS = Settings(LLM_STREAM=True, LLM_TOOL_CALLING="native", MCP_CLIENT_ENABLED=False, GATEWAY_CONFIRM_TIMEOUT=5)
TOKEN = "jeton-de-test"


class RuleLLM(LLMProvider):
    """« éteins » -> outil shutdown ; « volume » -> outil volume ; sinon écho. Répond après un résultat d'outil."""

    def __init__(self):
        super().__init__(SETTINGS)
        self.lock = threading.Lock()

    @classmethod
    def describe(cls, settings):
        return "Rule"

    def chat(self, messages, *, tools=None, audio_wav=None, on_token=None, **kwargs):
        last = messages[-1]
        if last["role"] == "tool":
            text = f"Résultat : {last['content']}"
        else:
            prompt = last["content"] or ""
            if tools and "éteins" in prompt:
                return LLMResponse(tool_calls=[ToolCall("shutdown", {}, id="c1")])
            if tools and "volume" in prompt:
                return LLMResponse(tool_calls=[ToolCall("volume", {"args": "40"}, id="c1")])
            text = f"Écho : {prompt}"
        for word in text.split(" "):
            if on_token:
                on_token(word + " ")
        return LLMResponse(text=text)


class FakeSTT:
    passthrough = False

    def transcribe(self, wav):
        return "transcription factice"


class FakeTTS(TTSProvider):
    @classmethod
    def describe(cls, settings):
        return "Fake"

    def synthesize(self, text):
        return np.zeros(100, dtype=np.int16), 8000


def make_core(executed):
    tools = ToolRegistry(SETTINGS)
    tools.add(Tool("volume", "Régler le volume", {"type": "object", "properties": {}},
                   lambda a: executed.append("volume") or "Succès."))
    tools.add(Tool("shutdown", "Éteindre l'ordinateur", {"type": "object", "properties": {}},
                   lambda a: executed.append("shutdown") or "Succès.", danger="confirm"))
    return AssistantCore(SETTINGS, stt=FakeSTT(), tts=TextToSpeech(SETTINGS, provider=FakeTTS(SETTINGS)),
                         tools=tools, llm=RuleLLM())


def collect_until_done(ws):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == "done":
            return events


class TestAssistantCore(unittest.TestCase):
    def test_sessions_are_isolated(self):
        core = make_core([])
        core.respond("a", text="Bonjour")
        core.respond("b", text="Salut")
        self.assertEqual(core.get_session("a").conversation.history[0]["content"], "Bonjour")
        self.assertEqual(len(core.get_session("b").conversation.history), 2)

    def test_audio_is_transcribed_and_events_emitted(self):
        core = make_core([])
        events = []
        core.events.subscribe(lambda e: events.append(e.type), session_id="s")
        reply = core.respond("s", audio_wav=b"RIFF", synthesize=True)
        self.assertEqual(reply.transcript, "transcription factice")
        self.assertTrue(reply.text.startswith("Écho"))
        self.assertTrue(reply.audio_wav.startswith(b"RIFF"))
        self.assertEqual(events[0], "transcript")
        self.assertIn("token", events)
        self.assertEqual(events[-1], "response")

    def test_dangerous_tool_refused_without_session_confirmation(self):
        executed = []
        reply = make_core(executed).respond("x", text="éteins tout")
        self.assertEqual(executed, [])
        self.assertFalse(reply.tools[0]["executed"])

    def test_session_expiry(self):
        core = AssistantCore(Settings(GATEWAY_SESSION_TIMEOUT=0.001, MCP_CLIENT_ENABLED=False), tools=ToolRegistry(SETTINGS), llm=RuleLLM())
        core.open_session("old")
        core.open_session("keep", persistent=True)
        import time; time.sleep(0.01)
        core.open_session("new")
        self.assertIsNone(core.get_session("old"))
        self.assertIsNotNone(core.get_session("keep"))


class TestGateway(unittest.TestCase):
    def setUp(self):
        self.executed = []
        self.core = make_core(self.executed)
        settings = Settings(**{**SETTINGS.model_dump(), "GATEWAY_AUTH_TOKEN": TOKEN})
        self.client = TestClient(create_app(self.core, settings))

    def test_health_is_public_and_api_requires_token(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.post("/api/ask", json={"text": "x"}).status_code, 401)
        r = self.client.post("/api/ask", json={"text": "Bonjour", "speak": True}, headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "Écho : Bonjour")
        self.assertTrue(base64.b64decode(r.json()["audio"]["data"]).startswith(b"RIFF"))

    def test_websocket_rejects_bad_token(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "faux"})
            self.assertEqual(ws.receive_json()["type"], "error")
            with self.assertRaises(WebSocketDisconnect) as ctx:
                ws.receive_json()
            self.assertEqual(ctx.exception.code, 4401)

    def test_websocket_streaming_and_tools(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": TOKEN, "session": "tel"})
            ready = ws.receive_json()
            self.assertEqual((ready["type"], ready["session"]), ("ready", "tel"))
            ws.send_json({"type": "text", "text": "mets le volume", "speak": True})
            events = collect_until_done(ws)
        kinds = [e["type"] for e in events]
        self.assertIn("token", kinds)
        self.assertEqual([e["name"] for e in events if e["type"] == "tool"], ["volume"])
        self.assertIn("audio", kinds)
        self.assertEqual(self.executed, ["volume"])

    def test_websocket_confirmation_round_trip(self):
        for accepted, expected in ((False, []), (True, ["shutdown"])):
            self.executed.clear()
            with self.client.websocket_connect("/ws", headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
                ws.receive_json()  # ready
                ws.send_json({"type": "text", "text": "éteins l'ordinateur"})
                request = ws.receive_json()
                while request["type"] != "confirm_request":
                    request = ws.receive_json()
                self.assertIn("éteindre", request["question"])
                ws.send_json({"type": "confirm_response", "id": request["id"], "accepted": accepted})
                events = collect_until_done(ws)
            self.assertEqual(self.executed, expected)
            tool = next(e for e in events if e["type"] == "tool")
            self.assertEqual(tool["executed"], accepted)


if __name__ == "__main__":
    unittest.main()
