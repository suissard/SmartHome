"""
Redémarrage de SmartHome depuis l'interface web.

`request_restart()` déclenche l'arrêt normal (comme Ctrl+C : médias relancés, micro libéré, serveurs MCP déconnectés),
puis le point d'entrée appelle `restart_if_requested()` qui relance la même commande dans le même processus
(profil et options conservés, compatible avec un service systemd).
"""

import os
import signal
import sys
import threading

_requested = threading.Event()


def request_restart():
    """Demande le redémarrage : le signal interrompt la boucle principale de main.py ou de la passerelle."""
    _requested.set()
    signal.raise_signal(signal.SIGINT)


def restart_if_requested():
    """À appeler une fois l'arrêt terminé. Ne revient pas si un redémarrage a été demandé."""
    if _requested.is_set():
        print("🔄 Redémarrage de SmartHome...", flush=True)
        os.execv(sys.executable, sys.orig_argv)


if __name__ == "__main__":
    print(f"🧪 [DEBUG] Commande relancée au redémarrage : {sys.executable} {' '.join(sys.orig_argv[1:])}")
