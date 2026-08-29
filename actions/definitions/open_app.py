"""
Module d'action pour le lancement d'applications installées.
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class OpenAppAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="OPEN",
            description="Lancer une application installée (ex: firefox, spotify, code, calculatrice).",
            script_name="open_app.sh",
            has_args=True,
            args_hint="<application>",
            example_prompt="Ouvre Firefox.",
            example_response="[OPEN firefox] J'ouvre Firefox."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        cmd_exec = [str(self.get_script_path(scripts_dir))]
        app = (args or "").strip()
        if app:
            cmd_exec.append(app)
        return cmd_exec


ACTIONS = [OpenAppAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/open_app.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    print(ACTIONS[0].build_command(scripts, "calculatrice"))
