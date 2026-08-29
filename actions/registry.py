"""
Registre dynamique et auto-découverte des actions système SmartHome.
Scanne automatiquement le dossier actions/definitions/ et charge toutes les actions disponibles.
"""

import sys
import importlib
import pkgutil
import inspect
from pathlib import Path
from typing import Dict, List, Optional

# Assure l'accessibilité de la racine
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.base import BaseAction, CommandDefinition


class ActionRegistry:
    """Gestionnaire de chargement et registre de commandes."""

    def __init__(self, definitions_dir: Optional[Path] = None):
        self.definitions_dir = definitions_dir or (Path(__file__).resolve().parent / "definitions")
        self._actions: Dict[str, BaseAction] = {}
        self.reload()

    def register(self, action: BaseAction):
        """Enregistre une action dans le registre."""
        tag = action.tag.upper()
        self._actions[tag] = action

    def get(self, tag: str) -> Optional[BaseAction]:
        """Recherche une action par son tag (insensible à la casse)."""
        return self._actions.get(tag.upper())

    def get_all(self) -> List[BaseAction]:
        """Retourne la liste des actions activées."""
        return [act for act in self._actions.values() if act.enabled]

    @property
    def actions(self) -> Dict[str, BaseAction]:
        return self._actions

    def reload(self):
        """Scanne le répertoire definitions/ et charge tous les modules d'actions."""
        self._actions.clear()

        if not self.definitions_dir.exists():
            return

        # Parcours des modules python dans definitions/
        package_prefix = "actions.definitions."
        for finder, module_name, is_pkg in pkgutil.iter_modules([str(self.definitions_dir)]):
            if module_name.startswith("__"):
                continue

            full_module_name = f"{package_prefix}{module_name}"
            try:
                if full_module_name in sys.modules:
                    module = importlib.reload(sys.modules[full_module_name])
                else:
                    module = importlib.import_module(full_module_name)

                # 1. Si le module expose une liste explicite ACTIONS
                if hasattr(module, "ACTIONS") and isinstance(module.ACTIONS, (list, tuple)):
                    for act in module.ACTIONS:
                        if isinstance(act, BaseAction):
                            self.register(act)

                # 2. Découverte automatique des classes dérivées de BaseAction
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseAction) and obj is not BaseAction:
                        try:
                            instance = obj()
                            if instance.tag.upper() not in self._actions:
                                self.register(instance)
                        except Exception:
                            # Ignorer si la classe nécessite des paramètres spécifiques
                            pass

            except Exception as e:
                print(f"⚠️ [ActionRegistry] Erreur lors du chargement de {module_name} : {e}")


# Instance singleton globale
_global_registry = ActionRegistry()
COMMAND_REGISTRY = _global_registry.actions


def get_all_commands() -> List[BaseAction]:
    """Retourne la liste des commandes activées."""
    return _global_registry.get_all()


def get_command_by_tag(tag: str) -> Optional[BaseAction]:
    """Recherche une commande par son tag exact (insensible à la casse)."""
    return _global_registry.get(tag)


def register_action(action: BaseAction):
    """Enregistre dynamiquement une action supplémentaire."""
    _global_registry.register(action)


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/registry.py")
    print(f"Nombre d'actions découvertes : {len(COMMAND_REGISTRY)}")
    for tag, act in COMMAND_REGISTRY.items():
        print(f"  • [{tag}] ({act.script_name}) -> {act.description}")
