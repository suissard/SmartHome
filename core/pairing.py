"""
Appairage d'un appareil : URL de l'interface web (jeton dans le fragment) et QR code à afficher dans le terminal.
Le jeton est placé dans le fragment (#token=...) : il n'est jamais envoyé au serveur, ni écrit dans ses journaux
ni transmis en en-tête Referer. Le front le lit, le mémorise et l'efface de la barre d'adresse.
"""

import json
import socket
import subprocess
from urllib.parse import quote, urlparse

from core.config import Settings, get_settings
from core.security import is_loopback


def _lan_ip() -> str:
    """Adresse IP de cette machine sur le réseau local (sans envoyer de paquet)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _tailscale_json(*args: str) -> dict:
    try:
        out = subprocess.run(["tailscale", *args, "--json"], capture_output=True, text=True, timeout=3, check=True)
        return json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def tailscale_serve_url(port: int) -> str:
    """URL HTTPS publiée par `tailscale serve` pour ce port (vide si aucune)."""
    for hostport, web in (_tailscale_json("serve", "status").get("Web") or {}).items():
        for handler in (web.get("Handlers") or {}).values():
            target = urlparse(handler.get("Proxy", ""))
            if target.hostname in ("127.0.0.1", "localhost", "::1") and target.port == port:
                host, _, tcp_port = hostport.rpartition(":")
                return f"https://{host}" + ("" if tcp_port == "443" else f":{tcp_port}")
    return ""


def tailscale_ip() -> str:
    """Première adresse IPv4 Tailscale de cette machine (vide si Tailscale est arrêté)."""
    status = _tailscale_json("status")
    if status.get("BackendState") != "Running":
        return ""
    return next((ip for ip in status.get("TailscaleIPs", []) if "." in ip), "")


def base_url(settings: Settings) -> str:
    """URL de l'interface : GATEWAY_PUBLIC_URL, sinon celle de `tailscale serve`, sinon GATEWAY_HOST / GATEWAY_PORT."""
    if settings.GATEWAY_PUBLIC_URL:
        return settings.GATEWAY_PUBLIC_URL.rstrip("/")
    if settings.GATEWAY_TAILSCALE_URL and (url := tailscale_serve_url(settings.GATEWAY_PORT)):
        return url
    host = settings.GATEWAY_HOST
    if host in ("0.0.0.0", "::"):
        host = (settings.GATEWAY_TAILSCALE_URL and tailscale_ip()) or _lan_ip()
    return f"http://{host}:{settings.GATEWAY_PORT}"


def pairing_url(settings: Settings) -> str:
    """URL de connexion directe, avec le jeton s'il y en a un."""
    url = base_url(settings) + "/"
    return f"{url}#token={quote(settings.GATEWAY_AUTH_TOKEN, safe='')}" if settings.GATEWAY_AUTH_TOKEN else url


def qr_text(url: str) -> str:
    """QR code en caractères (blocs demi-hauteur), lisible dans un terminal."""
    import segno

    import io
    out = io.StringIO()
    segno.make(url, error="m").terminal(out=out, compact=True, border=2)
    return out.getvalue()


def print_pairing(settings: Settings | None = None):
    """Affiche l'URL de connexion et son QR code (rien si la passerelle n'est pas utilisable à distance)."""
    s = settings or get_settings()
    if not s.GATEWAY_QR_ENABLED:
        return
    url = pairing_url(s)
    print(f"\n📱 Interface web : {url}")
    if url.startswith("http://127.0.0.1") and is_loopback(s.GATEWAY_HOST):
        print("   (écoute locale uniquement : définissez GATEWAY_PUBLIC_URL ou GATEWAY_HOST pour un autre appareil)")
    try:
        print(qr_text(url))
    except ImportError:
        print("   (QR code indisponible : pip install segno)")


if __name__ == "__main__":
    print_pairing()
