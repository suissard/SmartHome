"""
Module d'action pour le redémarrage du système.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class RebootAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="REBOOT",
            description="Redémarrer l'ordinateur.",
            script_name="reboot.sh",
            has_args=False,
            example_prompt="Redémarre le système.",
            example_response="[REBOOT] Redémarrage de la machine en cours."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir))]


ACTIONS = [RebootAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/reboot.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts))
