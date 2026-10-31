#!/usr/bin/env python3
"""
Tests de l'écoute active : fin de conversation (phrases de congé, outil « sleep », tag [SLEEP]),
rejet du bruit ambiant par la VAD et filtre des transcriptions inventées par Whisper.
Composants factices : aucun modèle chargé, aucun micro ouvert.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from audio.stt import STTProvider
from audio.transcribe import VoiceTranscriber
from audio.vad import SpeechDetector
from core.assistant import AssistantCore, _asks_to_sleep
from core.config import Settings
from core.sentences import matches_phrase
from core.tools import Tool, ToolCall, ToolRegistry
from llm.providers import LLMProvider, LLMResponse
from tests.test_gateway import SETTINGS

SPEECH, NOISE = 5000, 3000   # amplitudes des trames factices : voix / bruit fort mais non vocal


class FakeVADModel:
    """Silero factice : une trame d'amplitude SPEECH est de la voix, tout le reste non."""

    def predict(self, x, frame_size=640):
        return 0.9 if int(np.abs(x).mean()) == SPEECH else 0.05

    def reset_states(self):
        pass


class FakeStream:
    """Micro factice qui rejoue une suite de trames, puis du silence."""

    def __init__(self, amplitudes, chunk):
        self.frames = [np.full(chunk, a, dtype=np.int16).tobytes() for a in amplitudes]
        self.chunk = chunk

    def get_read_available(self):
        return 0

    def read(self, n, exception_on_overflow=False):
        return self.frames.pop(0) if self.frames else bytes(2 * n)


class CountingSTT(STTProvider):
    passthrough = False

    def __init__(self, settings):
        super().__init__(settings)
        self.calls = 0

    def transcribe(self, wav):
        self.calls += 1
        return self._discard_hallucination("Allume la lumière")


class SleepLLM(LLMProvider):
    """Appelle l'outil sleep quand on lui dit « je vais me coucher », puis prend congé."""

    calls = 0

    @classmethod
    def describe(cls, settings):
        return "Sleep"

    def chat(self, messages, *, tools=None, on_token=None, **kwargs):
        SleepLLM.calls += 1
        last = messages[-1]
        if last["role"] == "tool":
            return LLMResponse(text="Bonne soirée !")
        if tools and "coucher" in (last["content"] or ""):
            return LLMResponse(tool_calls=[ToolCall("sleep", {}, id="c1")])
        return LLMResponse(text="Voilà.")


def sleep_core():
    tools = ToolRegistry(SETTINGS)
    tools.add(Tool("sleep", "Mettre en veille", {"type": "object", "properties": {}}, lambda a: "Succès."))
    return AssistantCore(SETTINGS, tools=tools, llm=SleepLLM(SETTINGS))


class TestEndPhrases(unittest.TestCase):
    def setUp(self):
        s = Settings()
        self.match = lambda text: matches_phrase(text, s.CONVERSATION_END_PHRASES, s.CONVERSATION_END_FILLERS)

    def test_goodbyes_match_with_fillers_and_punctuation(self):
        for text in ("Au revoir !", "Merci, au revoir.", "C’est tout pour moi, merci.", "Stop.", "Bonne nuit Jarvis"):
            self.assertTrue(self.match(text), text)

    def test_requests_containing_a_goodbye_word_do_not_match(self):
        for text in ("Stop la musique", "Baisse le son, au revoir", "Merci beaucoup", ""):
            self.assertFalse(self.match(text), text)


class TestCoreEndConversation(unittest.TestCase):
    def setUp(self):
        SleepLLM.calls = 0

    def test_end_phrase_skips_the_llm(self):
        core = sleep_core()
        events = []
        core.events.subscribe(lambda e: events.append(e.data), session_id="s")
        reply = core.respond("s", text="Merci, c'est tout.")
        self.assertTrue(reply.end_conversation)
        self.assertEqual(SleepLLM.calls, 0)
        self.assertTrue(events[-1]["end_conversation"])

    def test_sleep_tool_ends_conversation(self):
        reply = sleep_core().respond("s", text="Je vais me coucher")
        self.assertTrue(reply.end_conversation)
        self.assertEqual(reply.text, "Bonne soirée !")

    def test_normal_request_keeps_conversation_open(self):
        self.assertFalse(sleep_core().respond("s", text="Quelle heure est-il ?").end_conversation)

    def test_sleep_tag_in_text_mode(self):
        self.assertTrue(_asks_to_sleep("[SLEEP] À bientôt !", []))
        self.assertFalse(_asks_to_sleep("À bientôt !", [{"name": "sleep", "executed": False}]))


class TestNoiseRejection(unittest.TestCase):
    def make_transcriber(self):
        s = Settings(VAD_ENGINE="silero", VOICE_THRESHOLD=700, SILENCE_DURATION=0.05, VAD_MIN_SPEECH_DURATION=0.3)
        stt = CountingSTT(s)
        return VoiceTranscriber(s, stt=stt, vad=SpeechDetector(s, model=FakeVADModel())), stt, s.AUDIO_CHUNK

    def test_loud_noise_never_reaches_stt(self):
        transcriber, stt, chunk = self.make_transcriber()
        text, _, _ = transcriber.record_and_transcribe(FakeStream([NOISE] * 200, chunk), timeout_silence=0.3)
        self.assertEqual(text, "")
        self.assertEqual(stt.calls, 0)

    def test_too_short_speech_is_ignored(self):
        transcriber, stt, chunk = self.make_transcriber()
        text, _, _ = transcriber.record_and_transcribe(FakeStream([SPEECH] * 2 + [0] * 10, chunk), timeout_silence=0.3)
        self.assertEqual(text, "")
        self.assertEqual(stt.calls, 0)

    def test_speech_in_noise_ends_when_voice_stops(self):
        transcriber, stt, chunk = self.make_transcriber()
        # La voix s'arrête mais le bruit continue : la fin de phrase est quand même détectée
        stream = FakeStream([SPEECH] * 8 + [NOISE] * 500, chunk)
        text, _, audio_seconds = transcriber.record_and_transcribe(stream, timeout_silence=5)
        self.assertEqual(text, "Allume la lumière")
        self.assertLess(audio_seconds, 2)

    def test_energy_engine_keeps_the_old_behaviour(self):
        detector = SpeechDetector(Settings(VAD_ENGINE="energy", VOICE_THRESHOLD=700))
        self.assertTrue(detector.is_speech_start(np.full(1280, NOISE, dtype=np.int16)))


class TestHallucinationFilter(unittest.TestCase):
    def test_whisper_noise_phrases_are_dropped(self):
        stt = CountingSTT(Settings())
        self.assertEqual(stt._discard_hallucination("Sous-titres réalisés par la communauté d'Amara.org"), "")
        self.assertEqual(stt._discard_hallucination("..."), "")
        self.assertEqual(stt._discard_hallucination("Monte le volume"), "Monte le volume")


if __name__ == "__main__":
    unittest.main()
