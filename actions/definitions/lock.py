"""
Module d'action pour le verrouillage de session utilisateur.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class LockAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="LOCK",
            description="Verrouiller la session de l'utilisateur.",
            script_name="lock.sh",
            has_args=False,
            example_prompt="Verrouille ma session.",
            example_response="[LOCK] Session verrouillée."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir))]


ACTIONS = [LockAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/lock.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts))
