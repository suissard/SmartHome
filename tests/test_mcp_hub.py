#!/usr/bin/env python3
"""
🧪 SmartHome — Suite de Tests Unitaires et d'Intégration pour le Client Hub Multi-MCP
Vérifie :
- Le chargement de la configuration mcp_servers.json
- La connexion aux serveurs MCP locaux (stdio)
- La découverte et l'agrégation des outils de multiples serveurs
- L'exécution d'outils via le hub (asynchrone et synchrone)
- La génération du prompt dynamique d'outils
- La déconnexion propre et la gestion des erreurs
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

from core.mcp_hub import MCPClientHub, MCPServerConnection


class TestMCPClientHub(unittest.IsolatedAsyncioTestCase):
    """Tests automatisés pour le Client Hub Multi-MCP."""

    async def asyncSetUp(self):
        self.hub = MCPClientHub()

    async def asyncTearDown(self):
        await self.hub.disconnect_all_async()

    async def test_load_config(self):
        """Vérifie que la configuration mcp_servers.json est correctement lue."""
        configs = self.hub.load_config()
        self.assertIsInstance(configs, dict)
        self.assertIn("smarthome-local", configs)
        self.assertTrue(configs["smarthome-local"].get("enabled", False))

    async def test_connect_all_async_and_list_tools(self):
        """Vérifie la connexion asynchrone aux serveurs activés et la découverte des outils."""
        results = await self.hub.connect_all_async()
        self.assertIn("smarthome-local", results)
        self.assertTrue(results["smarthome-local"])

        tools = self.hub.get_all_tools()
        self.assertTrue(len(tools) >= 12, f"Trop peu d'outils découverts ({len(tools)})")

        tool_names = {t["name"] for t in tools}
        self.assertIn("list_actions", tool_names)
        self.assertIn("execute_action", tool_names)
        self.assertIn("set_volume", tool_names)

    async def test_call_tool_async_dry_run(self):
        """Vérifie l'exécution d'un outil en mode simulation (dry_run) via le hub."""
        await self.hub.connect_all_async()
        res = await self.hub.call_tool_async(
            "execute_action",
            {"tag": "VOLUME", "args": "42", "dry_run": True}
        )
        self.assertIn("DRY RUN", res)
        self.assertIn("VOLUME", res)

    def test_call_tool_sync(self):
        """Vérifie l'interface synchrone du hub utilisée par main.py."""
        sync_hub = MCPClientHub()
        try:
            results = sync_hub.connect_all()
            self.assertTrue(results.get("smarthome-local", False))

            res = sync_hub.call_tool(
                "execute_action",
                {"tag": "VOLUME", "args": "25", "dry_run": True}
            )
            self.assertIn("DRY RUN", res)
            self.assertIn("VOLUME", res)
        finally:
            sync_hub.disconnect_all()

    async def test_call_unknown_tool(self):
        """Vérifie le retour gracieux lors d'un appel d'outil inexistant."""
        await self.hub.connect_all_async()
        res = await self.hub.call_tool_async("unknown_tool_xyz")
        self.assertIn("introuvable", res)

    async def test_build_dynamic_prompt_section(self):
        """Vérifie que la section de prompt générée contient les serveurs et leurs outils."""
        await self.hub.connect_all_async()
        prompt_sec = self.hub.build_dynamic_prompt_section()
        self.assertIn("OUTILS & SERVEURS MCP CONNECTÉS", prompt_sec)
        self.assertIn("smarthome-local", prompt_sec)
        self.assertIn("set_volume", prompt_sec)

    async def test_status_summary(self):
        """Vérifie le rapport d'état structuré du hub."""
        await self.hub.connect_all_async()
        summary = self.hub.get_status_summary()
        self.assertTrue(summary["enabled"])
        self.assertIn("smarthome-local", summary["connected_servers"])
        self.assertTrue(summary["total_tools_count"] > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
