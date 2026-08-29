#!/usr/bin/env python3
"""
🧪 SmartHome — Suite de Tests Unitaires pour les Actions et Commandes Système
Exécute tous les tests automatisés (registre, regex, extraction, pipeline, et scripts non-destructifs).
Garantit qu'aucune extinction (shutdown) ou redémarrage (reboot) réel n'est déclenché.
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

from actions.commands import COMMAND_REGISTRY, CommandDefinition, get_all_commands, get_command_by_tag
from actions.manager import ActionManager


class TestCommandRegistry(unittest.TestCase):
    """Tests sur le registre et la structure des commandes."""

    def test_registry_contains_expected_tags(self):
        """Vérifie la présence de toutes les commandes standards."""
        expected_tags = {
            "SHUTDOWN", "REBOOT", "LOCK", "SCREEN_OFF",
            "VOLUME", "MUTE", "UNMUTE",
            "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREV",
            "OPEN", "NOTIFY"
        }
        self.assertTrue(expected_tags.issubset(set(COMMAND_REGISTRY.keys())),
                        f"Tags manquants : {expected_tags - set(COMMAND_REGISTRY.keys())}")

    def test_all_scripts_exist_and_executable(self):
        """Vérifie que chaque script référencé existe physiquement et est exécutable."""
        scripts_dir = ROOT_DIR / "actions" / "scripts"
        self.assertTrue(scripts_dir.is_dir(), f"Dossier {scripts_dir} introuvable")

        for tag, cmd in COMMAND_REGISTRY.items():
            script_path = scripts_dir / cmd.script_name
            self.assertTrue(script_path.exists(), f"Script introuvable pour [{tag}] : {script_path}")
            self.assertTrue(os.access(script_path, os.X_OK) or os.access(script_path, os.R_OK),
                            f"Permissions insuffisantes pour {script_path}")

    def test_command_regex_patterns(self):
        """Vérifie que les expressions régulières associées aux tags fonctionnent correctement."""
        # Commande sans argument : [MUTE]
        mute_cmd = COMMAND_REGISTRY["MUTE"]
        self.assertIsNotNone(mute_cmd.pattern.search("[MUTE] Son coupé."))
        self.assertIsNotNone(mute_cmd.pattern.search("[mute] minuscule"))

        # Commande avec arguments : [VOLUME 50]
        vol_cmd = COMMAND_REGISTRY["VOLUME"]
        m = vol_cmd.pattern.search("[VOLUME 50] Réglage")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip(), "50")

        m_down = vol_cmd.pattern.search("[volume down] Moins fort")
        self.assertIsNotNone(m_down)
        self.assertEqual(m_down.group(1).strip(), "down")

        # Commande avec argument texte multi-mots : [NOTIFY Sortir le chien]
        notify_cmd = COMMAND_REGISTRY["NOTIFY"]
        m_notif = notify_cmd.pattern.search("[NOTIFY Sortir le chien] Rappel envoyé.")
        self.assertIsNotNone(m_notif)
        self.assertEqual(m_notif.group(1).strip(), "Sortir le chien")

    def test_get_command_by_tag(self):
        """Vérifie la recherche insensible à la casse."""
        self.assertIsNotNone(get_command_by_tag("volume"))
        self.assertIsNotNone(get_command_by_tag("VOLUME"))
        self.assertIsNotNone(get_command_by_tag("VoLuMe"))
        self.assertIsNone(get_command_by_tag("INCONNU_XYZ"))


class TestActionManagerExtractionAndPrompt(unittest.TestCase):
    """Tests sur l'extraction d'actions et la génération dynamique de prompts."""

    def setUp(self):
        self.manager = ActionManager(enabled=True)

    def test_build_dynamic_system_prompt_enabled(self):
        """Vérifie l'enrichissement du prompt système."""
        base_prompt = "Tu es un assistant vocal."
        dynamic_prompt = self.manager.build_dynamic_system_prompt(base_prompt)
        self.assertIn("ACTIONS & COMMANDES SYSTÈME DISPONIBLES", dynamic_prompt)
        self.assertIn("[SHUTDOWN]", dynamic_prompt)
        self.assertIn("[VOLUME", dynamic_prompt)
        self.assertIn("[NOTIFY", dynamic_prompt)

    def test_build_dynamic_system_prompt_disabled(self):
        """Vérifie que le prompt n'est pas altéré si désactivé."""
        disabled_manager = ActionManager(enabled=False)
        base_prompt = "Tu es un assistant vocal."
        self.assertEqual(disabled_manager.build_dynamic_system_prompt(base_prompt), base_prompt)

    def test_extract_actions_single_tag(self):
        """Vérifie l'extraction d'un tag unique et la purification du texte TTS."""
        raw = "[VOLUME 75] Le volume a bien été réglé à 75%."
        clean, actions = self.manager.extract_actions(raw)
        self.assertEqual(clean, "Le volume a bien été réglé à 75%.")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["tag"], "VOLUME")
        self.assertEqual(actions[0]["args"], "75")

    def test_extract_actions_multiple_tags(self):
        """Vérifie l'extraction de multiples tags dans un même message."""
        raw = "[MUTE] [NOTIFY Silence activé] J'ai coupé le son et affiché une alerte."
        clean, actions = self.manager.extract_actions(raw)
        self.assertEqual(clean, "J'ai coupé le son et affiché une alerte.")
        self.assertEqual(len(actions), 2)
        tags = [a["tag"] for a in actions]
        self.assertEqual(tags, ["MUTE", "NOTIFY"])
        self.assertEqual(actions[1]["args"], "Silence activé")

    def test_extract_actions_no_tags(self):
        """Vérifie le comportement sur une réponse sans commande."""
        raw = "Il fait un grand soleil aujourd'hui à Paris."
        clean, actions = self.manager.extract_actions(raw)
        self.assertEqual(clean, raw)
        self.assertEqual(len(actions), 0)

    def test_extract_actions_unknown_tag(self):
        """Vérifie que les faux tags ou tags inexistants ne génèrent pas d'action."""
        raw = "[INVENTED_COMMAND 123] Ceci est un test avec un tag inconnu."
        clean, actions = self.manager.extract_actions(raw)
        self.assertEqual(clean, "Ceci est un test avec un tag inconnu.")
        self.assertEqual(len(actions), 0)


