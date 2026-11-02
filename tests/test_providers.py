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
from llm.providers import LLMProvider, LLMResponse, OllamaLLM, OpenRouterLLM
from audio.stt import STT_PROVIDERS, create_fallback_stt, create_stt
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

    def test_direct_stt_is_kept_whatever_the_llm(self):
        # Le repli se décide à chaque demande selon le modèle actif, plus à la création
        for provider in ("ollama", "openrouter"):
            self.assertTrue(create_stt(Settings(LLM_PROVIDER=provider, STT_PROVIDER="direct")).passthrough)

    def test_fallback_stt_must_transcribe(self):
        with patch.object(STT_PROVIDERS.get("whisper"), "__init__", return_value=None):
            self.assertEqual(create_fallback_stt(Settings()).provider_name, "whisper")
        with self.assertRaises(ValueError):
            create_fallback_stt(Settings(STT_FALLBACK_PROVIDER="bypass"))


class TestAudioInput(unittest.TestCase):
    """Entrée audio décidée par modèle : capacités Ollama, modalités OpenRouter, forçage LLM_AUDIO_INPUT."""

    def test_forced_modes_skip_detection(self):
        llm = OllamaLLM(Settings(LLM_AUDIO_INPUT="on"))
        with patch.object(OllamaLLM, "capabilities", side_effect=AssertionError("pas de requête")):
            self.assertTrue(llm.accepts_audio())
            llm.settings = Settings(LLM_AUDIO_INPUT="off")
            self.assertFalse(llm.accepts_audio())

    def test_ollama_reads_audio_capability_once_per_model(self):
        llm = OllamaLLM(Settings())
        caps = {"gemma4:12b": ["completion", "audio", "tools"], "qwen2.5:7b": ["completion", "tools"]}
        with patch.object(OllamaLLM, "capabilities", side_effect=lambda m: caps[m]) as show:
            self.assertTrue(llm.accepts_audio("gemma4:12b"))
            self.assertTrue(llm.accepts_audio("gemma4:12b"))
            self.assertFalse(llm.accepts_audio("qwen2.5:7b"))
        self.assertEqual(show.call_count, 2)

    def test_unreachable_server_means_transcription_and_retry(self):
        llm = OllamaLLM(Settings())
        with patch.object(OllamaLLM, "capabilities", side_effect=ConnectionError("refusé")):
            self.assertFalse(llm.accepts_audio("gemma4:12b"))
        with patch.object(OllamaLLM, "capabilities", return_value=["audio"]):
            self.assertTrue(llm.accepts_audio("gemma4:12b"))

    def test_openrouter_uses_catalog_modalities(self):
        llm = OpenRouterLLM(Settings())
        llm._input_modalities = {"google/gemini-2.5-flash": ["text", "image", "audio"], "meta-llama/llama-3.3-70b-instruct": ["text"]}
        self.assertTrue(llm.accepts_audio("google/gemini-2.5-flash"))
        self.assertFalse(llm.accepts_audio("meta-llama/llama-3.3-70b-instruct"))
        self.assertTrue(llm.accepts_audio("prive/inconnu"))

    def test_ollama_sends_audio_with_last_user_message(self):
        llm = OllamaLLM(Settings())
        sent = {}

        def chat(**kwargs):
            sent.update(kwargs)
            return {"message": {"content": "Cinq."}}

        llm.client.chat = chat
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
        self.assertEqual(llm.chat(messages, audio_wav=b"RIFF").text, "Cinq.")
        self.assertEqual(sent["messages"][1]["images"], [b"RIFF"])
        self.assertNotIn("images", messages[1])


class FakeHTTPResponse:
    def __init__(self, status=200, json_data=None, content=b"", text=""):
        self.status_code, self._json, self.content, self.text = status, json_data, content, text

    def json(self):
        return self._json


