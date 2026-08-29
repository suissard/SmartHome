"""
Module d'action pour la gestion du volume audio (Volume, Mute, Unmute).
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class VolumeAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="VOLUME",
            description="Régler le volume sonore (ex: 0 à 100, up, down).",
            script_name="volume.sh",
            has_args=True,
            args_hint="<0-100|up|down>",
            example_prompt="Mets le volume à 40%.",
            example_response="[VOLUME 40] Volume réglé à 40%."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        target = (args or "").strip() or "toggle"
        return [str(self.get_script_path(scripts_dir)), target]


class MuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MUTE",
            description="Couper le son de l'ordinateur (muet).",
            script_name="volume.sh",
            has_args=False,
            example_prompt="Coupe le son.",
            example_response="[MUTE] Son coupé."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir)), "mute"]


class UnmuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="UNMUTE",
            description="Réactiver le son de l'ordinateur.",
            script_name="volume.sh",
            has_args=False,
            example_prompt="Remets le son.",
            example_response="[UNMUTE] Son réactivé."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir)), "unmute"]


# Export des instances d'actions définies dans ce module
ACTIONS = [VolumeAction(), MuteAction(), UnmuteAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/volume.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    for act in ACTIONS:
        print(f"Action: {act.tag} -> Commande générée: {act.build_command(scripts, '50')}")
