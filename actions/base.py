"""
Base d'abstraction pour les actions système de SmartHome.
Chaque action hérite de BaseAction et encapsule ses métadonnées et sa logique d'exécution.
"""

from dataclasses import dataclass, field
import os
import re
import shlex
from pathlib import Path
from typing import Optional, List


@dataclass
class BaseAction:
    """Classe de base représentant une commande système exécutable."""
    tag: str
    description: str
    script_name: str
    has_args: bool = False
    args_hint: str = ""
    example_prompt: str = ""
    example_response: str = ""
    enabled: bool = True

    # Regex compilée pour détecter ce tag spécifique dans une réponse LLM
    _pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._init_pattern()

    def _init_pattern(self):
        if self.has_args:
            pattern_str = rf"\[{re.escape(self.tag)}(?:\s+([^\]]+))?\]"
        else:
            pattern_str = rf"\[{re.escape(self.tag)}\]"
        self._pattern = re.compile(pattern_str, flags=re.IGNORECASE)

    @property
    def pattern(self) -> re.Pattern:
        if self._pattern is None:
            self._init_pattern()
        return self._pattern

    def get_script_path(self, scripts_dir: Path) -> Path:
        """Retourne le chemin absolu vers le script bash associé."""
        return scripts_dir / self.script_name

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        """Construit la commande complète sous forme de liste d'arguments pour subprocess.
        Cette méthode peut être surchargée par chaque action spécifique.
        """
        script_path = self.get_script_path(scripts_dir)
        cmd_exec = [str(script_path)]

        args = (args or "").strip()
        if args:
            try:
                cmd_exec.extend(shlex.split(args))
            except Exception:
                cmd_exec.extend(args.split())

        return cmd_exec


# Alias de compatibilité
CommandDefinition = BaseAction


if __name__ == "__main__":
    print("🧪 [DEBUG] Test de BaseAction")
    sample_action = BaseAction(
        tag="TEST",
        description="Action de test",
        script_name="test.sh",
        has_args=True,
        args_hint="<arg>"
    )
    print(f"Action : {sample_action.tag}")
    print(f"Pattern : {sample_action.pattern.pattern}")
    print(f"Exemple match : {sample_action.pattern.search('[TEST hello] text')}")
