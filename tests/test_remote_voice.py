#!/usr/bin/env python3
"""
Tests de la garde « voix distante » : quand le micro du téléphone (PWA) est utilisé, le micro de l'ordinateur
ignore le mot-clé et quitte l'écoute active. Composants factices : aucun modèle chargé, aucun micro ouvert.
"""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from starlette.testclient import TestClient

from audio.transcribe import VoiceTranscriber
from audio.vad import SpeechDetector
from core.config import Settings
from core.events import EventBus
from core.remote_voice import RemoteVoiceGuard
from gateway.app import create_app
from tests.test_gateway import SETTINGS, make_core
from tests.test_listening import SPEECH, CountingSTT, FakeStream, FakeVADModel


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TestRemoteVoiceGuard(unittest.TestCase):
    def setUp(self):
        self.bus, self.clock = EventBus(), Clock()
        self.guard = RemoteVoiceGuard(self.bus, "local", hold=3.0, clock=self.clock)

    def test_active_while_remote_mic_is_open_then_for_hold(self):
        self.assertFalse(self.guard.active())
        self.bus.emit("remote_listening", "pwa", active=True)
        self.clock.now += 60
        self.assertTrue(self.guard.active())   # micro toujours ouvert, quelle que soit la durée
        self.bus.emit("remote_listening", "pwa", active=False)
        self.clock.now += 2.9
        self.assertTrue(self.guard.active())
        self.clock.now += 0.2
        self.assertFalse(self.guard.active())

    def test_remote_audio_without_listening_message(self):
        self.bus.emit("transcript", "api-client", text="Allume la lumière")
        self.assertTrue(self.guard.active())

    def test_local_session_and_other_events_are_ignored(self):
        self.bus.emit("remote_listening", "local", active=True)
        self.bus.emit("transcript", "local", text="x")
        self.bus.emit("token", "pwa", text="Bonjour")
        self.assertFalse(self.guard.active())

    def test_disabled_guard_never_blocks(self):
        guard = RemoteVoiceGuard(self.bus, "local", enabled=False)
        self.bus.emit("remote_listening", "pwa", active=True)
        self.assertFalse(guard.active())


class TestTranscriberAbort(unittest.TestCase):
    def test_should_stop_abandons_listening_and_recording(self):
        s = Settings(VAD_ENGINE="silero", VOICE_THRESHOLD=700, SILENCE_DURATION=0.05, VAD_MIN_SPEECH_DURATION=0.3)
        stt = CountingSTT(s)
        transcriber = VoiceTranscriber(s, stt=stt, vad=SpeechDetector(s, model=FakeVADModel()))
        reads = {"n": 0}
        stream = FakeStream([SPEECH] * 200, s.AUDIO_CHUNK)
        original = stream.read

        def counting_read(n, exception_on_overflow=False):
            reads["n"] += 1
            return original(n, exception_on_overflow)
        stream.read = counting_read
        # Le téléphone prend la main pendant l'enregistrement : rien n'est transcrit
        text, _, _ = transcriber.record_and_transcribe(stream, timeout_silence=30, should_stop=lambda: reads["n"] > 5)
        self.assertEqual(text, "")
        self.assertEqual(stt.calls, 0)


class TestGatewayListening(unittest.TestCase):
    def test_listening_messages_reach_the_guard_and_disconnect_releases_it(self):
        core = make_core([])
        clock = Clock()
        guard = RemoteVoiceGuard(core.events, "local", hold=3.0, clock=clock)
        client = TestClient(create_app(core, SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": ""})
            ws.receive_json()
            ws.send_json({"type": "listening", "active": True})
            ws.send_json({"type": "ping"})
            while ws.receive_json()["type"] != "pong":
                pass
            clock.now += 60
            self.assertTrue(guard.active())
        # Client parti micro ouvert : la garde se relâche après le délai
        clock.now += 3.1
        self.assertFalse(guard.active())


if __name__ == "__main__":
    unittest.main()