def streamed_wav(samples, rate=24000) -> bytes:
    """WAV tel que l'envoie Ollama : tailles RIFF et data à 0xFFFFFFFF (en-tête « en flux »)."""
    import struct
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF\xff\xff\xff\xffWAVEfmt " + struct.pack("<I", 16) + fmt
            + b"data\xff\xff\xff\xff" + np.asarray(samples, dtype="<i2").tobytes())


class TestOllamaAudio(unittest.TestCase):
    """Fournisseurs STT / TTS « ollama » (lfm3-audio...), sans serveur : les requêtes HTTP sont simulées."""

    def test_decode_streamed_wav(self):
        from audio.tts import decode_wav
        audio, rate = decode_wav(streamed_wav([1, -2, 300]))
        self.assertEqual((audio.tolist(), rate, audio.dtype), ([1, -2, 300], 24000, np.int16))
        with self.assertRaises(ValueError):
            decode_wav(b"ID3 pas un wav")

    def test_capability_is_required(self):
        from core.providers import check_ollama_capability
        with patch("core.providers.ollama_capabilities", return_value=["completion", "tools"]):
            with self.assertRaises(RuntimeError) as ctx:
                check_ollama_capability(Settings(), "qwen2.5:7b", "speech", "la synthèse vocale")
        self.assertIn("qwen2.5:7b", str(ctx.exception))
        with patch("core.providers.ollama_capabilities", return_value=["audio", "speech"]):
            check_ollama_capability(Settings(), "lfm3-audio", "speech", "la synthèse vocale")

    def test_unreachable_server_does_not_block_startup(self):
        import httpx
        from core.providers import check_ollama_capability
        with patch("core.providers.ollama_capabilities", side_effect=httpx.ConnectError("refusé")):
            check_ollama_capability(Settings(), "lfm3-audio", "audio", "l'audio en entrée")

    def test_ollama_stt_posts_wav_and_language(self):
        sent = {}

        def post(url, **kwargs):
            sent.update(url=url, **kwargs)
            return FakeHTTPResponse(json_data={"text": " Mets le volume à 40. "})

        with patch("audio.stt.check_ollama_capability"):
            stt = STT_PROVIDERS.create("ollama", Settings(WHISPER_LANGUAGE="fr"))
        with patch("httpx.post", side_effect=post):
            self.assertEqual(stt.transcribe(b"RIFF"), "Mets le volume à 40.")
        self.assertTrue(sent["url"].endswith("/v1/audio/transcriptions"))
        self.assertEqual(sent["data"], {"model": "lfm3-audio", "language": "fr"})
        self.assertEqual(sent["files"]["file"][1], b"RIFF")

    def test_ollama_tts_requests_wav_with_voice(self):
        sent = {}

        def post(url, **kwargs):
            sent.update(url=url, **kwargs)
            return FakeHTTPResponse(content=streamed_wav([0, 1000, -1000]))

        from audio.tts import TTS_PROVIDERS
        with patch("audio.tts.check_ollama_capability"):
            tts = TTS_PROVIDERS.create("ollama", Settings(OLLAMA_TTS_VOICE="male-french"))
        with patch("httpx.post", side_effect=post):
            audio, rate = tts.synthesize("Bonjour.")
        self.assertEqual((audio.tolist(), rate), ([0, 1000, -1000], 24000))
        self.assertEqual(sent["json"], {"model": "lfm3-audio", "input": "Bonjour.", "response_format": "wav", "voice": "male-french"})

    def test_ollama_tts_error_is_explicit(self):
        from audio.tts import TTS_PROVIDERS
        with patch("audio.tts.check_ollama_capability"):
            tts = TTS_PROVIDERS.create("ollama", Settings())
        with patch("httpx.post", return_value=FakeHTTPResponse(400, text='{"error": "only speed 1 is supported"}')):
            with self.assertRaises(RuntimeError) as ctx:
                tts.synthesize("Bonjour.")
        self.assertIn("only speed 1", str(ctx.exception))


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
