"""
Module d'action pour l'extinction complète de l'ordinateur.
Contient les métadonnées et le script d'extinction sécurisé (Linux et Windows).
"""

import subprocess
import sys
from typing import Tuple
from actions.base import BaseAction

_SHUTDOWN_SCRIPT = r"""
if command -v systemctl >/dev/null 2>&1; then
    systemctl poweroff
elif command -v shutdown >/dev/null 2>&1; then
    shutdown -h now
else
    echo "Erreur : Commande d'extinction introuvable." >&2
    exit 1
fi
"""


class ShutdownAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="SHUTDOWN",
            done_message="J'éteins l'ordinateur.",
            description="Éteindre complètement l'ordinateur.",
            script_code=_SHUTDOWN_SCRIPT,
            has_args=False,
            danger="confirm",
            example_prompt="Éteins l'ordinateur s'il te plaît.",
            example_response="[SHUTDOWN] J'éteins l'ordinateur. Bonne nuit !"
        )

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            print("🚀 [ACTIONS] [Windows] Lancement de l'extinction du système...")
            res = subprocess.run(["shutdown.exe", "/s", "/t", "0"], capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                print("✅ [ACTIONS] [Windows] Commande d'extinction transmise.")
            else:
                print(f"❌ [ACTIONS] [Windows] Échec shutdown : {res.stderr}")
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Exception shutdown : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print("🔍 [ACTIONS] [DRY RUN] [Windows] Extinction simulée")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [ShutdownAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/shutdown.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
