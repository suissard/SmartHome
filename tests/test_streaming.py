#!/usr/bin/env python3
"""
Tests de la parole en streaming et du barge-in : découpage en phrases, pipeline vocal interruptible,
phrases émises par le cœur pendant la génération, annulation (locale et via la passerelle).
Composants factices : aucun modèle chargé, aucun son joué.
"""

import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np
from starlette.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from audio.barge_in import BargeInDetector
from audio.speech import SpeechPipeline
from core.assistant import AssistantCore
from core.config import Settings
from core.sentences import SentenceSplitter
from core.tools import ToolRegistry
from gateway.app import create_app
from llm.providers import LLMProvider, LLMResponse
from tests.test_gateway import SETTINGS, FakeTTS, make_core
from audio.tts import TextToSpeech


class SlowLLM(LLMProvider):
    """Génère une longue réponse mot à mot, lentement (laisse le temps d'interrompre)."""

    @classmethod
    def describe(cls, settings):
        return "Slow"

    def chat(self, messages, *, on_token=None, **kwargs):
        text = "Voici une première phrase assez longue pour être dite. " * 30
        for word in text.split(" "):
            time.sleep(0.01)
            if on_token:
                on_token(word + " ")
        return LLMResponse(text=text)


def slow_core():
    tts = TextToSpeech(SETTINGS, provider=FakeTTS(SETTINGS))
    return AssistantCore(SETTINGS, tts=tts, tools=ToolRegistry(SETTINGS), llm=SlowLLM(SETTINGS))


class FakeTTSForPipeline:
    def __init__(self, delay=0.0):
        self.delay = delay

    def synthesize(self, text):
        time.sleep(self.delay)
        return np.full(10, len(text), dtype=np.int16), 8000


class TestSentenceSplitter(unittest.TestCase):
    def feed_all(self, tokens, min_chars=10):
        splitter = SentenceSplitter(min_chars)
        out = [s for t in tokens for s in splitter.feed(t)]
        return out, splitter.flush()

    def test_decimal_numbers_are_not_split(self):
        out, rest = self.feed_all(["Le volume est à 40.", "5 % maintenant. ", "Voilà"])
        self.assertEqual(out, ["Le volume est à 40.5 % maintenant."])
        self.assertEqual(rest, ["Voilà"])

    def test_short_sentences_are_merged_and_tags_removed(self):
        out, rest = self.feed_all(["[VOLUME 40] Oui. ", "C'est fait pour vous. ", "Ok"], min_chars=15)
        self.assertEqual(out, ["Oui. C'est fait pour vous."])
        self.assertEqual(rest, ["Ok"])

    def test_punctuation_only_is_ignored(self):
        out, rest = self.feed_all(["... ", "[MUTE]"])
        self.assertEqual(out + rest, [])


class TestSpeechPipeline(unittest.TestCase):
    def test_order_and_completion(self):
        played = []
        pipeline = SpeechPipeline(FakeTTSForPipeline(), sink=lambda samples, sr: played.append(int(samples[0])))
        for text in ("a", "bb", "ccc"):
            pipeline.say(text)
        self.assertTrue(pipeline.wait(timeout=2))
        self.assertEqual(played, [1, 2, 3])
        self.assertFalse(pipeline.busy)
        pipeline.close()

    def test_interrupt_drops_pending_sentences(self):
        played, release = [], threading.Event()

        def slow_sink(samples, sr):
            played.append(int(samples[0]))
            release.wait(2)

        pipeline = SpeechPipeline(FakeTTSForPipeline(), sink=slow_sink)
        for text in ("a", "bb", "ccc", "dddd"):
            pipeline.say(text)
        time.sleep(0.1)
        pipeline.interrupt()
        release.set()
        self.assertTrue(pipeline.wait(timeout=2))
        self.assertEqual(played, [1])
        pipeline.say("ee")
        self.assertTrue(pipeline.wait(timeout=2))
        self.assertEqual(played, [1, 2])
        pipeline.close()


