"""
Registre d'outils unifié : actions système locales + outils des serveurs MCP connectés.

Chaque outil a un schéma JSON (function calling), un niveau de danger et un exécuteur.
Les outils "confirm" passent par une politique de confirmation unique (`set_confirmation_handler`) :
- main.py installe une confirmation vocale ;
- une session distante fournit son propre gestionnaire (question envoyée au client) ;
- sans gestionnaire (ex: serveur MCP), un outil dangereux est refusé.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

# Contrainte des API OpenAI / Ollama sur les noms de fonctions
_INVALID_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass
class Tool:
    """Outil appelable par le LLM."""
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], str]
    danger: str = "safe"          # "safe" | "confirm"
    source: str = "local"         # "local" ou nom du serveur MCP
    # Valeurs possibles de l'argument "args" d'une action locale, pour les modèles de décision (voir llm/decision.py)
    decision_choices: Optional[dict[str, str]] = None

    def schema(self) -> dict:
        """Définition au format function calling (compatible OpenAI et Ollama)."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass
class ToolCall:
    """Appel d'outil demandé par le LLM."""
    name: str
    arguments: dict = field(default_factory=dict)
    id: str = ""


@dataclass
class ToolResult:
    call: ToolCall
    output: str
    executed: bool


# ==========================================
# Politique de confirmation des actions dangereuses
# ==========================================
ConfirmationHandler = Callable[[str], bool]
_confirmation_handler: Optional[ConfirmationHandler] = None


def set_confirmation_handler(handler: Optional[ConfirmationHandler]):
    """Installe la fonction qui demande confirmation à l'utilisateur (reçoit une description, retourne True si accepté)."""
    global _confirmation_handler
    _confirmation_handler = handler


def request_confirmation(
    description: str,
    settings: Optional[Settings] = None,
    handler: Optional[ConfirmationHandler] = None,
) -> bool:
    """Retourne True si l'action dangereuse décrite peut être exécutée.
    `handler` (propre à une session) est prioritaire sur le gestionnaire global."""
    s = settings or get_settings()
    if not s.ACTIONS_CONFIRM_DANGEROUS:
        return True
    handler = handler or _confirmation_handler
    if handler is None:
        print(f"⛔ [TOOLS] « {description} » refusé : confirmation requise mais aucun moyen de la demander.")
        return False
    try:
        return bool(handler(description))
    except Exception as e:
        print(f"⚠️ [TOOLS] Erreur pendant la confirmation : {e}")
        return False


# ==========================================
# Registre
# ==========================================
class ToolRegistry:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> Tool:
        name = _INVALID_NAME_CHARS.sub("_", tool.name)[:64]
        if name in self._tools:
            # Collision (ex: même outil sur deux serveurs) : préfixe par la source
            name = _INVALID_NAME_CHARS.sub("_", f"{tool.source}__{tool.name}")[:64]
        tool.name = name
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def call(self, call: ToolCall, confirm: Optional[ConfirmationHandler] = None) -> ToolResult:
        """Exécute un appel d'outil (avec confirmation si nécessaire). Ne lève jamais : l'erreur devient le résultat."""
        tool = self.get(call.name)
        if tool is None:
            return ToolResult(call, f"Outil inconnu : {call.name}", executed=False)

        if tool.danger == "confirm":
            summary = tool.description
            if call.arguments:
                summary += f" ({json.dumps(call.arguments, ensure_ascii=False)})"
            if not request_confirmation(summary, self.settings, confirm):
                return ToolResult(call, "Action annulée : l'utilisateur n'a pas confirmé.", executed=False)

        print(f"🛠️ [TOOLS] {tool.name}({json.dumps(call.arguments, ensure_ascii=False)})")
        try:
            return ToolResult(call, tool.handler(call.arguments) or "OK", executed=True)
        except Exception as e:
            return ToolResult(call, f"Erreur lors de l'exécution de {tool.name} : {e}", executed=False)


