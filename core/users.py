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

import contextlib
import json
import sqlite3
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
    # Adresse e-mail du compte dans l'annuaire
    email: str = ""
    # Compte référencé comme superadministrateur (_superusers) dans PocketBase
    superadmin: bool = False

    @property
    def has_profile(self) -> bool:
        """Compte de l'annuaire (le jeton maître et le micro n'ont ni prénom ni consignes à eux)."""
        return self.id not in (ADMIN_USER_ID, LOCAL_USER_ID)

    def public(self, settings: Settings) -> dict:
        """Ce que le client peut savoir de lui-même (affichage, boutons réservés aux administrateurs, profil)."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "admin": is_admin(self, settings),
            "superadmin": self.superadmin,
            "email": self.email,
            "instructions": self.instructions,
            "voice": self.voice,
            "profile": self.has_profile,
        }


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
    return user is not None and (user.superadmin or user.role in s.AUTH_ADMIN_ROLES)


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
    if user.superadmin and user.role not in s.AUTH_ROLE_TOOLS:
        admin_role = (s.AUTH_ADMIN_ROLES or ["admin"])[0]
        return ToolPolicy.parse(s.AUTH_ROLE_TOOLS.get(admin_role, "*"))
    policy = ToolPolicy.parse(s.AUTH_ROLE_TOOLS.get(user.role, "*" if user.superadmin else ""))
    if user.superadmin:
        return policy
    # Outils réservés aux superadmins : retirés de tous les autres comptes (jeton maître et micro « Foyer » compris)
    reserved = frozenset(name.strip().lower() for name in s.AUTH_SUPERADMIN_TOOLS if name.strip())
    if not is_admin(user, s):
        # Outils d'administration (paramètres de l'assistant) : réservés aux rôles AUTH_ADMIN_ROLES
        reserved |= frozenset(name.strip().lower() for name in s.AUTH_ADMIN_TOOLS if name.strip())
    return ToolPolicy(allowed=policy.allowed, denied=policy.denied | reserved)


# ==========================================
# API REST de PocketBase (bibliothèque standard)
# ==========================================
def pb_request(settings: Settings, path: str, body: Optional[dict] = None, token: str = "", method: str = "POST",
               not_found_is_refusal: bool = False, query: Optional[dict] = None) -> dict:
    """Requête vers /api/collections/<path>. Lève AuthError (refus) ou DirectoryUnavailable (serveur, configuration).
    `not_found_is_refusal` : pour un enregistrement, PocketBase répond 404 quand la règle d'accès refuse."""
    collection, _, rest = path.partition("/")
    url = (f"{settings.POCKETBASE_URL.rstrip('/')}/api/collections/{urllib.parse.quote(collection, safe='')}"
           f"{'/' + rest if rest else ''}{'?' + urllib.parse.urlencode(query) if query else ''}")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    data = json.dumps(body or {}).encode() if method in ("POST", "PATCH") else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=settings.POCKETBASE_TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (400, 401, 403) or (e.code == 404 and not_found_is_refusal):
            raise AuthError("Identifiants refusés.") from e
        if e.code == 404:
            raise DirectoryUnavailable(f"Collection PocketBase « {collection} » introuvable.") from e
        raise DirectoryUnavailable(f"PocketBase a répondu {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise DirectoryUnavailable(f"PocketBase injoignable ({settings.POCKETBASE_URL}) : {e}") from e


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

    def list_users(self, admin: User) -> list[dict]:
        """Liste les comptes de l'annuaire (réservé aux superadministrateurs)."""
        raise AuthError("Gestion des comptes non prise en charge par cet annuaire.")

    def create_user(self, admin: User, email: str, password: str, name: str = "", role: str = "member") -> dict:
        """Crée un compte utilisateur dans l'annuaire (réservé aux superadministrateurs)."""
        raise AuthError("Gestion des comptes non prise en charge par cet annuaire.")

    def update_user_role(self, admin: User, record_id: str, role: str, name: Optional[str] = None) -> dict:
        """Modifie le rôle (et éventuellement le prénom) d'un compte (réservé aux superadministrateurs)."""
        raise AuthError("Gestion des comptes non prise en charge par cet annuaire.")

    def delete_user(self, admin: User, record_id: str) -> bool:
        """Supprime un compte de l'annuaire (réservé aux superadministrateurs)."""
        raise AuthError("Gestion des comptes non prise en charge par cet annuaire.")


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


SUPERUSERS_COLLECTION = "_superusers"
_LOCAL_PB_DB = _ROOT_DIR / "pocketbase" / "pb_data" / "data.db"


@USER_DIRECTORIES.register("pocketbase", "pb")
class PocketBaseDirectory(UserDirectory):
    """Comptes d'une collection « auth » de PocketBase (API REST, bibliothèque standard uniquement),
    avec prise en charge directe des superadministrateurs référencés dans `_superusers`."""

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"PocketBase ({settings.POCKETBASE_URL}, collection {settings.POCKETBASE_USERS_COLLECTION})"

    def _post(self, action: str, body: Optional[dict] = None, token: str = "", method: str = "POST",
              not_found_is_refusal: bool = False, query: Optional[dict] = None) -> dict:
        return pb_request(self.settings, f"{self.settings.POCKETBASE_USERS_COLLECTION}/{action}", body, token, method,
                          not_found_is_refusal, query=query)

    def _db_superuser_emails(self) -> set[str]:
        """Emails référencés dans la table `_superusers` du PocketBase local (si présent sur le port par défaut)."""
        parsed = urllib.parse.urlparse(self.settings.POCKETBASE_URL)
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1") or (parsed.port or 80) != 8090:
            return set()
        if not _LOCAL_PB_DB.exists():
            return set()
        try:
            uri = f"file:{_LOCAL_PB_DB.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as conn:
                rows = conn.execute("SELECT email FROM _superusers").fetchall()
            return {str(r[0]).strip().lower() for r in rows if r and r[0]}
        except (sqlite3.Error, OSError):
            return set()

    def _is_db_superuser(self, identity_or_email: str) -> bool:
        val = str(identity_or_email or "").strip().lower()
        return bool(val) and val in self._db_superuser_emails()

    def _user(self, data: dict, superadmin: bool = False) -> User:
        record = data.get("record") or {}
        token = data.get("token") or ""
        if not record.get("id") or not token:
            raise DirectoryUnavailable("Réponse de PocketBase inattendue (ni compte ni jeton).")
        return self._from_record(record, token, superadmin=superadmin)

    def _from_record(self, record: dict, token: str, superadmin: bool = False) -> User:
        # Un compte de l'annuaire ne peut jamais prendre l'identité réservée du jeton maître ou du micro
        user_id = f"pb_{record['id']}"
        email = str(record.get("email") or "").strip()
        is_super = BooleanSuper(
            superadmin
            or bool(record.get("superadmin"))
            or record.get("collectionName") == SUPERUSERS_COLLECTION
            or self._is_db_superuser(email)
        )
        default_name = email.split("@")[0].replace(".", " ").title() if email else record["id"]
        name = record.get("name") or record.get("username") or default_name
        raw_role = str(record.get("role") or "").strip().lower()
        if is_super and raw_role not in (self.settings.AUTH_ADMIN_ROLES or ["admin"]):
            role = (self.settings.AUTH_ADMIN_ROLES or ["admin"])[0]
        else:
            role = raw_role or self.settings.AUTH_DEFAULT_ROLE
        instructions = str(record.get("instructions") or "")[:self.settings.AUTH_INSTRUCTIONS_MAX_CHARS]
        voice = str(record.get("voice") or "")[:100]
        return User(user_id, str(name), role, token, instructions, voice, email=email, superadmin=is_super)

    def _find_or_create_superuser_profile(self, su_record: dict, su_token: str, password: str = "") -> dict:
        """Associe un superadmin `_superusers` à son enregistrement dans `users` (pour profil et historique)."""
        email = str(su_record.get("email") or "").strip()
        if not email:
            return su_record
        safe_email = email.replace('"', "")
        try:
            res = self._post("records", token=su_token, method="GET",
                             query={"filter": f'email = "{safe_email}"', "perPage": 1})
            items = res.get("items") or []
            if items and items[0].get("id"):
                record = items[0]
                admin_role = (self.settings.AUTH_ADMIN_ROLES or ["admin"])[0]
                if record.get("role") != admin_role:
                    try:
                        record = self._post(f"records/{urllib.parse.quote(record['id'], safe='')}",
                                            {"role": admin_role}, token=su_token, method="PATCH")
                    except (AuthError, DirectoryUnavailable):
                        pass
                return record
            if password:
                admin_role = (self.settings.AUTH_ADMIN_ROLES or ["admin"])[0]
                default_name = email.split("@")[0].replace(".", " ").title()
                created = self._post("records", {
                    "email": email,
                    "password": password,
                    "passwordConfirm": password,
                    "name": default_name,
                    "role": admin_role,
                    "verified": True,
                }, token=su_token, method="POST")
                if created.get("id"):
                    return created
        except (AuthError, DirectoryUnavailable):
            pass
        return su_record

    def login(self, identity: str, password: str) -> User:
        if not identity or not password:
            raise AuthError("Identifiant et mot de passe requis.")
        try:
            data = self._post("auth-with-password", {"identity": identity, "password": password})
            record = data.get("record") or {}
            token = data.get("token") or ""
            email = str(record.get("email") or identity).strip()
            is_super = bool(record.get("superadmin")) or self._is_db_superuser(email)
            # Si le compte est aussi superadmin PocketBase, on récupère son jeton _superusers pour l'administration
            if is_super or str(record.get("role") or "") in (self.settings.AUTH_ADMIN_ROLES or ["admin"]):
                try:
                    su_data = pb_request(self.settings, f"{SUPERUSERS_COLLECTION}/auth-with-password",
                                         {"identity": email, "password": password})
                    if su_data.get("token"):
                        token = su_data["token"]
                        is_super = True
                except (AuthError, DirectoryUnavailable):
                    pass
            return self._from_record(record, token, superadmin=is_super)
        except AuthError as user_err:
            # Connexion directe avec un compte superadmin de PocketBase (_superusers)
            try:
                su_data = pb_request(self.settings, f"{SUPERUSERS_COLLECTION}/auth-with-password",
                                     {"identity": identity, "password": password})
            except (AuthError, DirectoryUnavailable):
                raise user_err
            su_record = su_data.get("record") or {}
            su_token = su_data.get("token") or ""
            if not su_record.get("id") or not su_token:
                raise user_err
            profile_record = self._find_or_create_superuser_profile(su_record, su_token, password=password)
            return self._from_record(profile_record, su_token, superadmin=True)

    def refresh(self, token: str) -> User:
        if not token:
            raise AuthError("Jeton de compte manquant.")
        try:
            return self._user(self._post("auth-refresh", token=token))
        except AuthError as user_err:
            try:
                su_data = pb_request(self.settings, f"{SUPERUSERS_COLLECTION}/auth-refresh", token=token)
            except (AuthError, DirectoryUnavailable):
                raise user_err
            su_record = su_data.get("record") or {}
            su_token = su_data.get("token") or ""
            if not su_record.get("id") or not su_token:
                raise user_err
            profile_record = self._find_or_create_superuser_profile(su_record, su_token)
            return self._from_record(profile_record, su_token, superadmin=True)

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
        return self._from_record(record, user.token, superadmin=user.superadmin)

    def _require_superadmin(self, admin: User):
        if not admin or not admin.superadmin or not admin.token:
            raise AuthError("Action réservée aux superadministrateurs référencés sur PocketBase.")

    def _format_user_item(self, record: dict, super_emails: set[str]) -> dict:
        email = str(record.get("email") or "").strip()
        is_super = bool(record.get("superadmin")) or (email.lower() in super_emails if email else False)
        default_name = email.split("@")[0].replace(".", " ").title() if email else record.get("id", "")
        role = str(record.get("role") or self.settings.AUTH_DEFAULT_ROLE).strip().lower()
        if is_super and role not in (self.settings.AUTH_ADMIN_ROLES or ["admin"]):
            role = (self.settings.AUTH_ADMIN_ROLES or ["admin"])[0]
        return {
            "id": str(record.get("id") or ""),
            "name": str(record.get("name") or default_name),
            "email": email,
            "role": role,
            "superadmin": is_super,
            "voice": str(record.get("voice") or ""),
            "created": str(record.get("created") or ""),
        }

    def list_users(self, admin: User) -> list[dict]:
        self._require_superadmin(admin)
        super_emails = self._db_superuser_emails()
        try:
            su_res = pb_request(self.settings, f"{SUPERUSERS_COLLECTION}/records", token=admin.token,
                                method="GET", query={"perPage": 200})
            for item in su_res.get("items") or []:
                if item.get("email"):
                    super_emails.add(str(item["email"]).strip().lower())
        except (AuthError, DirectoryUnavailable):
            pass
        data = self._post("records", token=admin.token, method="GET", query={"perPage": 200, "sort": "-created"})
        items = [self._format_user_item(r, super_emails) for r in (data.get("items") or []) if r.get("id")]
        seen_emails = {u["email"].lower() for u in items if u.get("email")}
        for su_email in sorted(super_emails):
            if su_email not in seen_emails:
                items.insert(0, {
                    "id": f"su:{su_email}",
                    "name": su_email.split("@")[0].replace(".", " ").title(),
                    "email": su_email,
                    "role": (self.settings.AUTH_ADMIN_ROLES or ["admin"])[0],
                    "superadmin": True,
                    "voice": "",
                    "created": "",
                })
        return items

    def create_user(self, admin: User, email: str, password: str, name: str = "", role: str = "member") -> dict:
        self._require_superadmin(admin)
        email = str(email or "").strip()
        password = str(password or "")
        role = str(role or self.settings.AUTH_DEFAULT_ROLE).strip().lower()
        if not email or "@" not in email:
            raise ValueError("Adresse e-mail valide requise.")
        if len(password) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
        if role not in ("admin", "member", "guest"):
            raise ValueError("Rôle invalide (attendu : admin, member ou guest).")
        clean_name = " ".join(str(name or "").split())[:80] or email.split("@")[0].replace(".", " ").title()
        record = self._post("records", {
            "email": email,
            "emailVisibility": True,
            "password": password,
            "passwordConfirm": password,
            "name": clean_name,
            "role": role,
            "verified": True,
        }, token=admin.token, method="POST")
        return self._format_user_item(record, self._db_superuser_emails())

    def update_user_role(self, admin: User, record_id: str, role: str, name: Optional[str] = None) -> dict:
        self._require_superadmin(admin)
        record_id = str(record_id or "").strip().removeprefix("pb_")
        role = str(role or "").strip().lower()
        if not record_id or record_id.startswith("su:"):
            raise ValueError("Ce compte superadmin système ne peut être modifié que depuis PocketBase (/_/).")
        if role not in ("admin", "member", "guest"):
            raise ValueError("Rôle invalide (attendu : admin, member ou guest).")
        body: dict = {"role": role}
        if name is not None and str(name).strip():
            body["name"] = " ".join(str(name).split())[:80]
        safe_id = urllib.parse.quote(record_id, safe="")
        record = self._post(f"records/{safe_id}", body, token=admin.token, method="PATCH", not_found_is_refusal=True)
        return self._format_user_item(record, self._db_superuser_emails())

    def delete_user(self, admin: User, record_id: str) -> bool:
        self._require_superadmin(admin)
        record_id = str(record_id or "").strip().removeprefix("pb_")
        if not record_id or record_id.startswith("su:"):
            raise ValueError("Impossible de supprimer un superadmin système depuis cette vue.")
        if admin.id == f"pb_{record_id}":
            raise ValueError("Vous ne pouvez pas supprimer votre propre compte en cours de session.")
        safe_id = urllib.parse.quote(record_id, safe="")
        self._post(f"records/{safe_id}", token=admin.token, method="DELETE", not_found_is_refusal=True)
        return True


def BooleanSuper(val) -> bool:
    return bool(val)


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
