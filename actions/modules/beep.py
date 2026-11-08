"""
Module d'action qui joue trois bips sonores courts et espacés sur les haut-parleurs du PC.
Le signal (WAV 44,1 kHz mono) est généré par python3 (bibliothèque standard), puis lu par paplay, pw-play ou aplay.
"""

from actions.base import BaseAction

_SCRIPT = r"""
if ! command -v python3 >/dev/null 2>&1; then
    echo "Erreur : python3 introuvable (nécessaire pour générer les bips)." >&2
    exit 1
fi

PLAYER=""
for candidate in paplay pw-play aplay; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PLAYER="$candidate"
        break
    fi
done
if [ -z "$PLAYER" ]; then
    echo "Erreur : aucun lecteur audio trouvé (paplay, pw-play ou aplay)." >&2
    exit 1
fi

WAV="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/smarthome-beep-XXXXXX.wav")" || {
    echo "Erreur : impossible de créer le fichier audio temporaire." >&2
    exit 1
}
trap 'rm -f "$WAV"' EXIT

python3 - "$WAV" <<'PY' || { echo "Erreur : génération des bips impossible." >&2; exit 1; }
import math, struct, sys, wave

RATE = 44100
FREQ = 880.0      # Hz
BEEP = 0.15       # durée d'un bip (s)
GAP = 0.35        # silence entre deux bips (s)
COUNT = 3
FADE = 0.005      # fondu d'entrée/sortie anti-clic (s)
AMP = 0.5

frames = bytearray()
n_beep = int(RATE * BEEP)
n_fade = int(RATE * FADE)
silence = b"\x00\x00" * int(RATE * GAP)
for i in range(COUNT):
    for n in range(n_beep):
        env = min(1.0, n / n_fade, (n_beep - 1 - n) / n_fade)
        frames += struct.pack("<h", int(32767 * AMP * env * math.sin(2 * math.pi * FREQ * n / RATE)))
    frames += silence

with wave.open(sys.argv[1], "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(RATE)
    wav.writeframes(bytes(frames))
PY

case "$PLAYER" in
    aplay) aplay -q "$WAV" || { echo "Erreur : lecture audio impossible (aplay)." >&2; exit 1; } ;;
    *) "$PLAYER" "$WAV" || { echo "Erreur : lecture audio impossible ($PLAYER)." >&2; exit 1; } ;;
esac
echo "Trois bips joués."
"""

_SCRIPT_WINDOWS = r"""
for ($i = 0; $i -lt 3; $i++) {
    [console]::Beep(880, 150)
    if ($i -lt 2) { Start-Sleep -Milliseconds 350 }
}
Write-Output "Trois bips joués."
"""


class BeepAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="BEEP",
            description=(
                "Jouer trois bips sonores courts et espacés sur les haut-parleurs de l'ordinateur, "
                "quand l'utilisateur demande des bips, un signal sonore ou de tester le son."
            ),
            script_code=_SCRIPT,
            script_code_windows=_SCRIPT_WINDOWS,
            has_args=False,
            example_prompt="Fais trois bips.",
            example_response="[BEEP] Voilà trois bips.",
            danger="safe",
            done_message="Voilà trois bips.",
        )


ACTIONS = [BeepAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/beep.py")
    action = ACTIONS[0]
    print(f"Action : [{action.tag}] (outil « {action.tool_name} ») chargée avec succès.")
    print(f"Arguments construits : {action.build_args('')}")
