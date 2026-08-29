"""
Module d'actions système pour SmartHome.
"""

from actions.base import BaseAction, CommandDefinition
from actions.registry import (
    COMMAND_REGISTRY,
    ActionRegistry,
    get_all_commands,
    get_command_by_tag,
    register_action
)
from actions.manager import ActionManager, get_action_manager

__all__ = [
    "BaseAction",
    "CommandDefinition",
    "COMMAND_REGISTRY",
    "ActionRegistry",
    "ActionManager",
    "get_action_manager",
    "get_all_commands",
    "get_command_by_tag",
    "register_action"
]
