"""
Module d'action pour le redémarrage du système.
Contient les métadonnées et le script de redémarrage (Linux et Windows).
"""

import subprocess
from typing import Tuple
from actions.base import BaseAction

_REBOOT_SCRIPT = r"""
if command -v systemctl >/dev/null 2>&1; then
    systemctl reboot
elif command -v reboot >/dev/null 2>&1; then
    reboot
else
    echo "Erreur : Commande de redémarrage introuvable." >&2
    exit 1
fi
"""


class RebootAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="REBOOT",
            done_message="Je redémarre l'ordinateur.",
            description="Redémarrer l'ordinateur.",
            script_code=_REBOOT_SCRIPT,
            has_args=False,
            danger="confirm",
            example_prompt="Redémarre le système.",
            example_response="[REBOOT] Redémarrage de la machine en cours."
        )

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            print("🚀 [ACTIONS] [Windows] Lancement du redémarrage du système...")
            res = subprocess.run(["shutdown.exe", "/r", "/t", "0"], capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                print("✅ [ACTIONS] [Windows] Commande de redémarrage transmise.")
            else:
                print(f"❌ [ACTIONS] [Windows] Échec reboot : {res.stderr}")
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Exception reboot : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print("🔍 [ACTIONS] [DRY RUN] [Windows] Redémarrage simulé")
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [RebootAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/reboot.py")
    print(f"Action : [{ACTIONS[0].tag}] chargée avec succès.")
