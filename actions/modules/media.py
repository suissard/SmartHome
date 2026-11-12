"""
Module d'action pour le contrôle multimédia (Play/Pause, Next, Previous).
Contient les métadonnées et le script d'exécution embarqué (Linux et Windows).
"""

from typing import List, Tuple
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

# Recherche via qdbus6 si busctl n'a rien trouvé
if [ "$called" -eq 0 ] && command -v qdbus6 >/dev/null 2>&1; then
    players=$(qdbus6 2>/dev/null | grep -i "org.mpris.MediaPlayer2")
    for p in $players; do
        if qdbus6 "$p" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player."$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche via qdbus standard
if [ "$called" -eq 0 ] && command -v qdbus >/dev/null 2>&1; then
    players=$(qdbus 2>/dev/null | grep -i "org.mpris.MediaPlayer2")
    for p in $players; do
        if qdbus "$p" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player."$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

# Recherche via dbus-send si rien d'autre n'a fonctionné
if [ "$called" -eq 0 ] && command -v dbus-send >/dev/null 2>&1; then
    for p in $(dbus-send --session --dest=org.freedesktop.DBus --type=method_call --print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames 2>/dev/null | grep -o 'org\.mpris\.MediaPlayer2\.[^"]*'); do
        if dbus-send --type=method_call --dest="$p" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player."$MPRIS_METHOD" >/dev/null 2>&1; then
            called=1
        fi
    done
fi

if [ "$called" -eq 1 ]; then
    exit 0
fi

echo "Erreur : Aucun lecteur multimédia actif trouvé." >&2
exit 1
"""


def _windows_media(cmd: str) -> Tuple[int, str, str]:
    import ctypes
    user32 = ctypes.windll.user32
    VK_MEDIA_NEXT = 0xB0
    VK_MEDIA_PREV = 0xB1
    VK_MEDIA_STOP = 0xB2
    VK_MEDIA_PLAY_PAUSE = 0xB3

    def press(vk: int):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)

    try:
        cmd_lower = (cmd or "play-pause").strip().lower()
        if cmd_lower in ("play-pause", "play_pause", "toggle", "play", "pause"):
            press(VK_MEDIA_PLAY_PAUSE)
            print("✅ [ACTIONS] [Windows] Média Play/Pause envoyé")
            return 0, "Média play/pause", ""
        elif cmd_lower in ("next",):
            press(VK_MEDIA_NEXT)
            print("✅ [ACTIONS] [Windows] Média Piste suivante envoyé")
            return 0, "Piste suivante", ""
        elif cmd_lower in ("previous", "prev"):
            press(VK_MEDIA_PREV)
            print("✅ [ACTIONS] [Windows] Média Piste précédente envoyé")
            return 0, "Piste précédente", ""
        elif cmd_lower in ("stop",):
            press(VK_MEDIA_STOP)
            print("✅ [ACTIONS] [Windows] Média Stop envoyé")
            return 0, "Média arrêté", ""
        else:
            return 1, "", f"Commande média inconnue : '{cmd}'"
    except Exception as e:
        print(f"❌ [ACTIONS] [Windows] Exception média : {e}")
        return -1, "", str(e)


class MediaPlayPauseAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PLAY_PAUSE",
            done_message="Média en pause." if False else "C'est fait.",
            description="Mettre en pause ou relancer la lecture multimédia (musique, vidéo).",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Mets la musique en pause.",
            example_response="[MEDIA_PLAY_PAUSE] Musique mise en pause."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["play-pause"]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return _windows_media("play-pause")

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


class MediaNextAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_NEXT",
            done_message="Piste suivante.",
            description="Passer à la piste / musique suivante.",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Passe à la chanson suivante.",
            example_response="[MEDIA_NEXT] Piste suivante."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["next"]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return _windows_media("next")

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


class MediaPrevAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="MEDIA_PREV",
            done_message="Piste précédente.",
            description="Revenir à la piste / musique précédente.",
            script_code=_MEDIA_SCRIPT,
            has_args=False,
            example_prompt="Remets la musique précédente.",
            example_response="[MEDIA_PREV] Piste précédente."
        )

    def build_args(self, args: str = "") -> List[str]:
        return ["previous"]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return _windows_media("previous")

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [MediaPlayPauseAction(), MediaNextAction(), MediaPrevAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/media.py")
    for act in ACTIONS:
        code, out, err = act.execute_sync()
        print(f"Action [{act.tag}] -> code: {code}")
