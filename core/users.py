"""
Comptes utilisateurs de la passerelle (PWA) : qui est connecté, avec quel rôle et quels droits.

L'annuaire est choisi par AUTH_PROVIDER dans le registre USER_DIRECTORIES :
- "none" : pas de comptes, seul le jeton GATEWAY_AUTH_TOKEN ouvre l'accès (administrateur) ;
- "pocketbase" : un compte par personne dans PocketBase. La PWA ne parle jamais à PocketBase :
  la passerelle vérifie l'identifiant et le mot de passe (ou le jeton du compte) à la connexion,
  puis la session est liée à ce compte (son rôle limite les outils et l'accès aux paramètres).

Le jeton maître GATEWAY_AUTH_TOKEN reste l'accès administrateur (appairage QR, serveur MCP, client CLI).
Le micro de l'ordinateur n'identifie pas la voix : il utilise le compte fixe « Foyer » (AUTH_LOCAL_ROLE).
"""

import json
import sys
from string import Template
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings
from core.providers import ProviderRegistry
from core.tools import ToolPolicy


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    # Jeton de l'annuaire, renvoyé au client pour ses prochaines connexions (jamais le mot de passe)
    token: str = ""
    # Consignes personnelles (ton, longueur des réponses...), ajoutées au prompt système de ses sessions
    instructions: str = ""
    # Voix de synthèse choisie (identifiant de TextToSpeech.voices() ; vide : voix par défaut)
    voice: str = ""

    @property
    def has_profile(self) -> bool:
        """Compte de l'annuaire (le jeton maître et le micro n'ont ni prénom ni consignes à eux)."""
        return self.id not in (ADMIN_USER_ID, LOCAL_USER_ID)

    def public(self, settings: Settings) -> dict:
        """Ce que le client peut savoir de lui-même (affichage, boutons réservés aux administrateurs, profil)."""
        return {"id": self.id, "name": self.name, "role": self.role, "admin": is_admin(self, settings),
                "instructions": self.instructions, "voice": self.voice, "profile": self.has_profile}


class AuthError(Exception):
    """Identifiants ou jeton refusés par l'annuaire."""


class DirectoryUnavailable(Exception):
    """L'annuaire ne répond pas ou est mal configuré (ce n'est pas la faute de l'utilisateur)."""


# Identifiant réservé au jeton maître et au micro : aucun compte de l'annuaire ne peut les usurper
ADMIN_USER_ID = "admin"
LOCAL_USER_ID = "local"


def admin_user(settings: Optional[Settings] = None) -> User:
    """Détenteur du jeton maître (ou client local d'une passerelle sans jeton)."""
    s = settings or get_settings()
    return User(ADMIN_USER_ID, "Administrateur", (s.AUTH_ADMIN_ROLES or ["admin"])[0])


def local_user(settings: Optional[Settings] = None) -> User:
    """Micro de l'ordinateur : personne n'est identifié, c'est le foyer qui parle."""
    s = settings or get_settings()
    return User(LOCAL_USER_ID, "Foyer", s.AUTH_LOCAL_ROLE)


def is_admin(user: Optional[User], settings: Optional[Settings] = None) -> bool:
    s = settings or get_settings()
    return user is not None and user.role in s.AUTH_ADMIN_ROLES


def user_prompt(user: Optional[User], settings: Optional[Settings] = None) -> str:
    """Lignes ajoutées au prompt système pour ce compte : à qui l'assistant parle, et ses préférences.
    Les consignes ne changent que le style : les droits restent ceux du rôle (ToolPolicy, vérifiés côté serveur)."""
    if user is None or not user.has_profile:
        return ""
    s = settings or get_settings()
    values = {"NAME": user.name, "INSTRUCTIONS": user.instructions}
    lines = [Template(s.AUTH_USER_PROMPT).safe_substitute(values).strip()]
    if user.instructions:
        lines.append(Template(s.AUTH_USER_INSTRUCTIONS_PROMPT).safe_substitute(values).strip())
    return "\n".join(line for line in lines if line)


def clean_profile(name: str, instructions: str, settings: Optional[Settings] = None) -> tuple[str, str]:
    """Prénom et consignes saisis dans la PWA : espaces superflus retirés, longueur bornée."""
    s = settings or get_settings()
    name = " ".join(str(name or "").split())[:80]
    if not name:
        raise ValueError("Le prénom ne peut pas être vide.")
    return name, str(instructions or "").strip()[:s.AUTH_INSTRUCTIONS_MAX_CHARS]


def tool_policy(user: Optional[User], settings: Optional[Settings] = None) -> Optional[ToolPolicy]:
    """Outils permis à l'utilisateur (None : aucune restriction, appel interne sans utilisateur)."""
    if user is None:
        return None
    s = settings or get_settings()
    return ToolPolicy.parse(s.AUTH_ROLE_TOOLS.get(user.role, ""))


# ==========================================
# Annuaires
# ==========================================
class UserDirectory:
    """Interface d'un annuaire de comptes."""
    provider_name = "base"
    enabled = True

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return cls.provider_name

    def login(self, identity: str, password: str) -> User:
        """Vérifie identifiant + mot de passe. Lève AuthError ou DirectoryUnavailable."""
        raise NotImplementedError

    def refresh(self, token: str) -> User:
        """Vérifie un jeton de compte et en renvoie un neuf. Lève AuthError ou DirectoryUnavailable."""
        raise NotImplementedError

    def update_profile(self, user: User, name: str, instructions: str, voice: str = "") -> User:
        """Enregistre le prénom, les consignes et la voix du compte (avec ses propres droits, jamais ceux d'un admin).
        La voix doit avoir été validée par l'appelant (voix installées sur cette machine)."""
        raise NotImplementedError


