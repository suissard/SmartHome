"""
Module d'action pour la mise en veille / extinction des écrans.
Contient les métadonnées et le script d'exécution (Linux et Windows).
"""

import sys
from typing import Tuple
from actions.base import BaseAction

_SCREEN_OFF_SCRIPT = r"""
# 1. KDE Plasma (Wayland ou X11) via kscreen-doctor
if command -v kscreen-doctor >/dev/null 2>&1; then
    kscreen-doctor --dpms off && exit 0
fi

# 2. KDE via raccourci PowerDevil D-Bus
if command -v qdbus6 >/dev/null 2>&1; then
    qdbus6 org.kde.kglobalaccel /component/org_kde_powerdevil invokeShortcut "Turn Off Screen" 2>/dev/null && exit 0
elif command -v qdbus >/dev/null 2>&1; then
    qdbus org.kde.kglobalaccel /component/org_kde_powerdevil invokeShortcut "Turn Off Screen" 2>/dev/null && exit 0
fi

# 3. Hyprland
if command -v hyprctl >/dev/null 2>&1; then
    hyprctl dispatch dpms off && exit 0
fi

# 4. Sway
if command -v swaymsg >/dev/null 2>&1; then
    swaymsg "output * dpms off" && exit 0
fi

# 5. Generic Wayland wlroots (wlopm)
if command -v wlopm >/dev/null 2>&1; then
    wlopm --off '*' && exit 0
fi

# 6. X11 DPMS (uniquement si sous X11)
if [ "$XDG_SESSION_TYPE" != "wayland" ] && command -v xset >/dev/null 2>&1; then
    xset dpms force off && exit 0
fi

echo "Erreur : Aucune commande de gestion d'affichage compatible détectée." >&2
exit 1
"""


class ScreenOffAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SCREEN_OFF",
            done_message="Écran éteint.",
            description="Éteindre l'écran / mettre les moniteurs en veille.",
            script_code=_SCREEN_OFF_SCRIPT,
            has_args=False,
            example_prompt="Éteins l'écran.",
            example_response="[SCREEN_OFF] Écran éteint."
        )

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            import ctypes
            print("🚀 [ACTIONS] [Windows] Extinction de l'écran...")
            # HWND_BROADCAST = 0xFFFF, WM_SYSCOMMAND = 0x0112, SC_MONITORPOWER = 0xF170, 2 = Monitor OFF
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
            print("✅ [ACTIONS] [Windows] Écran éteint.")
            return 0, "Écran éteint", ""
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Exception screen_off : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [ScreenOffAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/screen_off.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
