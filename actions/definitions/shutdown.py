"""
Module d'action pour l'extinction complète de l'ordinateur.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class ShutdownAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SHUTDOWN",
            description="Éteindre complètement l'ordinateur.",
            script_name="shutdown.sh",
            has_args=False,
            example_prompt="Éteins l'ordinateur s'il te plaît.",
            example_response="[SHUTDOWN] J'éteins l'ordinateur. Bonne nuit !"
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir))]


ACTIONS = [ShutdownAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/shutdown.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts))
