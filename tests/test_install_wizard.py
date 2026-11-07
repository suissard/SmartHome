"""Tests de l'assistant d'installation (core/install_wizard.py), sans terminal ni réseau."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import install_wizard as iw


def answers(*values):
    """Remplace menu.choose : renvoie l'option dont la valeur (ou le libellé) vient ensuite dans la liste."""
    queue = list(values)

    def fake_choose(title, options, index=0, can_go_back=False):
        wanted = queue.pop(0)
        for option in options:
            if option.value == wanted or option.label == wanted:
                return option
        raise AssertionError(f"{wanted!r} absent de « {title} » : {[o.label for o in options]}")
    return fake_choose


def wizard(*argv):
    return iw.InstallWizard(iw.parse_args(["--platform", "linux", "--pkg-manager", "apt-get", *argv]))


class ProfileNeedsTest(unittest.TestCase):
    def test_shipped_profiles(self):
        hybrid = iw.profile_needs(iw.effective_values("hybrid"))
        self.assertFalse(hybrid["ollama"])
        self.assertTrue(hybrid["openrouter"] and hybrid["whisper"] and hybrid["piper"])

        mix = iw.profile_needs(iw.effective_values("mix"))
        self.assertTrue(mix["ollama"] and mix["openrouter"])
        self.assertEqual(mix["ollama_models"], ["lfm3-audio"])

        cloud = iw.profile_needs(iw.effective_values("cloud"))
        self.assertFalse(cloud["ollama"])
        self.assertTrue(cloud["openrouter"])

        decision = iw.profile_needs(iw.effective_values("local-decision"))
        self.assertEqual(decision["ollama_models"], ["nimble"])
        self.assertTrue(decision["whisper"] and decision["piper"])

    def test_direct_listening_uses_fallback(self):
        needs = iw.profile_needs({"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "a", "STT_PROVIDER": "direct",
                                  "STT_FALLBACK_PROVIDER": "ollama", "OLLAMA_STT_MODEL": "b", "TTS_PROVIDER": "piper"})
        self.assertEqual(needs["ollama_models"], ["a", "b"])
        self.assertFalse(needs["whisper"])

    def test_env_file_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# commentaire\nA=1\nexport B = \"deux mots\"\nC=x # note\n\nD\n", encoding="utf-8")
            self.assertEqual(iw.read_env_file(path), {"A": "1", "B": "deux mots", "C": "x"})


class InstallWizardTest(unittest.TestCase):
    def run_wizard(self, w, *values, installed=False):
        with patch.object(iw, "choose", answers(*values)), \
                patch.object(iw, "answered"), patch.object(iw, "note"), \
                patch.object(iw.shutil, "which", return_value="/usr/bin/x" if installed else None), \
                patch.object(iw, "ollama_reachable", return_value=installed), \
                patch.object(iw, "last_profile", return_value=None), \
                patch("sys.stderr"):
            self.assertTrue(w.run())
        return w.plan()

    def test_local_profile_installs_ollama_and_its_model(self):
        plan = self.run_wizard(wizard(), "desktop", "local-decision", "install", "all", True, False, False, "go")
        self.assertEqual(plan["OLLAMA"], "install")
        self.assertEqual(plan["OLLAMA_PULL"], "nimble")
        self.assertEqual((plan["SYSTEM_DEPS"], plan["DOWNLOAD_MODELS"], plan["PROFILE"]), ("all", "true", "local-decision"))

    def test_cloud_profile_does_not_need_ollama(self):
        plan = self.run_wizard(wizard(), "desktop", "cloud", "none", "base", True, False, False, "go")
        self.assertEqual((plan["OLLAMA"], plan["OLLAMA_PULL"]), ("none", ""))

    def test_profile_later_asks_which_ollama_model(self):
        plan = self.run_wizard(wizard(), "desktop", None, "use", ["gemma4:12b"], "none", True, False, True, "go",
                               installed=True)
        self.assertEqual((plan["OLLAMA"], plan["OLLAMA_PULL"], plan["PROFILE"]), ("use", "gemma4:12b", ""))
        self.assertEqual(plan["WITH_SERVICE"], "true")

    def test_server_asks_listening_address(self):
        # Profil cloud sur un serveur : ni mot-clé ni Whisper, aucune question sur les modèles
        plan = self.run_wizard(wizard(), "server", "cloud", "none", "base", "127.0.0.1", True, False, "go")
        self.assertEqual((plan["MODE"], plan["GATEWAY_BIND"], plan["ACCOUNTS"]), ("server", "127.0.0.1", "true"))

    def test_disabled_questions_are_skipped(self):
        w = wizard("--system-deps", "false", "--ollama", "false", "--models", "false", "--accounts", "false")
        plan = self.run_wizard(w, "desktop", "mix", False, "go")
        self.assertEqual((plan["SYSTEM_DEPS"], plan["OLLAMA"], plan["DOWNLOAD_MODELS"]), ("none", "none", "false"))
        self.assertEqual(plan["ACCOUNTS"], "")  # question retirée : le .env décide

    def test_go_back_returns_to_previous_question(self):
        # ← à la question Ollama (3e question) : retour au choix du profil
        fake = answers("desktop", "cloud", "local-lfm", "install", "all", True, False, False, "go")
        state = {"calls": 0}

        def choose_with_back(title, options, index=0, can_go_back=False):
            state["calls"] += 1
            if state["calls"] == 3:
                self.assertTrue(can_go_back)
                raise iw.GoBack
            return fake(title, options, index, can_go_back)

        with patch.object(iw, "choose", choose_with_back), patch.object(iw, "answered"), patch.object(iw, "note"), \
                patch.object(iw.shutil, "which", return_value=None), \
                patch.object(iw, "ollama_reachable", return_value=False), \
                patch.object(iw, "last_profile", return_value=None), patch("sys.stderr"):
            w = wizard()
            self.assertTrue(w.run())
        self.assertEqual(w.plan()["PROFILE"], "local-lfm")
        self.assertEqual(w.plan()["OLLAMA_PULL"], "lfm3-audio")


if __name__ == "__main__":
    unittest.main()
