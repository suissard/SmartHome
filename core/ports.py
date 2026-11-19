"""
Port de la passerelle : si GATEWAY_PORT est déjà pris (un autre logiciel, une autre instance de SmartHome),
la passerelle prend le premier port libre parmi les GATEWAY_PORT_FALLBACK suivants au lieu de planter.
Le port retenu est ensuite publié sur le tailnet par `tailscale serve` (voir core/pairing.py).

Test isolé : python core/ports.py [port]
"""

import json
import os
import socket
import sys
import urllib.request
from typing import Optional

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings, get_settings

_HEALTH_TIMEOUT = 1.0


def _bind_host(host: str) -> str:
    return host or "0.0.0.0"


def port_free(host: str, port: int) -> bool:
    """Vrai si un serveur peut écouter sur host:port (même options que uvicorn : SO_REUSEADDR hors Windows,
    pour ne pas prendre pour occupé un port en TIME_WAIT après un redémarrage)."""
    host = _bind_host(host)
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, port: int, tries: int) -> Optional[int]:
    """`port` s'il est libre, sinon le premier libre des `tries` suivants (None si aucun)."""
    for candidate in range(port, min(port + tries, 65535) + 1):
        if port_free(host, candidate):
            return candidate
    return None


def is_smarthome(port: int) -> bool:
    """Vrai si le port est tenu par une passerelle SmartHome (une autre instance déjà lancée)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=_HEALTH_TIMEOUT) as response:
            return json.loads(response.read()).get("service") == "smarthome-gateway"
    except (OSError, ValueError, AttributeError):
        return False


class PortUnavailable(RuntimeError):
    pass


def resolve_gateway_port(settings: Optional[Settings] = None) -> Settings:
    """Réglages dont GATEWAY_PORT est un port libre. Lève PortUnavailable si aucun ne l'est."""
    s = settings or get_settings()
    wanted = s.GATEWAY_PORT
    port = find_free_port(s.GATEWAY_HOST, wanted, s.GATEWAY_PORT_FALLBACK)
    if port is None:
        last = min(wanted + s.GATEWAY_PORT_FALLBACK, 65535)
        span = f"{wanted}" if last == wanted else f"{wanted} à {last}"
        raise PortUnavailable(f"port {span} déjà utilisé : changez GATEWAY_PORT (ou GATEWAY_PORT_FALLBACK) dans .env")
    if port != wanted:
        who = "une autre instance de SmartHome" if is_smarthome(wanted) else "un autre logiciel"
        print(f"⚠️  [PASSERELLE] Port {wanted} déjà utilisé par {who} : port {port} utilisé à la place.")
        if who.startswith("une autre"):
            print("   Deux SmartHome se partagent alors le micro : arrêtez l'autre (systemctl --user stop smarthome).")
    return s.model_copy(update={"GATEWAY_PORT": port})


if __name__ == "__main__":
    s = get_settings()
    if len(sys.argv) > 1:
        s = s.model_copy(update={"GATEWAY_PORT": int(sys.argv[1])})
    print(f"Port demandé : {s.GATEWAY_HOST}:{s.GATEWAY_PORT} ({'libre' if port_free(s.GATEWAY_HOST, s.GATEWAY_PORT) else 'occupé'})")
    try:
        print(f"Port retenu  : {resolve_gateway_port(s).GATEWAY_PORT}")
    except PortUnavailable as e:
        print(f"❌ {e}")
