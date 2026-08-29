"""
Module d'action pour le contrôle multimédia (Play/Pause, Next, Previous).
Contient les métadonnées et le script bash MPRIS2 / playerctl embarqué.
"""

from typing import List
from actions.base import BaseAction

_MEDIA_SCRIPT = r"""
CMD="${1:-play-pause}"

case "$CMD" in
    play-pause|play_pause|toggle)
        PLAYERCTL_CMD="play-pause"
        MPRIS_METHOD="PlayPause"
        ;;
    next)
        PLAYERCTL_CMD="next"
        MPRIS_METHOD="Next"
        ;;
    previous|prev)
        PLAYERCTL_CMD="previous"
        MPRIS_METHOD="Previous"
        ;;
    stop)
        PLAYERCTL_CMD="stop"
        MPRIS_METHOD="Stop"
        ;;
    play)
        PLAYERCTL_CMD="play"
        MPRIS_METHOD="Play"
        ;;
    pause)
        PLAYERCTL_CMD="pause"
        MPRIS_METHOD="Pause"
        ;;
    *)
        echo "Commande multimédia inconnue : $CMD" >&2
        exit 1
        ;;
esac

# 1. Utilisation de playerctl si présent
if command -v playerctl >/dev/null 2>&1; then
    if playerctl "$PLAYERCTL_CMD" 2>/dev/null; then
        exit 0
    fi
fi

# 2. Fallback D-Bus MPRIS2 direct
called=0

# Recherche des lecteurs actifs via busctl
if command -v busctl >/dev/null 2>&1; then
    players=$(busctl --user list 2>/dev/null | awk '/org\.mpris\.MediaPlayer2/{print $1}')
    for p in $players; do
        if busctl --user call "$p" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player "$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche des lecteurs actifs via dbus-send
if [ $called -eq 0 ] && command -v dbus-send >/dev/null 2>&1; then
    players=$(dbus-send --session --dest=org.freedesktop.DBus --type=method_call --print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>/dev/null | grep -o 'org\.mpris\.MediaPlayer2[^"]*')
    for p in $players; do
        if dbus-send --type=method_call --dest="$p" /org/mpris/MediaPlayer2 "org.mpris.MediaPlayer2.Player.$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche des lecteurs actifs via qdbus6 ou qdbus
if [ $called -eq 0 ]; then
    QDBUS_BIN=""
    if command -v qdbus6 >/dev/null 2>&1; then
        QDBUS_BIN="qdbus6"
    elif command -v qdbus >/dev/null 2>&1; then
        QDBUS_BIN="qdbus"
    fi

    if [ -n "$QDBUS_BIN" ]; then
        players=$($QDBUS_BIN 2>/dev/null | grep 'org\.mpris\.MediaPlayer2')
        for p in $players; do
            if $QDBUS_BIN "$p" /org/mpris/MediaPlayer2 "org.mpris.MediaPlayer2.Player.$MPRIS_METHOD" >/dev/null 2>&1; then
                called=1
            fi
        done
    fi
fi

if [ $called -eq 1 ]; then
    exit 0
fi

echo "Avertissement : Aucun lecteur multimédia actif trouvé (MPRIS / playerctl)." >&2
exit 0
"""


class MediaPlayPauseAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PLAY_PAUSE",
            description="Mettre en pause ou relancer la lecture multimédia (musique/vidéo).",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Mets la musique en pause.",
            example_response="[MEDIA_PLAY_PAUSE] Pause musicale."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["play-pause"]


class MediaNextAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_NEXT",
            description="Passer à la piste / musique suivante.",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Passe à la chanson suivante.",
            example_response="[MEDIA_NEXT] Piste suivante."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["next"]


class MediaPrevAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PREV",
            description="Revenir à la piste / musique précédente.",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Remets la musique précédente.",
            example_response="[MEDIA_PREV] Piste précédente."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["previous"]


ACTIONS = [MediaPlayPauseAction(), MediaNextAction(), MediaPrevAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/media.py")
    for act in ACTIONS:
        code, out, err = act.execute_sync()
        print(f"Action [{act.tag}] -> code: {code}")
