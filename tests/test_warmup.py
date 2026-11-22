#!/usr/bin/env python3
"""
Tests du préchargement des modèles Ollama (core/warmup.py) : modèles concernés selon la configuration,
seuls les modèles absents de /api/ps sont chargés, phrase d'attente, maintien en mémoire.
Ollama est simulé : aucune requête réseau.
"""

import random
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import warmup
from core.config import Settings
from core.warmup import ModelWarmer, keep_alive_value, models_to_warm, waiting_phrase

OLLAMA_ALL = dict(LLM_PROVIDER="ollama", OLLAMA_MODEL="gemma4:12b", STT_PROVIDER="ollama", OLLAMA_STT_MODEL="lfm3-audio",
                  TTS_PROVIDER="ollama", OLLAMA_TTS_MODEL="lfm3-audio")


class TestModelsToWarm(unittest.TestCase):
    def test_all_ollama_providers_without_duplicates(self):
        self.assertEqual(models_to_warm(Settings(**OLLAMA_ALL)), ["lfm3-audio", "gemma4:12b"])

    def test_no_ollama_provider(self):
        s = Settings(LLM_PROVIDER="openrouter", STT_PROVIDER="whisper", TTS_PROVIDER="piper")
        self.assertEqual(models_to_warm(s), [])

    def test_active_llm_model_and_stt_fallback(self):
        s = Settings(LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen2.5:7b", STT_PROVIDER="direct", TTS_PROVIDER="piper",
                     OLLAMA_STT_MODEL="lfm3-audio")
        self.assertEqual(models_to_warm(s, "nimble"), ["nimble"])
        self.assertEqual(models_to_warm(s, "nimble", stt_via_ollama=True), ["lfm3-audio", "nimble"])


class TestHelpers(unittest.TestCase):
    def test_keep_alive_value(self):
        self.assertIsNone(keep_alive_value(Settings(OLLAMA_KEEP_ALIVE="")))
        self.assertEqual(keep_alive_value(Settings(OLLAMA_KEEP_ALIVE="-1")), -1)
        self.assertEqual(keep_alive_value(Settings(OLLAMA_KEEP_ALIVE="30m")), "30m")

    def test_waiting_phrase(self):
        s = Settings(OLLAMA_WARMUP_PHRASES="Attends, je réveille mes circuits.| |Une seconde.")
        phrases = {waiting_phrase(s, random.Random(seed)) for seed in range(30)}
        self.assertEqual(phrases, {"Attends, je réveille mes circuits.", "Une seconde."})
        self.assertEqual(waiting_phrase(Settings(OLLAMA_WARMUP_PHRASES="")), "")


class TestModelWarmer(unittest.TestCase):
    def test_loads_only_cold_models_and_reports_loading(self):
        release = threading.Event()
        loaded_calls = []

        def fake_load(settings, model):
            loaded_calls.append(model)
            release.wait(5)

        s = Settings(**OLLAMA_ALL)
        warmer = ModelWarmer(lambda: s)
        with mock.patch.object(warmup, "loaded_models", return_value={"lfm3-audio:latest"}), \
                mock.patch.object(warmup, "load_model", side_effect=fake_load):
            self.assertTrue(warmer.start())
            for _ in range(100):
                if warmer.loading():
                    break
                threading.Event().wait(0.01)
            self.assertEqual(warmer.loading(), ["gemma4:12b"])
            self.assertFalse(warmer.start(), "un seul préchargement à la fois")
            release.set()
            self.assertTrue(warmer.wait(5))
        self.assertEqual(loaded_calls, ["gemma4:12b"])
        self.assertEqual(warmer.loading(), [])

    def test_all_loaded_or_ollama_down(self):
        s = Settings(**OLLAMA_ALL)
        for ps in ({"gemma4:12b", "lfm3-audio:latest"}, ConnectionError("down")):
            warmer = ModelWarmer(lambda: s)
            kwargs = {"side_effect": ps} if isinstance(ps, Exception) else {"return_value": ps}
            with mock.patch.object(warmup, "loaded_models", **kwargs), mock.patch.object(warmup, "load_model") as load:
                self.assertTrue(warmer.start())
                self.assertTrue(warmer.wait(5))
                load.assert_not_called()

    def test_disabled(self):
        warmer = ModelWarmer(lambda: Settings(OLLAMA_WARMUP_ENABLED=False, **OLLAMA_ALL))
        with mock.patch.object(warmup, "loaded_models") as ps:
            self.assertFalse(warmer.start())
            ps.assert_not_called()


if __name__ == "__main__":
    unittest.main()
