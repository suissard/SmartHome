#!/usr/bin/env python3
"""
🧪 SmartHome — Suite de Tests Unitaires pour l'Architecture Modulaire des Actions
Valide l'auto-découverte (ActionRegistry), les définitions autonomes (BaseAction),
l'extraction regex, le prompt dynamique et l'exécution sécurisée (Mocks / Dry-Run).
Garantit qu'aucune extinction ou redémarrage réel n'est jamais déclenché.
"""

import os
import sys
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Inclusion de la racine du projet
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.base import BaseAction, CommandDefinition
from actions.registry import (
    COMMAND_REGISTRY,
    ActionRegistry,
    get_all_commands,
    get_command_by_tag,
    register_action
)
from actions.manager import ActionManager, get_action_manager


class TestModularActionRegistry(unittest.TestCase):
    """Tests sur l'auto-découverte et le registre dynamique d'actions."""

    def test_registry_auto_discovery(self):
        """Vérifie que l'auto-découverte charge toutes les commandes attendues."""
        expected_tags = {
            "SHUTDOWN", "REBOOT", "LOCK", "SCREEN_OFF",
            "VOLUME", "MUTE", "UNMUTE",
            "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREV",
            "OPEN", "NOTIFY"
        }
        discovered_tags = set(COMMAND_REGISTRY.keys())
        self.assertTrue(expected_tags.issubset(discovered_tags),
                        f"Tags manquants dans l'auto-découverte : {expected_tags - discovered_tags}")

    def test_all_actions_inherit_from_base_action(self):
        """Vérifie que chaque action enregistrée est bien une instance de BaseAction."""
        for tag, action in COMMAND_REGISTRY.items():
            self.assertIsInstance(action, BaseAction, f"L'action [{tag}] n'hérite pas de BaseAction")
            self.assertTrue(action.tag, f"Tag vide pour {action}")
            self.assertTrue(action.description, f"Description vide pour [{tag}]")
            self.assertTrue(action.script_name, f"script_name vide pour [{tag}]")

    def test_custom_action_registration(self):
        """Vérifie l'enregistrement dynamique d'une action personnalisée."""
        class CustomAction(BaseAction):
            def __init__(self):
                super().__init__(
                    tag="CUSTOM_TEST_ACTION",
                    description="Action dynamique de test",
                    script_name="notify.sh"
                )

        custom = CustomAction()
        register_action(custom)
        self.assertIn("CUSTOM_TEST_ACTION", COMMAND_REGISTRY)
        self.assertEqual(get_command_by_tag("CUSTOM_TEST_ACTION"), custom)
        # Nettoyage
        COMMAND_REGISTRY.pop("CUSTOM_TEST_ACTION", None)


class TestActionDefinitionsBuildCommand(unittest.TestCase):
    """Tests sur la méthode build_command de chaque classe d'action."""

    def setUp(self):
        self.scripts_dir = ROOT_DIR / "actions" / "scripts"

    def test_volume_actions_build_command(self):
        """Vérifie la construction des commandes pour VOLUME, MUTE et UNMUTE."""
        vol_act = get_command_by_tag("VOLUME")
        mute_act = get_command_by_tag("MUTE")
        unmute_act = get_command_by_tag("UNMUTE")

        self.assertIsNotNone(vol_act)
        self.assertIsNotNone(mute_act)
        self.assertIsNotNone(unmute_act)

        # VOLUME avec argument
        cmd = vol_act.build_command(self.scripts_dir, "50")
        self.assertTrue(cmd[0].endswith("volume.sh"))
        self.assertEqual(cmd[1], "50")

        # MUTE
        cmd_mute = mute_act.build_command(self.scripts_dir)
        self.assertTrue(cmd_mute[0].endswith("volume.sh"))
        self.assertEqual(cmd_mute[1], "mute")

        # UNMUTE
        cmd_unmute = unmute_act.build_command(self.scripts_dir)
        self.assertTrue(cmd_unmute[0].endswith("volume.sh"))
        self.assertEqual(cmd_unmute[1], "unmute")

    def test_media_actions_build_command(self):
        """Vérifie la construction des commandes pour le multimédia."""
        play_act = get_command_by_tag("MEDIA_PLAY_PAUSE")
        next_act = get_command_by_tag("MEDIA_NEXT")
        prev_act = get_command_by_tag("MEDIA_PREV")

        self.assertEqual(play_act.build_command(self.scripts_dir)[1], "play-pause")
        self.assertEqual(next_act.build_command(self.scripts_dir)[1], "next")
        self.assertEqual(prev_act.build_command(self.scripts_dir)[1], "previous")

    def test_notify_and_open_app_build_command(self):
        """Vérifie la transmission des messages et arguments pour NOTIFY et OPEN."""
        notify_act = get_command_by_tag("NOTIFY")
        open_act = get_command_by_tag("OPEN")

        cmd_notif = notify_act.build_command(self.scripts_dir, "Sortir le chien")
        self.assertTrue(cmd_notif[0].endswith("notify.sh"))
        self.assertEqual(cmd_notif[1], "Sortir le chien")

        cmd_open = open_act.build_command(self.scripts_dir, "firefox")
        self.assertTrue(cmd_open[0].endswith("open_app.sh"))
        self.assertEqual(cmd_open[1], "firefox")


