"""
Module d'action pour changer la sortie audio (enceintes, casque, HDMI...).
Fonctionne avec PipeWire et PulseAudio via pactl.
"""

from typing import List
from actions.base import BaseAction

_AUDIO_OUTPUT_SCRIPT = r"""
TARGET="${1:-next}"

if ! command -v pactl >/dev/null 2>&1; then
    echo "Erreur : pactl introuvable." >&2
    exit 1
fi

# Sorties disponibles : "nom|description"
mapfile -t SINKS < <(pactl -f json list sinks 2>/dev/null | python3 -c '
import json, sys
for s in json.load(sys.stdin):
    print(s["name"] + "|" + s.get("description", s["name"]))
')
[ "${#SINKS[@]}" -eq 0 ] && { echo "Aucune sortie audio trouvée." >&2; exit 1; }

DEFAULT=$(pactl get-default-sink)

if [ "$TARGET" = "list" ]; then
    for s in "${SINKS[@]}"; do
        echo "${s#*|}$([ "${s%%|*}" = "$DEFAULT" ] && echo ' (active)')"
    done
    exit 0
fi

CHOSEN=""
if [ "$TARGET" = "next" ]; then
    for i in "${!SINKS[@]}"; do
        if [ "${SINKS[$i]%%|*}" = "$DEFAULT" ]; then
            CHOSEN="${SINKS[$(( (i + 1) % ${#SINKS[@]} ))]}"
            break
        fi
    done
    [ -z "$CHOSEN" ] && CHOSEN="${SINKS[0]}"
else
    LOWER=$(echo "$TARGET" | tr '[:upper:]' '[:lower:]')
    # Synonymes courants
    case "$LOWER" in
        casque|écouteurs|ecouteurs) LOWER="head" ;;
        enceintes|enceinte|haut-parleurs) LOWER="speaker" ;;
        tv|télé|tele|écran|ecran) LOWER="hdmi" ;;
    esac
    for s in "${SINKS[@]}"; do
        if echo "$s" | tr '[:upper:]' '[:lower:]' | grep -q -- "$LOWER"; then
            CHOSEN="$s"
            break
        fi
    done
    [ -z "$CHOSEN" ] && { echo "Aucune sortie ne correspond à '$TARGET'." >&2; exit 1; }
fi

NAME="${CHOSEN%%|*}"
pactl set-default-sink "$NAME" || exit 1
# Déplace aussi les flux déjà en lecture
for id in $(pactl list short sink-inputs | cut -f1); do
    pactl move-sink-input "$id" "$NAME" 2>/dev/null
done
echo "Sortie audio : ${CHOSEN#*|}"
"""


class AudioOutputAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="AUDIO_OUTPUT",
            description="Changer la sortie audio (next, list, ou un mot du nom : casque, enceintes, hdmi, bluetooth).",
            script_code=_AUDIO_OUTPUT_SCRIPT,
            has_args=True,
            args_hint="<next|list|casque|enceintes|hdmi|nom>",
            example_prompt="Passe le son sur le casque.",
            example_response="[AUDIO_OUTPUT casque] Son basculé sur le casque."
        )

    def decision_choices(self):
        return {"next": "sortie suivante", "casque": "casque", "enceintes": "enceintes", "hdmi": "HDMI", "bluetooth": "Bluetooth"}

    def build_args(self, args: str = "") -> List[str]:
        target = " ".join((args or "").split())
        return [target or "next"]


ACTIONS = [AudioOutputAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/audio_output.py")
    code, out, err = ACTIONS[0].execute_sync("list")
    print(f"Code : {code}\n{out}{err}")
