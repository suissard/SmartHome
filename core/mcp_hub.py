#!/usr/bin/env python3
"""
🔌 SmartHome MCP Client Hub
Gestionnaire de connexions multi-serveurs MCP (Model Context Protocol).
Permet à SmartHome de se connecter à plusieurs serveurs MCP (locaux en stdio ou distants en SSE/HTTP),
de découvrir automatiquement tous leurs outils et de router les appels d'outils vers le serveur approprié.
"""

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Inclusion de la racine du projet
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from core.config import (
    MCP_CLIENT_ENABLED,
    MCP_SERVERS_CONFIG_PATH,
)


class MCPServerConnection:
    """Représente une connexion active à un serveur MCP."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: List[Any] = []
        self.is_connected: bool = False
        self.error_message: Optional[str] = None
        self._exit_stack: Optional[AsyncExitStack] = None

    async def connect(self) -> bool:
        """Établit la connexion avec le serveur MCP et découvre ses outils."""
        self.error_message = None
        self._exit_stack = AsyncExitStack()

        try:
            url = self.config.get("url")
            command = self.config.get("command")

            # 1. Transport Réseau (SSE ou HTTP)
            if url:
                transport_type = self.config.get("transport", "sse").lower()
                headers = self.config.get("headers", {})

                if transport_type in ("http", "streamable-http"):
                    streams = await self._exit_stack.enter_async_context(
                        streamable_http_client(url)
                    )
                else:
                    streams = await self._exit_stack.enter_async_context(
                        sse_client(url, headers=headers)
                    )

                read_stream, write_stream = streams
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )

            # 2. Transport Local (stdio)
            elif command:
                args = self.config.get("args", [])
                env_vars = os.environ.copy()
                if "env" in self.config and isinstance(self.config["env"], dict):
                    env_vars.update(self.config["env"])

                # Résolution des chemins relatifs pour la commande et les arguments
                resolved_cmd = command
                if command.startswith(".venv") or command.startswith("./"):
                    resolved_cmd = str(BASE_DIR / command)

                resolved_args = []
                for a in args:
                    if a.endswith(".py") and not Path(a).is_absolute():
                        resolved_args.append(str(BASE_DIR / a))
                    else:
                        resolved_args.append(a)

                server_params = StdioServerParameters(
                    command=resolved_cmd,
                    args=resolved_args,
                    env=env_vars,
                    cwd=str(BASE_DIR)
                )

                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )

            else:
                self.error_message = "Configuration invalide : ni 'url' ni 'command' spécifié."
                return False

            # Initialisation de la session MCP
            await self.session.initialize()

            # Découverte des outils exposés par le serveur
            tools_response = await self.session.list_tools()
            self.tools = tools_response.tools if hasattr(tools_response, "tools") else []
            self.is_connected = True
            return True

        except Exception as e:
            self.is_connected = False
            self.error_message = str(e)
            if self._exit_stack:
                try:
                    await self._exit_stack.aclose()
                except Exception:
                    pass
                self._exit_stack = None
            return False

    async def disconnect(self):
        """Ferme proprement la session MCP."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None
        self.session = None
        self.is_connected = False
        self.tools.clear()