class TestActionManagerIntegration(unittest.TestCase):
    """Tests du gestionnaire ActionManager découplé."""

    def setUp(self):
        self.manager = ActionManager(enabled=True)

    def test_dynamic_system_prompt(self):
        """Vérifie la génération dynamique du prompt avec toutes les commandes découvertes."""
        base_prompt = "Tu es un assistant vocal domotique."
        prompt = self.manager.build_dynamic_system_prompt(base_prompt)
        self.assertIn("ACTIONS & COMMANDES SYSTÈME DISPONIBLES", prompt)
        self.assertIn("[VOLUME", prompt)
        self.assertIn("[SHUTDOWN]", prompt)
        self.assertIn("[MEDIA_PLAY_PAUSE]", prompt)

    def test_extract_actions_and_clean_tts(self):
        """Vérifie l'extraction et la purification du texte pour la voix."""
        raw = "[NOTIFY Rendez-vous chez le dentiste] Rappel enregistré pour demain."
        clean, actions = self.manager.extract_actions(raw)
        self.assertEqual(clean, "Rappel enregistré pour demain.")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["tag"], "NOTIFY")
        self.assertEqual(actions[0]["args"], "Rendez-vous chez le dentiste")

    def test_execute_action_dry_run(self):
        """Vérifie le mode dry-run universel."""
        action = {
            "tag": "VOLUME",
            "args": "45",
            "definition": get_command_by_tag("VOLUME")
        }
        self.assertTrue(self.manager.execute_action(action, dry_run=True))

    @patch("subprocess.Popen")
    def test_execute_action_delegation(self, mock_popen):
        """Vérifie que manager.py délègue fidèlement la construction de commande à l'action."""
        action = {
            "tag": "MEDIA_NEXT",
            "args": "",
            "definition": get_command_by_tag("MEDIA_NEXT")
        }
        self.manager.execute_action(action, dry_run=False)
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        self.assertTrue(cmd_args[0].endswith("media.sh"))
        self.assertEqual(cmd_args[1], "next")

    @patch("subprocess.Popen")
    def test_safety_critical_commands_never_run_in_tests(self, mock_popen):
        """Garantit la sécurité : SHUTDOWN et REBOOT en dry-run ne lancent aucun processus."""
        for tag in ("SHUTDOWN", "REBOOT"):
            action = {
                "tag": tag,
                "args": "",
                "definition": get_command_by_tag(tag)
            }
            self.manager.execute_action(action, dry_run=True)
            mock_popen.assert_not_called()

    def test_singleton(self):
        """Vérifie le singleton get_action_manager."""
        self.assertIs(get_action_manager(), get_action_manager())


class TestBashScriptsSyntaxAndSafeExecution(unittest.TestCase):
    """Vérification de la syntaxe bash de tous les scripts et exécution réelle des scripts sûrs."""

    def test_all_bash_scripts_syntax(self):
        """Vérifie la syntaxe de tous les fichiers .sh avec bash -n."""
        scripts_dir = ROOT_DIR / "actions" / "scripts"
        sh_files = list(scripts_dir.glob("*.sh"))
        self.assertGreater(len(sh_files), 0, "Aucun script bash trouvé")

        for sh_file in sh_files:
            with self.subTest(script=sh_file.name):
                res = subprocess.run(["bash", "-n", str(sh_file)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"Erreur de syntaxe dans {sh_file.name} : {res.stderr}")

    def test_safe_script_notify(self):
        """Exécute notify.sh avec des paramètres de test sécurisés."""
        script_path = ROOT_DIR / "actions" / "scripts" / "notify.sh"
        res = subprocess.run([str(script_path), "SmartHome Test Unit", "Test modulaire réussi."],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(res.returncode, 0, f"notify.sh a échoué : {res.stderr}")

    def test_safe_script_media(self):
        """Exécute media.sh (contrôle multimédia / D-Bus)."""
        script_path = ROOT_DIR / "actions" / "scripts" / "media.sh"
        res = subprocess.run([str(script_path), "play-pause"],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(res.returncode, 0, f"media.sh a échoué : {res.stderr}")

    def test_safe_script_volume_reversible(self):
        """Exécute volume.sh de manière réversible (up puis down)."""
        script_path = ROOT_DIR / "actions" / "scripts" / "volume.sh"
        res_up = subprocess.run([str(script_path), "up"], capture_output=True, text=True, timeout=5)
        self.assertEqual(res_up.returncode, 0, f"volume.sh up a échoué : {res_up.stderr}")
        res_down = subprocess.run([str(script_path), "down"], capture_output=True, text=True, timeout=5)
        self.assertEqual(res_down.returncode, 0, f"volume.sh down a échoué : {res_down.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