USER_DIRECTORIES: ProviderRegistry[UserDirectory] = ProviderRegistry("annuaire")


@USER_DIRECTORIES.register("none", "off", "token")
class NoDirectory(UserDirectory):
    enabled = False

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return "Aucun (jeton unique)"

    def login(self, identity: str, password: str) -> User:
        raise AuthError("Les comptes utilisateurs sont désactivés (AUTH_PROVIDER=none) : utilisez le jeton.")

    def refresh(self, token: str) -> User:
        raise AuthError("Les comptes utilisateurs sont désactivés (AUTH_PROVIDER=none) : utilisez le jeton.")

    def update_profile(self, user: User, name: str, instructions: str, voice: str = "") -> User:
        raise AuthError("Les comptes utilisateurs sont désactivés (AUTH_PROVIDER=none).")


@USER_DIRECTORIES.register("pocketbase", "pb")
class PocketBaseDirectory(UserDirectory):
    """Comptes d'une collection « auth » de PocketBase (API REST, bibliothèque standard uniquement)."""

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"PocketBase ({settings.POCKETBASE_URL}, collection {settings.POCKETBASE_USERS_COLLECTION})"

    def _url(self, action: str) -> str:
        collection = urllib.parse.quote(self.settings.POCKETBASE_USERS_COLLECTION, safe="")
        return f"{self.settings.POCKETBASE_URL.rstrip('/')}/api/collections/{collection}/{action}"

    def _post(self, action: str, body: Optional[dict] = None, token: str = "", method: str = "POST",
              not_found_is_refusal: bool = False) -> dict:
        """`not_found_is_refusal` : pour un enregistrement, PocketBase répond 404 quand la règle d'accès refuse."""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        request = urllib.request.Request(
            self._url(action), data=json.dumps(body or {}).encode(), headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.POCKETBASE_TIMEOUT) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (400, 401, 403) or (e.code == 404 and not_found_is_refusal):
                raise AuthError("Identifiants refusés.") from e
            if e.code == 404:
                raise DirectoryUnavailable(
                    f"Collection PocketBase « {self.settings.POCKETBASE_USERS_COLLECTION} » introuvable."
                ) from e
            raise DirectoryUnavailable(f"PocketBase a répondu {e.code}.") from e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise DirectoryUnavailable(f"PocketBase injoignable ({self.settings.POCKETBASE_URL}) : {e}") from e

    def _user(self, data: dict) -> User:
        record = data.get("record") or {}
        token = data.get("token") or ""
        if not record.get("id") or not token:
            raise DirectoryUnavailable("Réponse de PocketBase inattendue (ni compte ni jeton).")
        return self._from_record(record, token)

    def _from_record(self, record: dict, token: str) -> User:
        # Un compte de l'annuaire ne peut jamais prendre l'identité réservée du jeton maître ou du micro
        user_id = f"pb_{record['id']}"
        name = record.get("name") or record.get("username") or record.get("email") or record["id"]
        role = str(record.get("role") or self.settings.AUTH_DEFAULT_ROLE).strip().lower()
        instructions = str(record.get("instructions") or "")[:self.settings.AUTH_INSTRUCTIONS_MAX_CHARS]
        return User(user_id, str(name), role, token, instructions, str(record.get("voice") or "")[:100])

    def login(self, identity: str, password: str) -> User:
        if not identity or not password:
            raise AuthError("Identifiant et mot de passe requis.")
        return self._user(self._post("auth-with-password", {"identity": identity, "password": password}))

    def refresh(self, token: str) -> User:
        if not token:
            raise AuthError("Jeton de compte manquant.")
        return self._user(self._post("auth-refresh", token=token))

    def update_profile(self, user: User, name: str, instructions: str, voice: str = "") -> User:
        if not user.has_profile or not user.token:
            raise AuthError("Ce compte n'a pas de profil modifiable.")
        name, instructions = clean_profile(name, instructions, self.settings)
        record_id = urllib.parse.quote(user.id.removeprefix("pb_"), safe="")
        # Jeton du compte lui-même : la règle de la collection lui interdit de toucher à son rôle
        try:
            record = self._post(f"records/{record_id}", {"name": name, "instructions": instructions, "voice": voice},
                                token=user.token, method="PATCH", not_found_is_refusal=True)
        except AuthError as e:
            raise AuthError("Profil refusé par PocketBase (session expirée ? reconnectez-vous).") from e
        if not record.get("id"):
            raise DirectoryUnavailable("Réponse de PocketBase inattendue (compte absent).")
        return self._from_record(record, user.token)


def create_directory(settings: Optional[Settings] = None) -> UserDirectory:
    s = settings or get_settings()
    return USER_DIRECTORIES.create(s.AUTH_PROVIDER, s)


if __name__ == "__main__":
    import getpass

    s = get_settings()
    directory = create_directory(s)
    print(f"🧪 [DEBUG] Annuaire : {directory.describe(s)}")
    for role, rules in s.AUTH_ROLE_TOOLS.items():
        print(f"  • rôle {role:<8}: outils « {rules} »{' (administrateur)' if role in s.AUTH_ADMIN_ROLES else ''}")
    if directory.enabled:
        try:
            identity = input("Identifiant (email) : ").strip()
            user = directory.login(identity, getpass.getpass("Mot de passe : "))
            print(f"✅ Connecté : {user.name} (rôle {user.role}, admin={is_admin(user, s)})")
            print(f"✅ Jeton renouvelé : {bool(directory.refresh(user.token).token)}")
        except (AuthError, DirectoryUnavailable) as e:
            print(f"❌ {e}")
        except (KeyboardInterrupt, EOFError):
            pass
