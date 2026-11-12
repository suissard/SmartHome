"""Tests des profils de configuration (profiles/*.env) et de la pause des médias sans ducking."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import profiles, settings_store
from core.menu import Option, menu_lines
from core.wizard import Wizard
from core.config import Settings, load_settings


class ProfilesTest(unittest.TestCase):
    def test_default_profile_exists_and_comes_first(self):
        names = profiles.list_profiles()
        self.assertEqual(names[0], profiles.DEFAULT_PROFILE)
        self.assertLessEqual({"hybrid", "mix", "local-gemma", "local-lfm", "local-decision", "cloud"}, set(names))

    def test_every_profile_is_valid_settings(self):
        for name in profiles.list_profiles():
            with self.subTest(profile=name):
                Settings.model_validate(profiles.profile_values(name))
                self.assertTrue(profiles.describe_profile(name))

    def test_user_settings_supplant_machine_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("OPENROUTER_API_KEY=user-key\nOLLAMA_MODEL=qwen\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "machine-key", "LLM_PROVIDER": "ollama"}):
                s = load_settings(env, profile={"LLM_PROVIDER": "openrouter"})
                # Les réglages utilisateur (.env et profil) supplantent ceux de la machine (os.environ)
                self.assertEqual(s.OPENROUTER_API_KEY, "user-key")
                self.assertEqual(s.LLM_PROVIDER, "openrouter")
                self.assertEqual(s.OLLAMA_MODEL, "qwen")

    def test_profile_argument_is_consumed(self):
        argv = ["main.py", "--profile", "cloud", "--x"]
        with patch.dict(os.environ, {}, clear=False):
            self.assertEqual(profiles.pop_profile_argument(argv), "cloud")
            self.assertEqual(os.environ[profiles.PROFILE_ENV_VAR], "cloud")
            os.environ.pop(profiles.PROFILE_ENV_VAR)
        self.assertEqual(argv, ["main.py", "--x"])

    def test_menu_writes_only_the_chosen_name_on_stdout(self):
        names = profiles.list_profiles()
        stdout = io.StringIO()
        with patch("builtins.input", return_value="3"), patch.object(profiles, "remember_profile") as remember, \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            print(profiles.choose_profile())
        self.assertEqual(stdout.getvalue().strip(), names[1])
        remember.assert_called_once_with(names[1])

    def test_last_choice_is_used_without_menu(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "PROFILES_DIR", Path(tmp)), \
                patch.dict(os.environ, {profiles.PROFILE_ENV_VAR: ""}):
            for name in ("hybrid", "cloud"):
                (Path(tmp) / f"{name}.env").write_text("# Titre\n", encoding="utf-8")
            self.assertEqual(profiles.active_profile(), "hybrid")
            profiles.remember_profile("cloud")
            self.assertEqual(profiles.active_profile(), "cloud")
            (Path(tmp) / "cloud.env").unlink()
            self.assertEqual(profiles.active_profile(), "hybrid")

    def test_menu_lines_fit_the_terminal(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            options = [Option("cloud", detail="x" * 80, tag="dernier choix"), Option("mix")]
            lines = menu_lines("Titre", options, 0, 40, can_go_back=True)
        self.assertTrue(all(len(line) <= 40 for line in lines))
        self.assertIn("❯ cloud · dernier choix", "\n".join(lines))

    def _wizard(self, models, **fields):
        settings = Settings(OPENROUTER_API_KEY="", **fields)
        w = Wizard(settings)
        w.models = models
        return w

    def test_wizard_only_offers_what_is_available(self):
        models = [{"name": "gemma4:12b", "capabilities": ["completion", "audio"]},
                  {"name": "lfm3-audio:latest", "capabilities": ["audio", "speech"]}]
        w = self._wizard(models)
        w.brain, w.brain_local, w.brain_audio = "gemma4:12b", True, True
        seen = {}

        def answer(step, text, options, index=0):
            seen[step] = options
            return options[-1]

        with patch.object(Wizard, "ask", side_effect=answer), redirect_stderr(io.StringIO()):
            w.step_listen()
            w.step_voice()
        listen = [o.label for o in seen["step_listen"]]
        self.assertEqual(w.values["step_listen"], {"STT_PROVIDER": "ollama", "OLLAMA_STT_MODEL": "lfm3-audio:latest"})
        self.assertNotIn("OpenRouter", listen)
        self.assertIn("gemma4:12b écoute directement", listen)
        self.assertTrue(seen["step_listen"][-1].tag.startswith("2e modèle"))

    def test_wizard_saves_key_in_env_and_settings_in_profile(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "PROFILES_DIR", Path(tmp)):
            w = self._wizard([])
            w.new_key = "sk-secret"
            w.values = {"step_brain": {"LLM_PROVIDER": "openrouter"}, "step_voice": {"TTS_PROVIDER": "piper"}}
            w.summary = {"Réflexion": "m", "Écoute": "Whisper", "Voix": "Piper"}
            with patch("core.wizard.save_to_env") as save:
                self.assertEqual(w.save(), "perso")
            self.assertEqual(save.call_args.args[0].OPENROUTER_API_KEY, "sk-secret")
            profile = (Path(tmp) / "perso.env").read_text(encoding="utf-8")
            self.assertNotIn("sk-secret", profile)
            self.assertIn("LLM_PROVIDER=openrouter", profile)
            self.assertEqual(profiles.describe_profile("perso").split(" : ")[0], "Perso")

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

    def test_openrouter_api_key_is_editable_and_saves_to_env(self):
        self.assertIn("OPENROUTER_API_KEY", settings_store.EDITABLE)
        desc = {f["name"]: f for g in settings_store.describe(Settings(OPENROUTER_API_KEY="sk-secret")) for f in g["fields"]}
        self.assertEqual(desc["OPENROUTER_API_KEY"]["kind"], "password")
        self.assertEqual(desc["OPENROUTER_API_KEY"]["value"], "")
        self.assertTrue(desc["OPENROUTER_API_KEY"]["configured"])
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            s = Settings(OPENROUTER_API_KEY="sk-new-key")
            settings_store.save_changes(s, ["OPENROUTER_API_KEY"], env)
            self.assertIn("OPENROUTER_API_KEY=sk-new-key", env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
