"""
Module de compatibilité pour l'accès aux commandes et définitions d'actions.
Redirige vers actions.base et actions.registry.
"""

from actions.base import BaseAction, CommandDefinition
from actions.registry import (
    COMMAND_REGISTRY,
    ActionRegistry,
    get_all_commands,
    get_command_by_tag,
    register_action
)

__all__ = [
    "BaseAction",
    "CommandDefinition",
    "COMMAND_REGISTRY",
    "ActionRegistry",
    "get_all_commands",
    "get_command_by_tag",
    "register_action"
]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test de compatibilité actions/commands.py")
    print(f"Commandes disponibles via commands.py : {len(COMMAND_REGISTRY)}")
    for cmd in get_all_commands():
        print(f"  - [{cmd.tag}] : {cmd.description}")
