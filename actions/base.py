"""
Base d'abstraction pour les actions système de SmartHome.
Chaque action hérite de BaseAction et encapsule ses métadonnées et son script d'exécution embarqué.
"""

from dataclasses import dataclass, field
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple


@dataclass
class BaseAction:
    """Classe de base représentant une commande système autonome avec son script embarqué."""
    tag: str
    description: str
    script_code: str = ""
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

    def build_args(self, args: str = "") -> List[str]:
        """Découpe les arguments passés pour le script bash. Peut être surchargé."""
        args_clean = (args or "").strip()
        if not args_clean:
            return []
        try:
            return shlex.split(args_clean)
        except Exception:
            return args_clean.split()

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        """Exécute le script bash embarqué de manière asynchrone non-bloquante."""
        cmd_args = self.build_args(args)
        cmd_exec = ["bash", "-c", self.script_code, "_"] + cmd_args

        if dry_run:
            print(f"🔍 [ACTIONS] [DRY RUN] Tag [{self.tag}] avec args: {cmd_args}")
            return True

        if not self.script_code.strip():
            print(f"⚠️ [ACTIONS] Aucun script défini pour [{self.tag}]")
            return False

        try:
            print(f"🚀 [ACTIONS] Exécution [{self.tag}] (args: {cmd_args})")
            subprocess.Popen(
                cmd_exec,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
        except Exception as e:
            print(f"⚠️ [ACTIONS] Erreur lors de l'exécution de [{self.tag}] : {e}")
            return False

    def execute_sync(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        """Exécute le script bash de manière synchrone (utile pour les tests et le diagnostic)."""
        cmd_args = self.build_args(args)
        cmd_exec = ["bash", "-c", self.script_code, "_"] + cmd_args

        try:
            res = subprocess.run(cmd_exec, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)


# Alias de compatibilité
CommandDefinition = BaseAction


if __name__ == "__main__":
    print("🧪 [DEBUG] Test de BaseAction avec script embarqué")
    sample_action = BaseAction(
        tag="ECHO_TEST",
        description="Action de test echo",
        script_code='echo "Hello from action: $1, $2"',
        has_args=True
    )
    print(f"Action : [{sample_action.tag}]")
    code, out, err = sample_action.execute_sync("world 42")
    print(f"Code : {code} | Sortie : {out.strip()}")