def _action_tool(action, settings: Settings) -> Tool:
    def handler(arguments: dict) -> str:
        code, out, err = action.execute_sync(str(arguments.get("args", "")), timeout=settings.ACTIONS_TIMEOUT)
        if code == 0:
            return f"Succès. {out.strip()}".strip()
        return f"Échec (code {code}) : {(err or out).strip()}"

    return Tool(
        name=action.tool_name,
        description=action.description,
        parameters=action.parameters,
        handler=handler,
        danger=action.danger,
        source="local",
        decision_choices=action.decision_choices() if action.has_args else None,
    )


def _mcp_danger(mcp_tool, server_config: dict) -> str:
    """Niveau de danger d'un outil MCP : forcé par la config du serveur ("tool_danger"), sinon d'après ses annotations."""
    forced = str(server_config.get("tool_danger", "auto")).lower()
    if forced in ("safe", "confirm"):
        return forced
    ann = getattr(mcp_tool, "annotations", None)
    if ann is not None:
        if getattr(ann, "read_only_hint", None) or getattr(ann, "readOnlyHint", None):
            return "safe"
        if getattr(ann, "destructive_hint", None) is False or getattr(ann, "destructiveHint", None) is False:
            return "safe"
    # Spécification MCP : sans annotation, un outil est supposé potentiellement destructeur
    return "confirm"


def _mcp_tool(hub, server_name: str, server_config: dict, mcp_tool) -> Tool:
    raw_name = getattr(mcp_tool, "name", "")
    schema = getattr(mcp_tool, "input_schema", None) or getattr(mcp_tool, "inputSchema", None) or {"type": "object", "properties": {}}
    return Tool(
        name=raw_name,
        description=(getattr(mcp_tool, "description", "") or raw_name).strip().split("\n")[0],
        parameters=schema,
        handler=lambda arguments: hub.call_tool(raw_name, arguments),
        danger=_mcp_danger(mcp_tool, server_config),
        source=server_name,
    )


def _expose_mcp_server(server_name: str, server_config: dict) -> bool:
    """Un serveur MCP n'est proposé au LLM que si `expose_to_llm` n'est pas faux et s'il ne s'agit pas
    du propre serveur MCP de SmartHome (ses outils doublonneraient les actions locales)."""
    if server_config.get("expose_to_llm") is False:
        return False
    if any("mcp_server.py" in str(arg) for arg in server_config.get("args", [])):
        print(f"ℹ️ [TOOLS] Serveur MCP '{server_name}' ignoré pour le LLM (c'est SmartHome lui-même).")
        return False
    return True


def build_tool_registry(settings: Optional[Settings] = None, include_mcp: bool = True) -> ToolRegistry:
    """Construit le registre à partir des actions activées et, si le hub est connecté, des outils MCP."""
    s = settings or get_settings()
    registry = ToolRegistry(s)

    if s.ACTIONS_ENABLED:
        from actions.registry import get_all_commands
        for action in get_all_commands():
            registry.add(_action_tool(action, s))

    if include_mcp and s.MCP_CLIENT_ENABLED:
        from core.mcp_hub import get_mcp_hub
        hub = get_mcp_hub()
        for server_name, conn in hub.servers.items():
            if not conn.is_connected or not _expose_mcp_server(server_name, conn.config):
                continue
            for mcp_tool in conn.tools:
                registry.add(_mcp_tool(hub, server_name, conn.config, mcp_tool))

    return registry


def parse_arguments(raw: Any) -> dict:
    """Normalise les arguments d'un appel (dict, chaîne JSON ou vide)."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"args": parsed}
        except json.JSONDecodeError:
            return {"args": raw}
    return {}


if __name__ == "__main__":
    print("🧪 [DEBUG] Outils disponibles pour le LLM (actions locales, sans connexion MCP) :")
    for t in build_tool_registry(include_mcp=False).all():
        print(f"  • {t.name:<18} [{t.danger:<7}] {t.description}")
