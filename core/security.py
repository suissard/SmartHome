"""
Sécurité des services réseau (serveur MCP, passerelle) : jeton Bearer et règle « pas d'écoute réseau sans jeton ».
"""

import hmac
from typing import Iterable


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def token_matches(provided: str, expected: str) -> bool:
    """Comparaison en temps constant (évite de deviner le jeton caractère par caractère)."""
    return bool(expected) and hmac.compare_digest(provided.encode(), expected.encode())


def require_token_for_host(host: str, token: str, service: str, variable: str):
    """Refuse de démarrer un service hors loopback (LAN, Tailscale...) sans jeton configuré."""
    if not token and not is_loopback(host):
        raise SystemExit(
            f"❌ [{service}] Refus d'écouter sur {host} sans {variable} : n'importe quel appareil du réseau "
            f"pourrait piloter l'ordinateur. Définissez {variable} dans .env (ex: `openssl rand -hex 32`)."
        )


def bearer_from_headers(headers: Iterable[tuple[bytes, bytes]]) -> str:
    """Extrait le jeton d'un en-tête `Authorization: Bearer <jeton>` (scope ASGI)."""
    value = dict(headers).get(b"authorization", b"").decode(errors="ignore")
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


class BearerTokenMiddleware:
    """Middleware ASGI pur (compatible SSE/streaming) exigeant `Authorization: Bearer <token>` sur les requêtes HTTP.
    Les chemins de `exempt_paths` et les WebSockets (authentifiés par leur propre handler) ne sont pas filtrés."""

    def __init__(self, asgi_app, token: str, exempt_paths: Iterable[str] = ()):
        self.asgi_app = asgi_app
        self.token = token
        self.exempt_paths = set(exempt_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") not in self.exempt_paths:
            if not token_matches(bearer_from_headers(scope.get("headers", [])), self.token):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"www-authenticate", b"Bearer")],
                })
                await send({"type": "http.response.body", "body": "Jeton manquant ou invalide.".encode()})
                return
        await self.asgi_app(scope, receive, send)