class MCPClientHub:
    """
    Gestionnaire centralisé de multiples clients MCP.
    Maintient une boucle d'événements en arrière-plan pour offrir
    des interfaces synchrones et asynchrones pour main.py et le LLM.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        enabled: bool = MCP_CLIENT_ENABLED
    ):
        self.enabled = enabled
        self.config_path = config_path or MCP_SERVERS_CONFIG_PATH
        self.servers: Dict[str, MCPServerConnection] = {}
        self.tool_to_server: Dict[str, str] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running: bool = False
        self._lock = threading.Lock()

    def _ensure_background_loop(self):
        """Démarre le thread de boucle d'événements en arrière-plan si nécessaire."""
        with self._lock:
            if self._loop is None or not self._loop.is_running():
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    args=(self._loop,),
                    name="MCPClientHubLoop",
                    daemon=True
                )
                self._thread.start()
                self._is_running = True

    def _run_loop(self, loop: asyncio.AbstractEventLoop):
        """Exécution de la boucle asyncio dédiée."""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def load_config(self) -> Dict[str, Dict[str, Any]]:
        """Charge le fichier JSON de configuration des serveurs MCP."""
        cfg_file = Path(self.config_path)
        if not cfg_file.is_absolute():
            cfg_file = BASE_DIR / cfg_file

        if not cfg_file.exists():
            return {}

        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("mcpServers", data)
        except Exception as e:
            print(f"⚠️ [MCP-HUB] Erreur lecture configuration {cfg_file} : {e}", file=sys.stderr)
            return {}

    async def connect_all_async(self) -> Dict[str, bool]:
        """Se connecte à tous les serveurs activés (asynchrone)."""
        if not self.enabled:
            return {}

        configs = self.load_config()
        self.tool_to_server.clear()
        results = {}

        for server_name, server_cfg in configs.items():
            # Vérifier si le serveur est explicitement activé (défaut: True)
            if not server_cfg.get("enabled", True):
                continue

            conn = MCPServerConnection(server_name, server_cfg)
            success = await conn.connect()
            self.servers[server_name] = conn
            results[server_name] = success

            if success:
                for tool in conn.tools:
                    tool_name = getattr(tool, "name", "")
                    if tool_name:
                        self.tool_to_server[tool_name] = server_name
            else:
                print(f"⚠️ [MCP-HUB] Échec connexion serveur '{server_name}': {conn.error_message}", file=sys.stderr)

        return results

    def connect_all(self) -> Dict[str, bool]:
        """Se connecte à tous les serveurs activés (synchrone)."""
        if not self.enabled:
            return {}
        self._ensure_background_loop()
        future = asyncio.run_coroutine_threadsafe(self.connect_all_async(), self._loop)
        return future.result(timeout=15.0)

    async def disconnect_all_async(self):
        """Ferme toutes les connexions actives (asynchrone)."""
        for conn in self.servers.values():
            if conn.is_connected:
                await conn.disconnect()
        self.servers.clear()
        self.tool_to_server.clear()

    def disconnect_all(self):
        """Ferme toutes les connexions actives (synchrone)."""
        if self._loop and self._loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self.disconnect_all_async(), self._loop)
                future.result(timeout=5.0)
            except Exception:
                pass

            # Arrêt de la boucle
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._loop = None
            self._thread = None
            self._is_running = False

    async def call_tool_async(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """Exécute un outil sur le serveur MCP qui le fournit (asynchrone)."""
        args = arguments or {}
        server_name = self.tool_to_server.get(tool_name)

        if not server_name or server_name not in self.servers:
            return f"❌ Outil MCP '{tool_name}' introuvable sur les serveurs connectés."

        conn = self.servers[server_name]
        if not conn.is_connected or not conn.session:
            return f"❌ Le serveur MCP '{server_name}' n'est pas connecté."

        try:
            res = await conn.session.call_tool(tool_name, args)
            if hasattr(res, "content") and res.content:
                texts = []
                for item in res.content:
                    if hasattr(item, "text") and item.text:
                        texts.append(item.text)
                return "\n".join(texts) if texts else "✅ Outil exécuté sans message de sortie."
            return "✅ Outil exécuté avec succès."
        except Exception as e:
            return f"⚠️ Erreur lors de l'exécution de '{tool_name}' sur '{server_name}' : {e}"

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """Exécute un outil sur le serveur MCP approprié (synchrone)."""
        self._ensure_background_loop()
        future = asyncio.run_coroutine_threadsafe(
            self.call_tool_async(tool_name, arguments),
            self._loop
        )
        return future.result(timeout=30.0)

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Retourne la liste consolidée de tous les outils découverts."""
        consolidated = []
        for server_name, conn in self.servers.items():
            if not conn.is_connected:
                continue
            for t in conn.tools:
                consolidated.append({
                    "server": server_name,
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", ""),
                    "input_schema": getattr(t, "inputSchema", {}),
                })
        return consolidated

    def build_dynamic_prompt_section(self) -> str:
        """
        Construit une section de prompt système détaillant tous les outils
        disponibles sur l'ensemble des serveurs MCP connectés.
        """
        if not self.servers:
            return ""

        sections = []
        for server_name, conn in self.servers.items():
            if not conn.is_connected or not conn.tools:
                continue

            desc = conn.config.get("description", "")
            header = f"Serveur [{server_name}]" + (f" ({desc})" if desc else "") + " :"
            lines = [header]

            for tool in conn.tools:
                t_name = getattr(tool, "name", "")
                t_desc = getattr(tool, "description", "").strip().split("\n")[0]
                lines.append(f"  • {t_name} : {t_desc}")

            sections.append("\n".join(lines))

        if not sections:
            return ""

        return "\n### 🔌 OUTILS & SERVEURS MCP CONNECTÉS :\n" + "\n\n".join(sections)

    def get_status_summary(self) -> Dict[str, Any]:
        """Retourne un résumé de l'état des connexions et des outils."""
        connected_servers = [s for s, c in self.servers.items() if c.is_connected]
        failed_servers = [s for s, c in self.servers.items() if not c.is_connected]
        total_tools = len(self.tool_to_server)

        return {
            "enabled": self.enabled,
            "config_path": self.config_path,
            "connected_servers": connected_servers,
            "failed_servers": failed_servers,
            "total_tools_count": total_tools,
            "tools_by_server": {
                s: len(c.tools) for s, c in self.servers.items() if c.is_connected
            }
        }


# Singleton global pour le Hub Client MCP
_global_mcp_hub: Optional[MCPClientHub] = None


def get_mcp_hub() -> MCPClientHub:
    """Retourne l'instance globale du MCPClientHub."""
    global _global_mcp_hub
    if _global_mcp_hub is None:
        _global_mcp_hub = MCPClientHub()
    return _global_mcp_hub


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du Client Hub Multi-MCP...")
    hub = MCPClientHub()

    print(f"Chargement de la configuration depuis '{hub.config_path}'...")
    results = hub.connect_all()
    print("\n📡 Statut des connexions :")
    for name, success in results.items():
        status_icon = "✅ Connecté" if success else "❌ Échec"
        print(f"  • {name} : {status_icon}")

    tools = hub.get_all_tools()
    print(f"\n🛠️ {len(tools)} outils découverts au total :")
    for t in tools[:8]:
        print(f"  - [{t['server']}] {t['name']} : {t['description'][:60]}...")

    if "list_actions" in hub.tool_to_server:
        print("\n👉 Test d'appel de l'outil 'list_actions' via le hub...")
        output = hub.call_tool("list_actions")
        print(f"Sortie (premiers 200 caractères) :\n{output[:200]}...")

    hub.disconnect_all()
    print("\n✅ Test terminé et connexions fermées.")
