"""
Module d'action pour la capture d'écran (enregistrée dans ACTIONS_SCREENSHOT_DIR).
Contient les métadonnées et le script bash embarqué.
"""

import os
from typing import List
from actions.base import BaseAction
from core.config import ACTIONS_SCREENSHOT_DIR

_SCREENSHOT_SCRIPT = r"""
DIR="${1:-$HOME/Pictures}"
mkdir -p "$DIR" || exit 1
FILE="$DIR/capture_$(date +%Y%m%d_%H%M%S).png"

if command -v spectacle >/dev/null 2>&1; then
    spectacle -b -n -f -o "$FILE" >/dev/null 2>&1
elif command -v grim >/dev/null 2>&1; then
    grim "$FILE"
elif command -v gnome-screenshot >/dev/null 2>&1; then
    gnome-screenshot -f "$FILE"
elif command -v scrot >/dev/null 2>&1; then
    scrot "$FILE"
else
    echo "Erreur : aucun outil de capture (spectacle, grim, gnome-screenshot, scrot)." >&2
    exit 1
fi

if [ -s "$FILE" ]; then
    echo "Capture enregistrée : $FILE"
else
    echo "Erreur : la capture a échoué." >&2
    exit 1
fi
"""


class ScreenshotAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SCREENSHOT",
            description="Prendre une capture d'écran du bureau et l'enregistrer dans le dossier d'images.",
            script_code=_SCREENSHOT_SCRIPT,
            example_prompt="Fais une capture d'écran.",
            example_response="[SCREENSHOT] Capture d'écran faite."
        )

    def build_args(self, args: str = "") -> List[str]:
        return [os.path.expanduser(ACTIONS_SCREENSHOT_DIR)]


ACTIONS = [ScreenshotAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/screenshot.py")
    print(f"Dossier de destination : {ACTIONS[0].build_args()[0]}")
