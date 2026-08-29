"""
Module d'action pour l'affichage de notifications sur le bureau.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class NotifyAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="NOTIFY",
            description="Afficher une notification sur le bureau.",
            script_name="notify.sh",
            has_args=True,
            args_hint="<message>",
            example_prompt="Affiche un rappel pour sortir le chien.",
            example_response="[NOTIFY Sortir le chien] Notification affichée."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        cmd_exec = [str(self.get_script_path(scripts_dir))]
        msg = (args or "").strip()
        if msg:
            cmd_exec.append(msg)
        return cmd_exec


ACTIONS = [NotifyAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/notify.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts, "Rappel important"))
