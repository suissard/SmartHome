"""Tests de la CLI `smarthome`, de la configuration XDG (~/.config/smarthome) et de `smarthome config`."""

import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import cli, cli_config, config, profiles, settings_store
from core.config import Settings


class XdgConfigResolutionTest(unittest.TestCase):
    def test_resolve_env_file_prefers_explicit_then_repo_then_xdg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            xdg = Path(tmp) / "xdg"
            root.mkdir()
            with patch.object(config, "BASE_DIR", root), \
                    patch.object(config, "USER_ENV_FILE", xdg / "smarthome" / "config.env"):
                # 1. Aucun .env dans le dépôt -> bascule sur XDG
                with patch.dict(os.environ, {"SMARTHOME_ENV_FILE": ""}):
                    self.assertEqual(config.resolve_env_file(), xdg / "smarthome" / "config.env")

                # 2. .env présent dans le dépôt -> rétrocompatibilité
                (root / ".env").write_text("ASSISTANT_NAME=Test\n", encoding="utf-8")
                with patch.dict(os.environ, {"SMARTHOME_ENV_FILE": ""}):
                    self.assertEqual(config.resolve_env_file(), root / ".env")

                # 3. SMARTHOME_ENV_FILE explicite -> prioritaire
                with patch.dict(os.environ, {"SMARTHOME_ENV_FILE": "custom.env"}):
                    self.assertEqual(config.resolve_env_file(), root / "custom.env")

    def test_profiles_use_xdg_when_no_repo_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shipped = root / "profiles"
            shipped.mkdir(parents=True)
            (shipped / "hybrid.env").write_text("# Hybride : défaut\n", encoding="utf-8")
            xdg = Path(tmp) / "xdg"
            with patch.object(profiles, "BASE_DIR", root), \
                    patch.object(profiles, "PROFILES_DIR", shipped), \
                    patch.object(profiles, "_DEFAULT_PROFILES_DIR", shipped), \
                    patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg), profiles.PROFILE_ENV_VAR: ""}):
                self.assertEqual(profiles.user_profiles_dir(), xdg / "smarthome" / "profiles")
                self.assertFalse(profiles.has_saved_profile())
                (xdg / "smarthome" / "profiles").mkdir(parents=True)
                (xdg / "smarthome" / "profiles" / "perso.env").write_text("# Perso : test\n", encoding="utf-8")
                profiles.remember_profile("perso")
                self.assertTrue(profiles.has_saved_profile())
                self.assertEqual(profiles.last_profile(), "perso")
                self.assertEqual(profiles.list_profiles(), ["hybrid", "perso"])


class SettingsStoreHelpersTest(unittest.TestCase):
    def test_set_fields_and_unset_creates_secure_minimal_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "nested" / "config.env"
            s = Settings(MCP_CLIENT_ENABLED=False)
            new, changed = settings_store.set_fields(s, {"ASSISTANT_NAME": "Nova", "OPENROUTER_API_KEY": "sk-123"}, env)
            self.assertEqual(set(changed), {"ASSISTANT_NAME", "OPENROUTER_API_KEY"})
            self.assertEqual(new.ASSISTANT_NAME, "Nova")
            self.assertTrue(env.is_file())
            mode = stat.S_IMODE(env.stat().st_mode)
            self.assertEqual(mode, 0o600)
            content = env.read_text(encoding="utf-8")
            self.assertIn("ASSISTANT_NAME=Nova", content)
            self.assertIn("OPENROUTER_API_KEY=sk-123", content)

            self.assertTrue(settings_store.unset_field("OPENROUTER_API_KEY", env))
            self.assertNotIn("OPENROUTER_API_KEY", env.read_text(encoding="utf-8"))
            self.assertFalse(settings_store.unset_field("OPENROUTER_API_KEY", env))

    def test_set_fields_rejects_unknown_or_invalid(self):
        s = Settings(MCP_CLIENT_ENABLED=False)
        with self.assertRaises(ValueError):
            settings_store.set_fields(s, {"INCONNUE": "1"})
        with self.assertRaises(ValueError):
            settings_store.set_fields(s, {"GATEWAY_PORT": "not-a-port"})


class CliConfigCommandsTest(unittest.TestCase):
    def test_set_get_unset_token_and_mic_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "config.env"
            with patch.object(cli_config, "ENV_FILE", env), \
                    patch.object(settings_store, "ENV_FILE", env), \
                    patch.object(cli_config, "load_settings", side_effect=lambda p=env: config.load_settings(p, profile={})):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(cli_config.handle_config(["set", "ASSISTANT_NAME=Orion"]), 0)
                    self.assertEqual(cli_config.handle_config(["get", "ASSISTANT_NAME"]), 0)
                    self.assertEqual(cli_config.handle_config(["token", "--generate"]), 0)
                    self.assertEqual(cli_config.handle_config(["get", "GATEWAY_AUTH_TOKEN"]), 0)
                    self.assertEqual(cli_config.handle_config(["get", "GATEWAY_AUTH_TOKEN", "--raw"]), 0)
                    self.assertEqual(cli_config.handle_config(["mic", "2"]), 0)
                    self.assertEqual(cli_config.handle_config(["get", "AUDIO_INPUT_DEVICE_INDEX"]), 0)
                    self.assertEqual(cli_config.handle_config(["mic", "auto"]), 0)
                    self.assertEqual(cli_config.handle_config(["unset", "ASSISTANT_NAME"]), 0)

                out = stdout.getvalue()
                self.assertIn("Orion", out)
                self.assertIn("Configuré (masqué)", out)
                self.assertIn("index 2", out)
                self.assertIn("défaut du système", out)
                token = env.read_text(encoding="utf-8")
                self.assertIn("GATEWAY_AUTH_TOKEN=", token)

    def test_install_and_uninstall_desktop_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_home = Path(tmp) / "share"
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(data_home)}), \
                    patch.object(cli.shutil, "which", return_value=None):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(cli.main(["install-desktop"]), 0)
                desktop = data_home / "applications" / "smarthome.desktop"
                self.assertTrue(desktop.is_file())
                content = desktop.read_text(encoding="utf-8")
                self.assertIn("Name=SmartHome", content)
                self.assertIn("Terminal=true", content)
                self.assertIn("start", content)

                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["install-desktop", "--uninstall"]), 0)
                self.assertFalse(desktop.exists())

    def test_reset_sound_dispatch(self):
        with patch("audio.ducking.AudioDucker.reset_all") as reset:
            self.assertEqual(cli.main(["reset-sound"]), 0)
            reset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
