"""Tests des profils de configuration (profiles/*.env) et de la pause des médias sans ducking."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import profiles, settings_store
from core.config import Settings, load_settings


class ProfilesTest(unittest.TestCase):
    def test_default_profile_exists_and_comes_first(self):
        names = profiles.list_profiles()
        self.assertEqual(names[0], profiles.DEFAULT_PROFILE)
        self.assertEqual(set(names), {"mix", "local-gemma", "local-lfm", "local-decision", "cloud"})

    def test_every_profile_is_valid_settings(self):
        for name in profiles.list_profiles():
            with self.subTest(profile=name):
                Settings.model_validate(profiles.profile_values(name))
                self.assertTrue(profiles.describe_profile(name))

    def test_profile_overrides_env_file_but_not_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("LLM_PROVIDER=ollama\nOLLAMA_MODEL=qwen\n", encoding="utf-8")
            s = load_settings(env, profile={"LLM_PROVIDER": "openrouter"})
            self.assertEqual((s.LLM_PROVIDER, s.OLLAMA_MODEL), ("openrouter", "qwen"))
            with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
                self.assertEqual(load_settings(env, profile={"LLM_PROVIDER": "openrouter"}).LLM_PROVIDER, "ollama")

    def test_profile_argument_is_consumed(self):
        argv = ["main.py", "--profile", "cloud", "--x"]
        with patch.dict(os.environ, {}, clear=False):
            self.assertEqual(profiles.pop_profile_argument(argv), "cloud")
            self.assertEqual(os.environ[profiles.PROFILE_ENV_VAR], "cloud")
            os.environ.pop(profiles.PROFILE_ENV_VAR)
        self.assertEqual(argv, ["main.py", "--x"])

    def test_unknown_profile_is_refused(self):
        with self.assertRaises(SystemExit):
            profiles.profile_path("inexistant")

    def test_local_overrides_are_not_a_profile_and_win_over_it(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "PROFILES_DIR", Path(tmp)):
            (Path(tmp) / "mix.env").write_text("# Mix\nTTS_PROVIDER=ollama\nSTT_PROVIDER=ollama\n", encoding="utf-8")
            profiles.local_overrides_path("mix").write_text("TTS_PROVIDER=piper\n", encoding="utf-8")
            self.assertEqual(profiles.list_profiles(), ["mix"])
            self.assertEqual(profiles.profile_values("mix"), {"TTS_PROVIDER": "piper", "STT_PROVIDER": "ollama"})

    def test_saved_profile_field_goes_to_local_overrides(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "PROFILES_DIR", Path(tmp)):
            (Path(tmp) / "mix.env").write_text("# Mix\nTTS_PROVIDER=ollama\n", encoding="utf-8")
            env = Path(tmp) / ".env"
            s = Settings(TTS_PROVIDER="piper", LLM_HISTORY_MESSAGES=2)
            with patch.object(settings_store, "ENV_FILE", env), patch.dict(os.environ, {profiles.PROFILE_ENV_VAR: "mix"}):
                settings_store.save_changes(s, ["TTS_PROVIDER", "LLM_HISTORY_MESSAGES"], env)
            self.assertIn("TTS_PROVIDER=piper", profiles.local_overrides_path("mix").read_text(encoding="utf-8"))
            self.assertEqual(env.read_text(encoding="utf-8"), "LLM_HISTORY_MESSAGES=2\n")

    def test_visibility_rules_target_known_fields(self):
        known = set(settings_store.EDITABLE) | {"LLM_MODE"}
        self.assertLessEqual(set(settings_store.VISIBLE_WHEN), set(settings_store.EDITABLE))
        for rules in settings_store.VISIBLE_WHEN.values():
            for rule in rules:
                self.assertLessEqual(set(rule), known)

    def test_describe_exposes_visibility_rules(self):
        fields = {f["name"]: f for g in settings_store.describe(Settings()) for f in g["fields"]}
        self.assertEqual(fields["OLLAMA_TTS_VOICE"]["when"], [{"TTS_PROVIDER": ["ollama"]}])
        self.assertIsNone(fields["LLM_PROVIDER"]["when"])

    def test_decision_profile_loads_a_single_ollama_model(self):
        values = profiles.profile_values("local-decision")
        self.assertEqual((values["STT_PROVIDER"], values["TTS_PROVIDER"]), ("whisper", "piper"))

    def test_media_pause_enabled_by_default(self):
        self.assertTrue(Settings().MEDIA_PAUSE_ENABLED)


if __name__ == "__main__":
    unittest.main()
