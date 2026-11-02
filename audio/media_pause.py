import atexit
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import MEDIA_PAUSE_ENABLED


class MediaPauser:
    """
    Met en pause les lecteurs multimédias (MPRIS via playerctl) pendant l'échange
    avec l'assistant, puis relance uniquement ceux qui étaient en lecture avant.
    Un lecteur déjà en pause au mot-clé n'est jamais relancé.
    """

    def __init__(self, enabled: bool = MEDIA_PAUSE_ENABLED):
        self.enabled = enabled
        self.paused_players: List[str] = []
        self._available = shutil.which("playerctl") is not None

        if not self._available and self.enabled:
            print("⚠️ [MEDIA] 'playerctl' non trouvé sur le système. Pause des médias désactivée.")
            self.enabled = False

        if self.enabled:
            atexit.register(self.resume)

    def _playerctl(self, *args: str) -> str:
        try:
            res = subprocess.run(
                ["playerctl", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=1.5,
            )
            return res.stdout.strip() if res.returncode == 0 else ""
        except Exception:
            return ""

    def pause(self) -> List[str]:
        """Met en pause les lecteurs en lecture et mémorise lesquels."""
        if not self.enabled:
            return []

        # Déjà en pause par nous (deuxième mot-clé sans reprise) : on garde la liste d'origine
        if self.paused_players:
            return list(self.paused_players)

        for player in self._playerctl("-l").splitlines():
            player = player.strip()
            if player and self._playerctl("-p", player, "status") == "Playing":
                self._playerctl("-p", player, "pause")
                self.paused_players.append(player)
        return list(self.paused_players)

    def resume(self) -> List[str]:
        """Relance les lecteurs mis en pause par `pause()` (seulement s'ils sont restés en pause)."""
        resumed: List[str] = []
        for player in self.paused_players:
            if self._playerctl("-p", player, "status") == "Paused":
                self._playerctl("-p", player, "play")
                resumed.append(player)
        self.paused_players = []
        return resumed


if __name__ == "__main__":
    import time

    print("🧪 [DEBUG] Test du module Pause Média (MPRIS / playerctl)...")
    pauser = MediaPauser(enabled=True)
    print(f"  • Statut : {'Activé' if pauser.enabled else 'Désactivé'}")
    if pauser.enabled:
        print(f"  • Lecteurs détectés : {pauser._playerctl('-l').splitlines() or 'aucun'}")
        print(f"👉 Mis en pause : {pauser.pause() or 'rien (aucun média en lecture)'}")
        time.sleep(3.0)
        print(f"👉 Relancés : {pauser.resume() or 'rien'}")
