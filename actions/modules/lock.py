"""
Module d'action pour le verrouillage de session utilisateur.
Contient les métadonnées et le script de verrouillage (Linux et Windows).
"""

from typing import Tuple
from actions.base import BaseAction

_LOCK_SCRIPT = r"""
# 1. loginctl (standard systemd multi-environnements)
if command -v loginctl >/dev/null 2>&1; then
    loginctl lock-session && exit 0
fi

# 2. D-Bus freedesktop ScreenSaver
if command -v qdbus6 >/dev/null 2>&1; then
    qdbus6 org.freedesktop.ScreenSaver /ScreenSaver Lock 2>/dev/null && exit 0
elif command -v qdbus >/dev/null 2>&1; then
    qdbus org.freedesktop.ScreenSaver /ScreenSaver Lock 2>/dev/null && exit 0
elif command -v dbus-send >/dev/null 2>&1; then
    dbus-send --type=method_call --dest=org.freedesktop.ScreenSaver /ScreenSaver org.freedesktop.ScreenSaver.Lock 2>/dev/null && exit 0
fi

# 3. xdg-screensaver
if command -v xdg-screensaver >/dev/null 2>&1; then
    xdg-screensaver lock && exit 0
fi

# 4. GNOME screensaver
if command -v gnome-screensaver-command >/dev/null 2>&1; then
    gnome-screensaver-command -l && exit 0
fi

# 5. Hyprlock / Swaylock
if command -v hyprlock >/dev/null 2>&1; then
    nohup hyprlock >/dev/null 2>&1 &
    exit 0
elif command -v swaylock >/dev/null 2>&1; then
    nohup swaylock >/dev/null 2>&1 &
    exit 0
fi

echo "Erreur : Aucun gestionnaire de verrouillage détecté." >&2
exit 1
"""


class LockAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="LOCK",
            done_message="Je verrouille la session.",
            description="Verrouiller la session de l'utilisateur.",
            script_code=_LOCK_SCRIPT,
            has_args=False,
            example_prompt="Verrouille ma session.",
            example_response="[LOCK] Session verrouillée."
        )

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            import ctypes
            print("🚀 [ACTIONS] [Windows] Verrouillage de la session utilisateur...")
            ok = ctypes.windll.user32.LockWorkStation()
            if ok:
                print("✅ [ACTIONS] [Windows] Session verrouillée avec succès.")
                return 0, "Session verrouillée", ""
            return 1, "", "Échec du verrouillage de la session"
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Exception lock : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print("🔍 [ACTIONS] [DRY RUN] [Windows] Verrouillage simulé")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [LockAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/lock.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
