"""
Module d'action pour la gestion du volume audio (Volume, Mute, Unmute).
Contient les métadonnées et le script bash embarqué.
"""

from typing import List
from actions.base import BaseAction

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
            # Démute automatiquement lors de l'augmentation du volume
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
                frac=$(awk "BEGIN {print $val/100}")
                wpctl set-volume @DEFAULT_AUDIO_SINK@ "$frac"
            fi
            ;;
    esac
elif command -v amixer >/dev/null 2>&1; then
    case "$TARGET" in
        mute)
            amixer set Master mute
            ;;
        unmute)
            amixer set Master unmute
            ;;
        toggle)
            amixer set Master toggle
            ;;
        up|+*)
            amixer set Master unmute
            amixer set Master 5%+
            ;;
        down|-*)
            amixer set Master 5%-
            ;;
        *)
            val="${TARGET%%%}"
            if [[ "$val" =~ ^[0-9]+$ ]]; then
                if [ "$val" -gt 0 ]; then
                    amixer set Master unmute
                fi
                amixer set Master "${val}%"
            fi
            ;;
    esac
else
    echo "Erreur : Aucun contrôleur audio trouvé (pactl, wpctl, amixer)." >&2
    exit 1
fi
"""


class VolumeAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="VOLUME",
            description="Régler le volume sonore (ex: 0 à 100, up, down).",
            script_code=_VOLUME_SCRIPT,
            has_args=True,
            args_hint="<0-100|up|down>",
            example_prompt="Mets le volume à 40%.",
            example_response="[VOLUME 40] Volume réglé à 40%."
        )

    def build_args(self, args: str = "") -> List[str]:
        target = (args or "").strip() or "toggle"
        return [target]


class MuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MUTE",
            description="Couper le son de l'ordinateur (muet).",
            script_code=_VOLUME_SCRIPT,
            has_args=False,
            example_prompt="Coupe le son.",
            example_response="[MUTE] Son coupé."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["mute"]


class UnmuteAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="UNMUTE",
            description="Réactiver le son de l'ordinateur.",
            script_code=_VOLUME_SCRIPT,
            has_args=False,
            example_prompt="Remets le son.",
            example_response="[UNMUTE] Son réactivé."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["unmute"]


ACTIONS = [VolumeAction(), MuteAction(), UnmuteAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/volume.py")
    for act in ACTIONS:
        code, out, err = act.execute_sync()
        print(f"Action [{act.tag}] -> code: {code}")