class TestCoreStreaming(unittest.TestCase):
    def test_sentences_are_spoken_during_generation(self):
        core = make_core([])
        sentences = []
        reply = core.respond("s", text="Bonjour à toi, comment vas-tu ce matin", on_sentence=sentences.append)
        self.assertEqual(" ".join(sentences), reply.text)
        self.assertGreaterEqual(len(sentences), 1)

    def test_cancel_interrupts_and_keeps_no_history(self):
        core = slow_core()
        events, sentences = [], []
        core.events.subscribe(lambda e: events.append(e.type), session_id="s")

        def on_sentence(sentence):
            sentences.append(sentence)
            core.cancel("s")  # l'utilisateur coupe la parole dès la première phrase

        reply = core.respond("s", text="Raconte", on_sentence=on_sentence)
        self.assertTrue(reply.interrupted)
        self.assertEqual(len(sentences), 1)
        self.assertIn("interrupted", events)
        self.assertNotIn("response", events)
        self.assertEqual(core.get_session("s").conversation.history, [])


class TestBargeInDetector(unittest.TestCase):
    def test_voice_mode_needs_loud_and_continuous_speech(self):
        s = Settings(BARGE_IN_MODE="voice", BARGE_IN_VOICE_THRESHOLD=1000, BARGE_IN_MIN_DURATION=0.2)
        detector = BargeInDetector(s)
        loud = np.full(1280, 3000, dtype=np.int16)    # 80 ms
        quiet = np.zeros(1280, dtype=np.int16)
        self.assertFalse(detector.process(loud))
        self.assertFalse(detector.process(quiet))      # le silence remet le compteur à zéro
        self.assertFalse(detector.process(loud))
        self.assertFalse(detector.process(loud))
        self.assertTrue(detector.process(loud))         # 240 ms continus

    def test_wakeword_mode_without_detector_is_off(self):
        self.assertEqual(BargeInDetector(Settings(BARGE_IN_MODE="wakeword")).mode, "off")


class TestLocalTurnBargeIn(unittest.TestCase):
    def test_loud_voice_interrupts_local_turn(self):
        import main

        class LoudMic:
            def read(self, n, exception_on_overflow=False):
                time.sleep(0.02)
                return np.full(n, 5000, dtype=np.int16).tobytes()

        core = slow_core()
        core.open_session(main.LOCAL_SESSION, persistent=True)
        speech = SpeechPipeline(FakeTTSForPipeline(), sink=lambda samples, sr: time.sleep(0.05))
        barge_in = BargeInDetector(Settings(BARGE_IN_MODE="voice", BARGE_IN_VOICE_THRESHOLD=1000, BARGE_IN_MIN_DURATION=0.3))
        start = time.monotonic()
        reply = main.run_local_turn(core, speech, LoudMic(), threading.Lock(), barge_in, "Raconte une histoire")
        self.assertTrue(reply.interrupted)
        self.assertLess(time.monotonic() - start, 5)
        speech.close()


class TestGatewayStreaming(unittest.TestCase):
    def test_audio_is_sent_sentence_by_sentence(self):
        client = TestClient(create_app(make_core([]), SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "text", "text": "Bonjour à toi, comment vas-tu ce matin", "speak": True})
            kinds = []
            while not kinds or kinds[-1] != "done":
                kinds.append(ws.receive_json()["type"])
        self.assertIn("audio_chunk", kinds)
        self.assertNotIn("audio", kinds)
        self.assertLess(kinds.index("audio_chunk"), kinds.index("done"))

    def test_stop_message_interrupts_generation(self):
        client = TestClient(create_app(slow_core(), SETTINGS))
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "text", "text": "Raconte", "speak": True})
            while ws.receive_json()["type"] != "token":
                pass
            ws.send_json({"type": "stop"})
            kinds = []
            while not kinds or kinds[-1] != "done":
                kinds.append(ws.receive_json()["type"])
        self.assertIn("interrupted", kinds)
        self.assertNotIn("response", kinds)


if __name__ == "__main__":
    unittest.main()
