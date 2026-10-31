#!/usr/bin/env python3
"""
Tests unitaires de la configuration typée, du registre de fournisseurs, de la conversation LLM
et du post-traitement TTS (avec des fournisseurs factices : aucun modèle n'est chargé).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import Settings, load_settings
from core.providers import ProviderRegistry
from llm.llm import Conversation
from llm.providers import LLMProvider, LLMResponse
from audio.stt import STT_PROVIDERS, create_stt
from audio.tts import TextToSpeech, TTSProvider


class FakeLLM(LLMProvider):
    def __init__(self, settings, reply="Bonjour.", error=None):
        super().__init__(settings)
        self.reply, self.error, self.calls = reply, error, []

    @classmethod
    def describe(cls, settings):
        return "Fake"

    def chat(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        if self.error:
            raise self.error
        return LLMResponse(text=self.reply)


class FakeTTS(TTSProvider):
    @classmethod
    def describe(cls, settings):
        return "Fake"

    def synthesize(self, text):
        self.last_text = text
        return np.full(1000, 1000, dtype=np.int16), 1000


class TestSettings(unittest.TestCase):
    def _load(self, env_content: str, environ: dict | None = None) -> Settings:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(env_content)
            with patch.dict(os.environ, environ or {}, clear=True):
                return load_settings(env_file)

    def test_env_overrides_file_and_empty_means_default(self):
        s = self._load("LLM_PROVIDER=ollama\nMCP_PORT=\nLLM_STREAM=non\n", {"LLM_PROVIDER": "OpenRouter"})
        self.assertEqual(s.LLM_PROVIDER, "openrouter")
        self.assertEqual(s.MCP_PORT, 8000)
        self.assertFalse(s.LLM_STREAM)

    def test_aliases_and_lists(self):
        s = self._load("STT_PROVIDER=bypass\nACTIVE_STANDBY_TIMEOUT=12\nACTIONS_OPEN_ALLOWED_APPS=Firefox, vlc\n")
        self.assertEqual(s.STT_PROVIDER, "direct")
        self.assertEqual(s.FOLLOW_UP_TIMEOUT, 12.0)
        self.assertEqual(s.ACTIONS_OPEN_ALLOWED_APPS, ["firefox", "vlc"])

    def test_invalid_values_stop_with_readable_message(self):
        with self.assertRaises(SystemExit) as ctx:
            self._load("WAKEWORD_THRESHOLD=3\nMCP_PORT=abc\n")
        self.assertIn("WAKEWORD_THRESHOLD", str(ctx.exception.code))
        self.assertIn("MCP_PORT", str(ctx.exception.code))


class TestProviderRegistry(unittest.TestCase):
    def test_register_alias_and_unknown(self):
        registry = ProviderRegistry("TEST")

        @registry.register("alpha", "a")
        class Alpha:
            def __init__(self, settings):
                self.settings = settings

        self.assertIs(registry.get("A"), Alpha)
        self.assertEqual(Alpha.provider_name, "alpha")
        self.assertIsInstance(registry.create("alpha", Settings()), Alpha)
        with self.assertRaises(ValueError) as ctx:
            registry.get("beta")
        self.assertIn("alpha", str(ctx.exception))

    def test_direct_stt_falls_back_to_whisper_with_ollama(self):
        with patch.object(STT_PROVIDERS.get("whisper"), "__init__", return_value=None):
            stt = create_stt(Settings(LLM_PROVIDER="ollama", STT_PROVIDER="direct"))
        self.assertEqual(stt.provider_name, "whisper")

    def test_direct_stt_kept_with_audio_capable_llm(self):
        stt = create_stt(Settings(LLM_PROVIDER="openrouter", STT_PROVIDER="direct"))
        self.assertTrue(stt.passthrough)


class TestConversation(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(LLM_HISTORY_MESSAGES=3, ACTIONS_DYNAMIC_PROMPT=False, LLM_STREAM=False, LLM_TOOL_CALLING="tags")

    def test_history_is_saved_and_starts_with_user(self):
        conv = Conversation(FakeLLM(self.settings, reply="<think>hmm</think> Réponse"), self.settings)
        self.assertEqual(conv.ask("Q1"), "Réponse")
        conv.ask("Q2")
        self.assertEqual(len(conv.history), 2)
        self.assertEqual(conv.history[0], {"role": "user", "content": "Q2"})

    def test_messages_sent_to_provider(self):
        fake = FakeLLM(self.settings)
        conv = Conversation(fake, self.settings)
        conv.ask("Q1")
        conv.ask(audio_bytes=b"RIFF")
        messages, kwargs = fake.calls[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual([m["content"] for m in messages[1:]], ["Q1", "Bonjour.", ""])
        self.assertEqual(kwargs["audio_wav"], b"RIFF")
        self.assertEqual(conv.history[-2]["content"], "🎙️ [Message vocal]")

    def test_provider_error_returns_warning_without_history(self):
        conv = Conversation(FakeLLM(self.settings, error=RuntimeError("panne")), self.settings)
        self.assertTrue(conv.ask("Q").startswith("⚠️"))
        self.assertEqual(conv.history, [])


class TestTextToSpeech(unittest.TestCase):
    def test_synthesize_adds_punctuation_and_padding(self):
        settings = Settings(TTS_SILENCE_START_DURATION=0.1, TTS_SILENCE_END_DURATION=0.2, TTS_FADE_OUT_DURATION=0.05)
        engine = FakeTTS(settings)
        tts = TextToSpeech(settings, provider=engine)
        audio, sr = tts.synthesize("Bonjour")
        self.assertEqual(engine.last_text, "Bonjour.")
        self.assertEqual(sr, 1000)
        self.assertEqual(audio.dtype, np.int16)
        self.assertEqual(len(audio), 100 + 1000 + 200)
        self.assertEqual(audio[-201], 0)  # fin du fondu de sortie

    def test_empty_text_produces_nothing(self):
        tts = TextToSpeech(Settings(), provider=FakeTTS(Settings()))
        audio, _ = tts.synthesize("   ")
        self.assertEqual(len(audio), 0)


if __name__ == "__main__":
    unittest.main()
