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


async def _send_text(send, status: int, message: str, extra_headers=()):
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"text/plain; charset=utf-8"), *extra_headers],
    })
    await send({"type": "http.response.body", "body": message.encode()})


class BearerTokenMiddleware:
    """Middleware ASGI pur (compatible SSE/streaming) exigeant `Authorization: Bearer <token>` sur les requêtes HTTP.
    Si `protected_prefixes` est fourni, seuls ces chemins sont filtrés (ex: "/api/" ; l'interface web reste publique).
    Les WebSockets (authentifiés par leur propre handler) ne sont pas filtrés."""

    def __init__(self, asgi_app, token: str, exempt_paths: Iterable[str] = (), protected_prefixes: Iterable[str] = ()):
        self.asgi_app = asgi_app
        self.token = token
        self.exempt_paths = set(exempt_paths)
        self.protected_prefixes = tuple(protected_prefixes)

    def _is_protected(self, path: str) -> bool:
        if path in self.exempt_paths:
            return False
        return not self.protected_prefixes or path.startswith(self.protected_prefixes)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._is_protected(scope.get("path", "")):
            if not token_matches(bearer_from_headers(scope.get("headers", [])), self.token):
                await _send_text(send, 401, "Jeton manquant ou invalide.", [(b"www-authenticate", b"Bearer")])
                return
        await self.asgi_app(scope, receive, send)


# En-têtes ajoutés par un proxy (tailscale serve, nginx...) : la requête ne vient pas de cette machine
_PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"tailscale-user-login")


def is_proxied(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    names = {name.lower() for name, _ in headers}
    return any(h in names for h in _PROXY_HEADERS)


class LocalOnlyMiddleware:
    """Sans jeton, le service n'est autorisé qu'en local. Un proxy comme `tailscale serve` écoute en loopback
    mais relaie tout le tailnet : on refuse donc les requêtes relayées tant qu'aucun jeton n'est configuré."""

    MESSAGE = "Accès distant refusé : configurez GATEWAY_AUTH_TOKEN pour utiliser la passerelle via un proxy (tailscale serve)."

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and is_proxied(scope.get("headers", [])):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4403, "reason": "Jeton requis via proxy"})
            else:
                await _send_text(send, 403, self.MESSAGE)
            return
        await self.asgi_app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Ajoute des en-têtes de sécurité aux réponses HTTP (interface web : scripts et connexions limités à l'origine)."""

    HEADERS = [
        (b"content-security-policy",
         b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
         b"media-src 'self' blob: data:; connect-src 'self' ws: wss:; worker-src 'self'; "
         b"frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
    ]

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.asgi_app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *self.HEADERS]}
            await send(message)
        await self.asgi_app(scope, receive, send_with_headers)
