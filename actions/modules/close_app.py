"""
Module d'action pour fermer proprement une application autorisée (SIGTERM, jamais SIGKILL).
Réutilise la liste blanche de [OPEN] (ACTIONS_OPEN_ALLOWED_APPS).
"""

from typing import List, Tuple
from actions.base import BaseAction
from core.config import ACTIONS_OPEN_ALLOWED_APPS

_CLOSE_SCRIPT = r"""
APP="${1:-}"
if [ -z "$APP" ]; then
    echo "Usage : close_app.sh <application>" >&2
    exit 1
fi

# Correspondance exacte du nom de processus, puis du binaire dans la ligne de commande
if pkill -TERM -x "$APP" 2>/dev/null || pkill -TERM -f "/${APP}( |\$)" 2>/dev/null; then
    echo "$APP fermé."
    exit 0
fi

echo "Aucun processus '$APP' en cours." >&2
exit 1
"""


class CloseAppAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="CLOSE",
            done_message="Je ferme ${ARGS}.",
            description="Fermer une application ouverte (ex: firefox, spotify, vlc). Seules les applications autorisées.",
            script_code=_CLOSE_SCRIPT,
            has_args=True,
            args_hint="<application>",
            example_prompt="Ferme Spotify.",
            example_response="[CLOSE spotify] Je ferme Spotify."
        )

    def decision_choices(self):
        return {app: app for app in ACTIONS_OPEN_ALLOWED_APPS}

    def build_args(self, args: str = "") -> List[str]:
        app = " ".join((args or "").lower().split())
        if app not in ACTIONS_OPEN_ALLOWED_APPS:
            print(f"⛔ [ACTIONS] Application non autorisée pour [CLOSE] : '{args}' (voir ACTIONS_OPEN_ALLOWED_APPS)")
            return []
        return [app]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        cmd_args = self.build_args(args)
        if not cmd_args:
            return 1, "", f"Application non autorisée ou invalide : '{args}'"
        app = cmd_args[0].lower().strip()
        app_target = app if app.endswith(".exe") else f"{app}.exe"
        try:
            import subprocess
            print(f"🚀 [ACTIONS] [Windows] Fermeture de l'application '{app_target}'...")
            res = subprocess.run(["taskkill", "/IM", app_target, "/F"], capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                print(f"✅ [ACTIONS] [Windows] Application '{app_target}' fermée.")
                return 0, f"{app} fermé", ""
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [CloseAppAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/close_app.py")
    print(f"'Firefox' -> {ACTIONS[0].build_args('Firefox')} | 'poweroff' -> {ACTIONS[0].build_args('poweroff')}")
