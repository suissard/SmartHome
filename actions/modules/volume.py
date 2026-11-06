"""
Module d'action pour la gestion du volume audio (Volume, Mute, Unmute).
Contient les métadonnées et le script d'exécution embarqué (Linux et Windows).
"""

import sys
from typing import List, Tuple
from actions.base import BaseAction, percent_choices

_VOLUME_SCRIPT = r"""
TARGET="${1:-toggle}"

# Support PipeWire (wpctl) ou PulseAudio / PipeWire-Pulse (pactl)
if command -v pactl >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            pactl set-sink-mute @DEFAULT_SINK@ 1
            ;;
        unmute)
            pactl set-sink-mute @DEFAULT_SINK@ 0
            ;;
        toggle)
            pactl set-sink-mute @DEFAULT_SINK@ toggle
            ;;
        up|+*)
            pactl set-sink-mute @DEFAULT_SINK@ 0
            pactl set-sink-volume @DEFAULT_SINK@ +5%
            ;;
        down|-*)
            pactl set-sink-volume @DEFAULT_SINK@ -5%
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    pactl set-sink-mute @DEFAULT_SINK@ 0
                fi
                pactl set-sink-volume @DEFAULT_SINK@ "${val}%"
            fi
            ;;
    esac
elif command -v wpctl >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 1
            ;;
        unmute)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
            ;;
        toggle)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
            ;;
        up|+*)
            wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
            wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+
            ;;
        down|-*)
            wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    wpctl set-mute @DEFAULT_AUDIO_SINK@ 0
                fi
                wpctl set-volume @DEFAULT_AUDIO_SINK@ "${val}%"
            fi
            ;;
    esac
elif command -v amixer >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            amixer -q set Master mute
            ;;
        unmute)
            amixer -q set Master unmute
            ;;
        toggle)
            amixer -q set Master toggle
            ;;
        up|+*)
            amixer -q set Master unmute
            amixer -q set Master 5%+
            ;;
        down|-*)
            amixer -q set Master 5%-
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    amixer -q set Master unmute
                fi
                amixer -q set Master "${val}%"
            fi
            ;;
    esac
else
    echo "Erreur : Aucun contrôleur audio trouvé (pactl, wpctl, amixer)." >&2
    exit 1
fi
"""


def _windows_volume(target: str) -> Tuple[int, str, str]:
    target = (target or "").strip().lower()
    import ctypes
    user32 = ctypes.windll.user32
    VK_MUTE = 0xAD
    VK_DOWN = 0xAE
    VK_UP = 0xAF

    def press(vk: int, times: int = 1):
        for _ in range(times):
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, 2, 0)

    try:
        if target in ("mute", "unmute", "toggle"):
            press(VK_MUTE)
            msg = "Son coupé" if target == "mute" else ("Son réactivé" if target == "unmute" else "Son basculé")
            print(f"✅ [ACTIONS] [Windows] {msg}")
            return 0, msg, ""
        elif target in ("up", "+", "plus", "monte", "monter", "augmente", "augmenter"):
            press(VK_UP, 4)
            print("✅ [ACTIONS] [Windows] Volume augmenté")
            return 0, "Volume augmenté", ""
        elif target in ("down", "-", "moins", "baisse", "baisser", "diminue", "diminuer"):
            press(VK_DOWN, 4)
            print("✅ [ACTIONS] [Windows] Volume diminué")
            return 0, "Volume diminué", ""
        elif target.rstrip("%").isdigit():
            val = max(0, min(100, int(target.rstrip("%"))))
            press(VK_DOWN, 50)
            press(VK_UP, val // 2)
            msg = f"Volume réglé à {val}%"
            print(f"✅ [ACTIONS] [Windows] {msg}")
            return 0, msg, ""
        else:
            return 1, "", f"Commande de volume inconnue : '{target}'"
    except Exception as e:
        print(f"❌ [ACTIONS] [Windows] Exception volume : {e}")
        return -1, "", str(e)


class VolumeAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="VOLUME",
            done_message="Volume ${ARGS}.",
            description="Régler le volume sonore : monter ou baisser le son, ou fixer un niveau de 0 à 100.",
            script_code=_VOLUME_SCRIPT,
            has_args=True,
            args_hint="<0-100|up|down>",
            example_prompt="Mets le volume à 40%.",
            example_response="[VOLUME 40] Volume réglé à 40%."
        )

    def decision_choices(self):
        return percent_choices(up="plus fort", down="moins fort")

    def build_args(self, args: str = "") -> List[str]:
        target = (args or "").strip() or "toggle"
        return [target]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        cmd_args = self.build_args(args)
        target = cmd_args[0] if cmd_args else "toggle"
        return _windows_volume(target)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print(f"🔍 [ACTIONS] [DRY RUN] [Windows] Volume {args}")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


class MuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MUTE",
            done_message="Son coupé.",
            description="Couper le son de l'ordinateur (muet).",
            script_code=_VOLUME_SCRIPT,
            has_args=False,
            example_prompt="Coupe le son.",
            example_response="[MUTE] Son coupé."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["mute"]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return _windows_volume("mute")

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print("🔍 [ACTIONS] [DRY RUN] [Windows] Mute")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


class UnmuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="UNMUTE",
            done_message="Son réactivé.",
            description="Réactiver le son de l'ordinateur.",
            script_code=_VOLUME_SCRIPT,
            has_args=False,
            example_prompt="Remets le son.",
            example_response="[UNMUTE] Son réactivé."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["unmute"]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return _windows_volume("unmute")

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print("🔍 [ACTIONS] [DRY RUN] [Windows] Unmute")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [VolumeAction(), MuteAction(), UnmuteAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/volume.py")
    for act in ACTIONS:
        code, out, err = act.execute_sync()
        print(f"Action [{act.tag}] -> code: {code}, out: {out}")
