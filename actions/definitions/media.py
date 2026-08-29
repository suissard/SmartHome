"""
Module d'action pour le contrôle multimédia (Play/Pause, Next, Previous).
"""

from pathlib import Path
from typing import List
from actions.base import BaseAction


class MediaPlayPauseAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PLAY_PAUSE",
            description="Mettre en pause ou relancer la lecture multimédia (musique/vidéo).",
            script_name="media.sh",
            has_args=False,
            example_prompt="Mets la musique en pause.",
            example_response="[MEDIA_PLAY_PAUSE] Pause musicale."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir)), "play-pause"]


class MediaNextAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_NEXT",
            description="Passer à la piste / musique suivante.",
            script_name="media.sh",
            has_args=False,
            example_prompt="Passe à la chanson suivante.",
            example_response="[MEDIA_NEXT] Piste suivante."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir)), "next"]


class MediaPrevAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PREV",
            description="Revenir à la piste / musique précédente.",
            script_name="media.sh",
            has_args=False,
            example_prompt="Remets la musique précédente.",
            example_response="[MEDIA_PREV] Piste précédente."
        )

    def build_command(self, scripts_dir: Path, args: str = "") -> List[str]:
        return [str(self.get_script_path(scripts_dir)), "previous"]


# Export des instances d'actions définies dans ce module
ACTIONS = [MediaPlayPauseAction(), MediaNextAction(), MediaPrevAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/media.py")
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    for act in ACTIONS:
        print(f"Action: {act.tag} -> Commande générée: {act.build_command(scripts)}")
