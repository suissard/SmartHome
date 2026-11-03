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

# Nouvelle valeur d'après la valeur actuelle ($1) et le maximum ($2)
next_value() {
    local NEW
    case "$TARGET" in
        up)   NEW=$(( $1 + $2 * STEP / 100 )) ;;
        down) NEW=$(( $1 - $2 * STEP / 100 )) ;;
        *)    NEW=$(( $2 * TARGET / 100 )) ;;
    esac
    [ "$NEW" -lt 0 ] && NEW=0
    [ "$NEW" -gt "$2" ] && NEW=$2
    echo "$NEW"
}

QDBUS=$(command -v qdbus6 || command -v qdbus || true)

# 1. KDE Plasma 6 : tous les écrans, y compris les moniteurs externes (DDC/CI ou atténuation logicielle)
if [ -n "$QDBUS" ]; then
    SVC=org.kde.ScreenBrightness
    DONE=""
    for DISPLAY_NAME in $("$QDBUS" $SVC /org/kde/ScreenBrightness $SVC.DisplaysDBusNames 2>/dev/null); do
        OBJ=/org/kde/ScreenBrightness/$DISPLAY_NAME
        MAX=$("$QDBUS" $SVC "$OBJ" $SVC.Display.MaxBrightness 2>/dev/null)
        CUR=$("$QDBUS" $SVC "$OBJ" $SVC.Display.Brightness 2>/dev/null)
        if [[ "$MAX" =~ ^[0-9]+$ && "$CUR" =~ ^[0-9]+$ && "$MAX" -gt 0 ]]; then
            NEW=$(next_value "$CUR" "$MAX")
            "$QDBUS" $SVC "$OBJ" $SVC.Display.SetBrightness "$NEW" 0 >/dev/null 2>&1 && DONE=$(( NEW * 100 / MAX ))
        fi
    done
    if [ -n "$DONE" ]; then
        echo "Luminosité réglée à ${DONE}%"
        exit 0
    fi
fi

# 2. brightnessctl, seulement sur un rétroéclairage : sans --class, il prendrait une LED (réseau, clavier) sur un PC fixe
if command -v brightnessctl >/dev/null 2>&1 && [ -n "$(ls -A /sys/class/backlight 2>/dev/null)" ]; then
    case "$TARGET" in
        up)   brightnessctl -q --class=backlight set "${STEP}%+" ;;
        down) brightnessctl -q --class=backlight set "${STEP}%-" ;;
        *)    brightnessctl -q --class=backlight set "${TARGET}%" ;;
    esac
    exit $?
fi

# 3. KDE Plasma 5 (PowerDevil via D-Bus)
if [ -n "$QDBUS" ]; then
    SVC=org.kde.Solid.PowerManagement
    OBJ=/org/kde/Solid/PowerManagement/Actions/BrightnessControl
    MAX=$("$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightnessMax 2>/dev/null)
    CUR=$("$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightness 2>/dev/null)
    if [[ "$MAX" =~ ^[0-9]+$ && "$CUR" =~ ^[0-9]+$ && "$MAX" -gt 0 ]]; then
        NEW=$(next_value "$CUR" "$MAX")
        "$QDBUS" $SVC $OBJ org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness "$NEW" >/dev/null 2>&1
        echo "Luminosité réglée à $(( NEW * 100 / MAX ))%"
        exit 0
    fi
fi

echo "Cet écran ne permet pas de régler la luminosité depuis l'ordinateur : à régler sur le moniteur. Inutile de changer de droits." >&2
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
