"""
Module d'action pour la luminosité de l'écran (valeur en %, up, down).
Contient les métadonnées et le script bash embarqué.
"""

from typing import List
from actions.base import BaseAction, percent_choices

_BRIGHTNESS_SCRIPT = r"""
TARGET="${1:-}"
STEP=10

if [ -z "$TARGET" ]; then
    echo "Usage : brightness.sh <0-100|up|down>" >&2
    exit 1
fi

# 1. brightnessctl
if command -v brightnessctl >/dev/null 2>&1; then
    case "$TARGET" in
        up)   brightnessctl -q set "${STEP}%+" ;;
        down) brightnessctl -q set "${STEP}%-" ;;
        *)    brightnessctl -q set "${TARGET}%" ;;
    esac
    exit $?
fi

# 2. KDE Plasma (PowerDevil via D-Bus)
QDBUS=$(command -v qdbus6 || command -v qdbus || true)
if [ -n "$QDBUS" ]; then
    SVC=org.kde.Solid.PowerManagement
    OBJ=/org/kde/Solid/PowerManagement/Actions/BrightnessControl
    MAX=$("$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightnessMax 2>/dev/null)
    CUR=$("$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightness 2>/dev/null)
    if [[ "$MAX" =~ ^[0-9]+$ && "$CUR" =~ ^[0-9]+$ ]]; then
        case "$TARGET" in
            up)   NEW=$(( CUR + MAX * STEP / 100 )) ;;
            down) NEW=$(( CUR - MAX * STEP / 100 )) ;;
            *)    NEW=$(( MAX * TARGET / 100 )) ;;
        esac
        [ "$NEW" -lt 0 ] && NEW=0
        [ "$NEW" -gt "$MAX" ] && NEW=$MAX
        "$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness "$NEW" >/dev/null 2>&1
        echo "Luminosité réglée à $(( NEW * 100 / MAX ))%"
        exit 0
    fi
fi

echo "Erreur : aucun contrôle de luminosité disponible (installer brightnessctl)." >&2
exit 1
"""


class BrightnessAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="BRIGHTNESS",
            done_message="Luminosité ${ARGS}.",
            description="Régler la luminosité de l'écran : plus ou moins lumineux, ou fixer un pourcentage de 0 à 100.",
            script_code=_BRIGHTNESS_SCRIPT,
            has_args=True,
            args_hint="<0-100|up|down>",
            example_prompt="Mets la luminosité à 40 pour cent.",
            example_response="[BRIGHTNESS 40] Luminosité à 40 pour cent."
        )

    def decision_choices(self):
        return percent_choices(up="plus lumineux", down="moins lumineux")

    def build_args(self, args: str = "") -> List[str]:
        value = (args or "").strip().lower().rstrip("%").strip()
        if value in ("up", "+", "plus", "augmente"):
            return ["up"]
        if value in ("down", "-", "moins", "baisse"):
            return ["down"]
        if value.isdigit():
            return [str(min(100, int(value)))]
        print(f"⛔ [ACTIONS] Argument invalide pour [BRIGHTNESS] : '{args}'")
        return []


ACTIONS = [BrightnessAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/brightness.py")
    print(f"Arguments '40%' -> {ACTIONS[0].build_args('40%')} | 'up' -> {ACTIONS[0].build_args('up')}")
