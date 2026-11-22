"""
Appairage d'un appareil : URL de l'interface web (jeton dans le fragment) et QR code à afficher dans le terminal.
Le jeton est placé dans le fragment (#token=...) : il n'est jamais envoyé au serveur, ni écrit dans ses journaux
ni transmis en en-tête Referer. Le front le lit, le mémorise et l'efface de la barre d'adresse.
"""

import json
import os
import socket
import subprocess
from typing import Optional
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


def _tailscale_bin() -> str:
    """Chemin de l'exécutable tailscale (y compris sous Windows où il n'est pas toujours dans le PATH)."""
    import shutil, sys
    found = shutil.which("tailscale")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in (
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Tailscale", "tailscale.exe"),
            os.path.join(os.environ.get("LocalAppData", ""), "Tailscale", "tailscale.exe"),
        ):
            if os.path.isfile(candidate):
                return candidate
    return "tailscale"


def _tailscale_json(*args: str) -> dict:
    try:
        out = subprocess.run([_tailscale_bin(), *args, "--json"], capture_output=True, text=True, timeout=3, check=True)
        return json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _serve_proxies(status: dict) -> list[tuple[str, int, Optional[int]]]:
    """(nom d'hôte, port HTTPS, port local visé ou None) de chaque publication `tailscale serve`."""
    found = []
    for hostport, web in (status.get("Web") or {}).items():
        host, _, tcp_port = hostport.rpartition(":")
        if not tcp_port.isdigit():
            continue
        for handler in (web.get("Handlers") or {}).values():
            target = urlparse(handler.get("Proxy", ""))
            try:
                local = target.port if target.hostname in ("127.0.0.1", "localhost", "::1") else None
            except ValueError:
                local = None
            found.append((host, int(tcp_port), local))
    return found


def _https_url(host: str, tcp_port: int) -> str:
    return f"https://{host}" + ("" if tcp_port == 443 else f":{tcp_port}")


def tailscale_serve_url(port: int, status: Optional[dict] = None) -> str:
    """URL HTTPS publiée par `tailscale serve` pour ce port (vide si aucune)."""
    if status is None:
        status = _tailscale_json("serve", "status")
    for host, tcp_port, local in _serve_proxies(status):
        if local == port:
            return _https_url(host, tcp_port)
    return ""


def _serve_port_to_use(status: dict, port: int, ours: range, candidates: list[int]) -> Optional[tuple[int, bool]]:
    """Port HTTPS du tailnet où publier la passerelle, et s'il faut d'abord retirer une ancienne publication.
    Un port déjà utilisé par un autre logiciel n'est jamais repris ; une publication laissée par SmartHome
    (vers un port de `ours` où plus rien n'écoute) l'est, pour garder la même adresse sur le téléphone."""
    from core.ports import port_free
    proxies = {tcp_port: local for _, tcp_port, local in _serve_proxies(status)}
    taken = {int(p) for p in (status.get("TCP") or {}) if str(p).isdigit()} | set(proxies)
    for candidate in candidates:
        if candidate not in taken:
            return candidate, False
        local = proxies.get(candidate)
        if local is not None and local != port and local in ours and port_free("127.0.0.1", local):
            return candidate, True
    return None


def publish_tailscale_serve(settings: Settings, requested_port: Optional[int] = None) -> str:
    """Publie la passerelle sur le tailnet (`tailscale serve --bg`, HTTPS exigé par le micro du téléphone) si elle
    ne l'est pas déjà, sur un port HTTPS libre de GATEWAY_TAILSCALE_HTTPS_PORTS. Renvoie l'URL (vide sinon)."""
    s = settings
    if not (s.GATEWAY_TAILSCALE_SERVE and s.GATEWAY_TAILSCALE_URL) or s.GATEWAY_PUBLIC_URL:
        return ""
    # Sans jeton, LocalOnlyMiddleware refuse ce qui passe par un proxy ; tailscale serve vise 127.0.0.1
    if not s.GATEWAY_AUTH_TOKEN or not (is_loopback(s.GATEWAY_HOST) or s.GATEWAY_HOST in ("", "0.0.0.0", "::")):
        return ""
    if not tailscale_ip():
        return ""
    status = _tailscale_json("serve", "status")
    if url := tailscale_serve_url(s.GATEWAY_PORT, status):
        return url
    base = requested_port or s.GATEWAY_PORT
    choice = _serve_port_to_use(status, s.GATEWAY_PORT, range(base, base + s.GATEWAY_PORT_FALLBACK + 1),
                                s.GATEWAY_TAILSCALE_HTTPS_PORTS)
    if choice is None:
        ports = ", ".join(map(str, s.GATEWAY_TAILSCALE_HTTPS_PORTS))
        print(f"⚠️  [TAILSCALE] Ports HTTPS {ports} déjà utilisés : ajoutez-en un à GATEWAY_TAILSCALE_HTTPS_PORTS.")
        return ""
    https_port, replace = choice
    target = f"http://127.0.0.1:{s.GATEWAY_PORT}"
    commands = ([[_tailscale_bin(), "serve", f"--https={https_port}", "off"]] if replace else [])
    commands.append([_tailscale_bin(), "serve", "--bg", f"--https={https_port}", target])
    for cmd in commands:
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"⚠️  [TAILSCALE] Publication impossible : {e}")
            return ""
        if done.returncode != 0:
            output = (done.stderr or done.stdout or "").strip()
            if "operator" in output or "sudo" in output or "Access denied" in output:
                print(f"⚠️  [TAILSCALE] Publication refusée (droits) : lancez une fois 'sudo tailscale set --operator=$USER',"
                      f" ou 'sudo tailscale serve --bg --https={https_port} {target}'.")
            else:
                print(f"⚠️  [TAILSCALE] Publication impossible : {output.splitlines()[-1] if output else done.returncode}")
            return ""
    url = tailscale_serve_url(s.GATEWAY_PORT)
    if url:
        print(f"🔒 [TAILSCALE] Passerelle publiée sur le tailnet : {url}")
    return url


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
