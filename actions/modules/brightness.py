"""
Module d'action pour la luminosité de l'écran (valeur en %, up, down).
Contient les métadonnées et le script d'exécution embarqué (Linux et Windows).
"""

import subprocess
import sys
from typing import List, Tuple
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
        if value in ("up", "+", "plus", "augmente", "augmenter", "monter"):
            return ["up"]
        if value in ("down", "-", "moins", "baisse", "baisser", "diminue", "diminuer"):
            return ["down"]
        if value.isdigit():
            return [str(min(100, int(value)))]
        return []

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        cmd_args = self.build_args(args)
        if not cmd_args:
            raw = (args or "").strip().lower()
            if any(w in raw for w in ("baisse", "diminue", "moins", "down")):
                target = "down"
            elif any(w in raw for w in ("augmente", "plus", "monte", "up")):
                target = "up"
            else:
                return 1, "", f"Argument invalide pour BRIGHTNESS : '{args}'"
        else:
            target = cmd_args[0]

        # 1. Lecture de la valeur actuelle
        current = 100
        try:
            res_cur = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness"],
                capture_output=True, text=True, timeout=timeout
            )
            val_str = res_cur.stdout.strip().split()
            if val_str and val_str[-1].isdigit():
                current = int(val_str[-1])
        except Exception:
            pass

        if target == "up":
            new_val = min(100, current + 10)
        elif target == "down":
            new_val = max(0, current - 10)
        else:
            try:
                new_val = max(0, min(100, int(target)))
            except ValueError:
                return 1, "", f"Valeur invalide pour BRIGHTNESS : '{target}'"

        try:
            ps_set = f"(Get-WmiObject -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1, {new_val})"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_set],
                capture_output=True, text=True, timeout=timeout
            )
            if res.returncode == 0:
                msg = f"Luminosité réglée à {new_val}%"
                print(f"✅ [ACTIONS] [Windows] {msg}")
                return 0, msg, ""
            err = (res.stderr or res.stdout).strip()
            print(f"❌ [ACTIONS] [Windows] Erreur réglage luminosité : {err}")
            return res.returncode, "", err
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Exception luminosité : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [BrightnessAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/brightness.py")
    print(f"Arguments '40%' -> {ACTIONS[0].build_args('40%')} | 'up' -> {ACTIONS[0].build_args('up')}")
    if sys.platform == "win32":
        print("Test Windows execute_sync_windows('down'):")
        c, o, e = ACTIONS[0].execute_sync_windows("down")
        print(f"Result: code={c}, out={o}, err={e}")
