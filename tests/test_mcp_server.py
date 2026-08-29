#!/usr/bin/env python3
"""
🧪 SmartHome — Suite de Tests Unitaires et d'Intégration pour le Serveur MCP
Vérifie :
- L'initialisation du serveur MCP (nom, outils, ressources, prompts)
- L'appel de tous les outils (Tools)
- La lecture et le format des ressources (Resources)
- La génération des templates de prompts (Prompts)
- L'absence d'effets de bord destructeurs
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Inclusion de la racine du projet
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp_server import app, _get_tts, _get_feedback, _get_ducker, _get_transcriber
from actions.registry import COMMAND_REGISTRY


class TestSmartHomeMCPServer(unittest.IsolatedAsyncioTestCase):
    """Tests automatisés pour le serveur MCP SmartHome."""

    async def test_server_metadata_and_tools_count(self):
        """Vérifie que le serveur MCP expose tous les outils attendus."""
        self.assertEqual(app.name, "smarthome")
        
        tools = await app.list_tools()
        tool_names = {t.name for t in tools}

        expected_tools = {
            "list_actions",
            "execute_action",
            "set_volume",
            "media_control",
            "send_notification",
            "open_application",
            "lock_session",
            "screen_off",
            "system_power",
            "tts_speak",
            "play_feedback_sound",
            "set_system_ducking",
            "stt_transcribe_file",
            "ask_assistant",
            "get_conversation_history",
            "clear_conversation_history",
        }
        self.assertTrue(
            expected_tools.issubset(tool_names),
            f"Outils manquants : {expected_tools - tool_names}"
        )

    async def test_list_actions_tool(self):
        """Vérifie le fonctionnement de l'outil list_actions."""
        res = await app.call_tool("list_actions", {})
        self.assertIsNotNone(res)
        self.assertTrue(len(res.content) > 0)
        # Vérifie que les tags majeurs sont présents dans la sortie
        text_full = "".join([c.text for c in res.content if hasattr(c, "text")])
        self.assertIn("VOLUME", text_full)
        self.assertIn("NOTIFY", text_full)
        self.assertIn("OPEN", text_full)

    async def test_execute_action_dry_run(self):
        """Vérifie l'exécution d'une action en mode dry_run."""
        res = await app.call_tool("execute_action", {"tag": "VOLUME", "args": "50", "dry_run": True})
        self.assertTrue(len(res.content) > 0)
        first_text = res.content[0].text
        self.assertIn("DRY RUN", first_text)
        self.assertIn("VOLUME", first_text)

    async def test_execute_action_unknown_tag(self):
        """Vérifie le comportement face à un tag d'action inconnu."""
        res = await app.call_tool("execute_action", {"tag": "NON_EXISTENT_TAG"})
        first_text = res.content[0].text
        self.assertIn("Action inconnue", first_text)

    async def test_set_volume_tool(self):
        """Vérifie l'outil set_volume avec dry_run/mock."""
        with patch("mcp_server.execute_action") as mock_exec:
            mock_exec.return_value = "Volume réglé"
            from mcp_server import set_volume
            out = set_volume("40")
            mock_exec.assert_called_with("VOLUME", "40")

            out_mute = set_volume("mute")
            mock_exec.assert_called_with("MUTE")

    async def test_media_control_tool(self):
        """Vérifie l'outil media_control."""
        with patch("mcp_server.execute_action") as mock_exec:
            mock_exec.return_value = "Média contrôlé"
            from mcp_server import media_control
            media_control("next")
            mock_exec.assert_called_with("MEDIA_NEXT")

            media_control("previous")
            mock_exec.assert_called_with("MEDIA_PREV")

            media_control("play-pause")
            mock_exec.assert_called_with("MEDIA_PLAY_PAUSE")

    async def test_send_notification_tool(self):
        """Vérifie l'outil send_notification."""
        with patch("mcp_server.execute_action") as mock_exec:
            mock_exec.return_value = "Notification envoyée"
            from mcp_server import send_notification
            send_notification("Rappel réunion", title="Alerte")
            mock_exec.assert_called_with("NOTIFY", "Alerte Rappel réunion")

    async def test_open_application_tool(self):
        """Vérifie l'outil open_application."""
        with patch("mcp_server.execute_action") as mock_exec:
            mock_exec.return_value = "Application lancée"
            from mcp_server import open_application
            open_application("firefox")
            mock_exec.assert_called_with("OPEN", "firefox")

    async def test_system_power_tool_safety(self):
        """Vérifie le routage sécurisé de l'outil system_power."""
        with patch("mcp_server.execute_action") as mock_exec:
            mock_exec.return_value = "Action simulée"
            from mcp_server import system_power
            system_power("shutdown")
            mock_exec.assert_called_with("SHUTDOWN")

            system_power("reboot")
            mock_exec.assert_called_with("REBOOT")

            invalid_out = system_power("invalid_cmd")
            self.assertIn("non reconnue", invalid_out)

    async def test_conversation_history_tools(self):
        """Vérifie la consultation et la réinitialisation de l'historique conversationnel."""
        from llm.llm import add_history_message, clear_history
        clear_history()
        add_history_message("user", "Bonjour assistant")
        add_history_message("assistant", "Bonjour ! Comment puis-je vous aider ?")

        res_hist = await app.call_tool("get_conversation_history", {})
        self.assertTrue(len(res_hist.content) > 0)
        hist_text = "".join([c.text for c in res_hist.content])
        self.assertIn("Bonjour assistant", hist_text)

        res_clear = await app.call_tool("clear_conversation_history", {})
        clear_text = res_clear.content[0].text
        self.assertIn("réinitialisé", clear_text)

        res_empty = await app.call_tool("get_conversation_history", {})
        empty_text = "".join([c.text for c in res_empty.content])
        self.assertNotIn("Bonjour assistant", empty_text)

    async def test_audio_feedback_sound_tool(self):
        """Vérifie le déclenchement de play_feedback_sound avec mock."""
        with patch("mcp_server._get_feedback") as mock_fb_getter:
            mock_fb = MagicMock()
            mock_fb_getter.return_value = mock_fb
            from mcp_server import play_feedback_sound
            msg = play_feedback_sound("wake", volume=0.7)
            mock_fb.play_sound.assert_called_with("wake", volume=0.7)
            self.assertIn("wake", msg)

    async def test_ducking_tool(self):
        """Vérifie le déclenchement du ducking avec mock."""
        with patch("mcp_server._get_ducker") as mock_ducker_getter:
            mock_ducker = MagicMock()
            mock_ducker.duck.return_value = True
            mock_ducker_getter.return_value = mock_ducker
            from mcp_server import set_system_ducking

            msg_duck = set_system_ducking(duck=True, volume_percent=15)
            mock_ducker.duck.assert_called_with(target_percent=15)
            self.assertIn("activée", msg_duck)

            msg_unduck = set_system_ducking(duck=False)
            mock_ducker.unduck.assert_called_once()
            self.assertIn("rétabli", msg_unduck)

    async def test_resources_availability_and_valid_json(self):
        """Vérifie que toutes les ressources MCP sont enregistrées et retournent du JSON valide."""
        resources = await app.list_resources()
        resource_uris = {r.uri for r in resources}

        expected_resources = {
            "smarthome://status",
            "smarthome://actions",
            "smarthome://history",
            "smarthome://config",
        }
        self.assertEqual(expected_resources, resource_uris)

        for uri in expected_resources:
            with self.subTest(uri=uri):
                res = await app.read_resource(uri)
                self.assertTrue(len(res) > 0)
                content_str = res[0].content
                # Vérifie que le contenu est un JSON valide décodable
                data = json.loads(content_str)
                self.assertIsNotNone(data)

    async def test_prompts_availability_and_generation(self):
        """Vérifie que les prompts MCP sont enregistrés et retournent des messages exploitables."""
        prompts = await app.list_prompts()
        prompt_names = {p.name for p in prompts}

        expected_prompts = {"smarthome_assistant", "smart_home_planner"}
        self.assertTrue(expected_prompts.issubset(prompt_names))

        for pname in expected_prompts:
            with self.subTest(prompt=pname):
                p_res = await app.get_prompt(pname)
                self.assertIsNotNone(p_res)
                self.assertTrue(len(p_res.messages) > 0)
                msg_text = p_res.messages[0].content.text
                self.assertTrue(len(msg_text) > 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
