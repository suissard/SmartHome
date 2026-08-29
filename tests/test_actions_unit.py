#!/usr/bin/env python3
"""
🧪 SmartHome — Suite de Tests Unitaires pour l'Architecture Modulaire des Actions
Valide l'auto-découverte (ActionRegistry), les définitions autonomes (BaseAction),
la syntaxe des scripts bash embarqués (bash -n), l'extraction regex,
le prompt dynamique et l'exécution sécurisée (Mocks / Dry-Run).
Garantit qu'aucune extinction ou redémarrage réel n'est jamais déclenché.
"""

import sys
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Inclusion de la racine du projet
ROOT_DIR = Path(__file__).resolve().parent.parent
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

    def test_all_actions_inherit_from_base_action_with_script(self):
        """Vérifie que chaque action enregistrée est une BaseAction avec un script bash non-vide."""
        for tag, action in COMMAND_REGISTRY.items():
            self.assertIsInstance(action, BaseAction, f"L'action [{tag}] n'hérite pas de BaseAction")
            self.assertTrue(action.tag, f"Tag vide pour {action}")
            self.assertTrue(action.description, f"Description vide pour [{tag}]")
            self.assertTrue(action.script_code.strip(), f"script_code vide pour [{tag}]")

    def test_all_embedded_bash_scripts_syntax(self):
        """Vérifie la syntaxe de tous les scripts bash embarqués avec 'bash -n'."""
        for tag, action in COMMAND_REGISTRY.items():
            with self.subTest(tag=tag):
                res = subprocess.run(["bash", "-n"], input=action.script_code, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"Erreur de syntaxe bash dans [{tag}] : {res.stderr}")

    def test_custom_action_registration(self):
        """Vérifie l'enregistrement dynamique d'une action personnalisée."""
        class CustomAction(BaseAction):
            def __init__(self):
                super().__init__(
                    tag="CUSTOM_TEST_ACTION",
                    description="Action dynamique de test",
                    script_code='echo "Custom action executed: $1"'
                )

        custom = CustomAction()
        register_action(custom)
        self.assertIn("CUSTOM_TEST_ACTION", COMMAND_REGISTRY)
        self.assertEqual(get_command_by_tag("CUSTOM_TEST_ACTION"), custom)
        # Nettoyage
        COMMAND_REGISTRY.pop("CUSTOM_TEST_ACTION", None)


class TestActionDefinitionsBuildArgs(unittest.TestCase):
    """Tests sur le formatage d'arguments de chaque classe d'action."""

    def test_volume_actions_build_args(self):
        """Vérifie les arguments pour VOLUME, MUTE et UNMUTE."""
        vol_act = get_command_by_tag("VOLUME")
        mute_act = get_command_by_tag("MUTE")
        unmute_act = get_command_by_tag("UNMUTE")

        self.assertEqual(vol_act.build_args("50"), ["50"])
        self.assertEqual(vol_act.build_args(""), ["toggle"])
        self.assertEqual(mute_act.build_args(), ["mute"])
        self.assertEqual(unmute_act.build_args(), ["unmute"])

    def test_media_actions_build_args(self):
        """Vérifie les arguments pour le multimédia."""
        play_act = get_command_by_tag("MEDIA_PLAY_PAUSE")
        next_act = get_command_by_tag("MEDIA_NEXT")
        prev_act = get_command_by_tag("MEDIA_PREV")

        self.assertEqual(play_act.build_args(), ["play-pause"])
        self.assertEqual(next_act.build_args(), ["next"])
        self.assertEqual(prev_act.build_args(), ["previous"])

    def test_notify_and_open_app_build_args(self):
        """Vérifie les arguments pour NOTIFY et OPEN."""
        notify_act = get_command_by_tag("NOTIFY")
        open_act = get_command_by_tag("OPEN")

        self.assertEqual(notify_act.build_args("Sortir le chien"), ["Sortir le chien"])
        self.assertEqual(open_act.build_args("firefox"), ["firefox"])


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
        """Vérifie que manager.py délègue fidèlement à BaseAction.execute()."""
        action = {
            "tag": "MEDIA_NEXT",
            "args": "",
            "definition": get_command_by_tag("MEDIA_NEXT")
        }
        self.manager.execute_action(action, dry_run=False)
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        self.assertEqual(cmd_args[0], "bash")
        self.assertEqual(cmd_args[1], "-c")
        self.assertEqual(cmd_args[3], "_")
        self.assertEqual(cmd_args[4], "next")

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


class TestSafeDirectExecution(unittest.TestCase):
    """Exécution synchrone réelle et sécurisée des actions inoffensives."""

    def test_safe_action_notify(self):
        """Exécute l'action NOTIFY avec des paramètres de test."""
        action = get_command_by_tag("NOTIFY")
        code, stdout, stderr = action.execute_sync("Test unitaire d'action embarquée")
        self.assertEqual(code, 0, f"NOTIFY a échoué : {stderr}")

    def test_safe_action_media(self):
        """Exécute l'action MEDIA_PLAY_PAUSE (contrôle multimédia / D-Bus)."""
        action = get_command_by_tag("MEDIA_PLAY_PAUSE")
        code, stdout, stderr = action.execute_sync()
        self.assertEqual(code, 0, f"MEDIA_PLAY_PAUSE a échoué : {stderr}")

    def test_safe_action_volume_reversible(self):
        """Exécute l'action VOLUME de manière réversible (up puis down)."""
        action = get_command_by_tag("VOLUME")
        code_up, _, err_up = action.execute_sync("up")
        self.assertEqual(code_up, 0, f"VOLUME up a échoué : {err_up}")
        code_down, _, err_down = action.execute_sync("down")
        self.assertEqual(code_down, 0, f"VOLUME down a échoué : {err_down}")

    def test_safe_action_open_app_invalid(self):
        """Vérifie que OPEN retourne un code d'erreur sur une application inexistante."""
        action = get_command_by_tag("OPEN")
        code, _, _ = action.execute_sync("application_inexistante_test_xyz")
        self.assertNotEqual(code, 0, "OPEN aurait dû échouer pour une application inexistante")


if __name__ == "__main__":
    unittest.main(verbosity=2)
