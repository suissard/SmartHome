"""
Module d'action pour la mise en veille / extinction des écrans.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class ScreenOffAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SCREEN_OFF",
            description="Mettre en veille / éteindre les écrans.",
            script_name="screen_off.sh",
            has_args=False,
            example_prompt="Éteins les écrans.",
            example_response="[SCREEN_OFF] Écrans éteints."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir))]


ACTIONS = [ScreenOffAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/screen_off.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts))