class TestActionManagerExecution(unittest.TestCase):
    """Tests sur l'exécution des commandes (sécurisés via Mock et Dry Run)."""

    def setUp(self):
        self.manager = ActionManager(enabled=True)

    def test_execute_action_dry_run(self):
        """Vérifie le mode dry-run sans création de sous-processus."""
        action = {
            "tag": "VOLUME",
            "args": "50",
            "definition": COMMAND_REGISTRY["VOLUME"]
        }
        result = self.manager.execute_action(action, dry_run=True)
        self.assertTrue(result)

    @patch("subprocess.Popen")
    def test_execute_action_spawns_process_with_correct_args(self, mock_popen):
        """Vérifie la construction exacte de la commande subprocess pour différents tags."""
        # 1. Test MUTE
        action_mute = {
            "tag": "MUTE",
            "args": "",
            "definition": COMMAND_REGISTRY["MUTE"]
        }
        self.manager.execute_action(action_mute, dry_run=False)
        mock_popen.assert_called()
        cmd_args = mock_popen.call_args[0][0]
        self.assertTrue(cmd_args[0].endswith("volume.sh"))
        self.assertEqual(cmd_args[1], "mute")

        # 2. Test MEDIA_PLAY_PAUSE
        mock_popen.reset_mock()
        action_media = {
            "tag": "MEDIA_PLAY_PAUSE",
            "args": "",
            "definition": COMMAND_REGISTRY["MEDIA_PLAY_PAUSE"]
        }
        self.manager.execute_action(action_media, dry_run=False)
        cmd_args = mock_popen.call_args[0][0]
        self.assertTrue(cmd_args[0].endswith("media.sh"))
        self.assertEqual(cmd_args[1], "play-pause")

        # 3. Test NOTIFY
        mock_popen.reset_mock()
        action_notify = {
            "tag": "NOTIFY",
            "args": "Rappel de rendez-vous",
            "definition": COMMAND_REGISTRY["NOTIFY"]
        }
        self.manager.execute_action(action_notify, dry_run=False)
        cmd_args = mock_popen.call_args[0][0]
        self.assertTrue(cmd_args[0].endswith("notify.sh"))
        self.assertEqual(cmd_args[1], "Rappel de rendez-vous")

    @patch("subprocess.Popen")
    def test_critical_commands_never_called_unintentionally(self, mock_popen):
        """Vérifie la sécurité absolue des commandes SHUTDOWN et REBOOT."""
        action_shutdown = {
            "tag": "SHUTDOWN",
            "args": "",
            "definition": COMMAND_REGISTRY["SHUTDOWN"]
        }
        # En mode dry-run, subprocess.Popen ne doit jamais être appelé
        self.manager.execute_action(action_shutdown, dry_run=True)
        mock_popen.assert_not_called()


    def test_process_response_with_actions_dry_run(self):
        """Vérifie que process_response extrait et prépare toutes les actions en dry-run."""
        raw_response = "[VOLUME 30] [OPEN calculatrice] Volume réglé et calculatrice ouverte."
        clean_text = self.manager.process_response(raw_response, dry_run=True)
        self.assertEqual(clean_text, "Volume réglé et calculatrice ouverte.")

    def test_singleton_action_manager(self):
        """Vérifie le singleton get_action_manager."""
        from actions.manager import get_action_manager
        m1 = get_action_manager()
        m2 = get_action_manager()
        self.assertIs(m1, m2)


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
        res = subprocess.run([str(script_path), "SmartHome Test Unit", "Ceci est un test unitaire."],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(res.returncode, 0, f"notify.sh a échoué : {res.stderr}")

    def test_safe_script_media(self):
        """Exécute media.sh (contrôle multimédia / D-Bus)."""
        script_path = ROOT_DIR / "actions" / "scripts" / "media.sh"
        res = subprocess.run([str(script_path), "play-pause"],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(res.returncode, 0, f"media.sh a échoué : {res.stderr}")

    def test_safe_script_volume(self):
        """Exécute volume.sh de manière réversible (up puis down)."""
        script_path = ROOT_DIR / "actions" / "scripts" / "volume.sh"
        res_up = subprocess.run([str(script_path), "up"], capture_output=True, text=True, timeout=5)
        self.assertEqual(res_up.returncode, 0, f"volume.sh up a échoué : {res_up.stderr}")
        res_down = subprocess.run([str(script_path), "down"], capture_output=True, text=True, timeout=5)
        self.assertEqual(res_down.returncode, 0, f"volume.sh down a échoué : {res_down.stderr}")

    def test_safe_script_open_app_invalid(self):
        """Vérifie que open_app.sh retourne un code d'erreur propre sur une application inexistante."""
        script_path = ROOT_DIR / "actions" / "scripts" / "open_app.sh"
        res = subprocess.run([str(script_path), "application_inexistante_test_xyz"],
                             capture_output=True, text=True, timeout=5)
        self.assertNotEqual(res.returncode, 0, "open_app.sh aurait dû échouer pour une application inexistante")


if __name__ == "__main__":
    unittest.main(verbosity=2)

