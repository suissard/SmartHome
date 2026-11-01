"""
Module d'action pour les minuteurs : notification + son à l'échéance.
S'appuie sur systemd-run --user (le minuteur survit à SmartHome).
"""

import re
from typing import List
from actions.base import BaseAction
from core.config import ACTIONS_TIMER_MAX_SECONDS

_TIMER_SCRIPT = r"""
SECONDS_TOTAL="${1:-}"
MESSAGE="${2:-Minuteur terminé}"

if ! [[ "$SECONDS_TOTAL" =~ ^[0-9]+$ ]] || [ "$SECONDS_TOTAL" -le 0 ]; then
    echo "Usage : timer.sh <secondes> [message]" >&2
    exit 1
fi

# Commande exécutée à l'échéance : notification + son d'alerte si disponible
NOTIFY='notify-send -u critical -i alarm-symbolic "SmartHome" "$0"; '
NOTIFY+='for f in /usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga /usr/share/sounds/freedesktop/stereo/complete.oga; do '
NOTIFY+='[ -f "$f" ] && command -v paplay >/dev/null 2>&1 && paplay "$f" && break; done'

if ! command -v systemd-run >/dev/null 2>&1; then
    echo "Erreur : systemd-run introuvable." >&2
    exit 1
fi

systemd-run --user --quiet --collect --on-active="${SECONDS_TOTAL}s" \
    --description="Minuteur SmartHome" bash -c "$NOTIFY" "$MESSAGE" || exit 1
echo "Minuteur de ${SECONDS_TOTAL} secondes lancé."
"""

_UNITS = {
    "h": 3600, "heure": 3600, "heures": 3600,
    "m": 60, "min": 60, "mn": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "seconde": 1, "secondes": 1,
}
_TOKEN = re.compile(r"(\d+)\s*([a-zéû]*)")
_SEPARATORS = re.compile(r"[\s,]*(?:et\b)?[\s,]*")


def parse_duration(text: str) -> tuple:
    """Extrait (secondes, message restant) d'un texte comme '1h30 pâtes' ou '10 minutes pizza'.

    Un nombre sans unité vaut des minutes ; '1h30' = 1 h 30 min.
    """
    text = (text or "").strip().lower()
    total, pos = 0, 0
    while True:
        m = _TOKEN.match(text, pos)
        if not m:
            break
        value, unit, end = int(m.group(1)), m.group(2), m.end()
        if unit not in _UNITS:
            # Le mot suivant n'est pas une unité (ex: "30 pâtes") : il appartient au message
            unit, end = "", m.end(1)
        if unit:
            factor = _UNITS[unit]
        else:
            # "1h30" : le nombre nu suit une heure et vaut des minutes ; sinon minutes
            factor = 60
        total += value * factor
        pos = _SEPARATORS.match(text, end).end()
        if not unit:
            break
    return total, text[pos:].strip(" ,:-")


class TimerAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="TIMER",
            done_message="Minuteur de ${ARGS} lancé.",
            description="Lancer un minuteur ou un rappel (notification et son à la fin). Durée puis message optionnel.",
            script_code=_TIMER_SCRIPT,
            has_args=True,
            args_hint="<durée ex: 10m, 1h30, 45s> [message]",
            example_prompt="Mets un minuteur de 10 minutes pour les pâtes.",
            example_response="[TIMER 10m pâtes] Minuteur de dix minutes lancé."
        )

    def decision_choices(self):
        # Le message reste celui par défaut : un modèle de décision ne rédige pas de texte
        minutes = (1, 2, 3, 5, 10, 15, 20, 30, 45)
        choices = {f"{m}m": f"{m} minute{'s' if m > 1 else ''}" for m in minutes}
        choices.update({"1h": "1 heure", "1h30": "1 heure 30", "2h": "2 heures"})
        return choices

    def build_args(self, args: str = "") -> List[str]:
        seconds, message = parse_duration(args)
        if seconds <= 0 or seconds > ACTIONS_TIMER_MAX_SECONDS:
            print(f"⛔ [ACTIONS] Durée invalide pour [TIMER] : '{args}' (max {ACTIONS_TIMER_MAX_SECONDS}s)")
            return []
        return [str(seconds), message or "Minuteur terminé"]


ACTIONS = [TimerAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/timer.py")
    for sample in ("10m", "1h30 pâtes", "45 s thé", "5", "2 heures et 15 minutes four"):
        print(f"{sample!r} -> {parse_duration(sample)}")
