"""
PocketBase (annuaire des comptes, voir core/users.py) : installation du binaire, compte administrateur et lancement.

    python -m core.pocketbase              État (binaire, version, serveur joignable)
    python -m core.pocketbase install      Télécharge la version POCKETBASE_VERSION (somme de contrôle vérifiée)
    python -m core.pocketbase admin        Crée ou met à jour le compte administrateur de PocketBase
    python -m core.pocketbase serve        Lance PocketBase au premier plan (Ctrl+C pour arrêter)

`ensure_running()` est appelé au démarrage de main.py et de la passerelle : si AUTH_PROVIDER=pocketbase,
que POCKETBASE_URL désigne cette machine et que rien n'y répond, SmartHome lance le binaire du projet
(données dans pocketbase/pb_data, migrations dans pocketbase/pb_migrations, journal pocketbase/pocketbase.log)
et l'arrête en quittant. Un PocketBase déjà lancé (service, autre terminal, redémarrage de SmartHome) est réutilisé.
"""

import getpass
import hashlib
import io
import platform
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings

PB_DIR = _ROOT_DIR / "pocketbase"
DATA_DIR = PB_DIR / "pb_data"
MIGRATIONS_DIR = PB_DIR / "pb_migrations"
LOG_FILE = PB_DIR / "pocketbase.log"
RELEASES_URL = "https://github.com/pocketbase/pocketbase/releases/download"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
STARTUP_TIMEOUT_SECONDS = 15.0
STOP_TIMEOUT_SECONDS = 5.0

# Architecture de la machine -> suffixe des archives publiées par PocketBase
_ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armv7"}


def binary_path() -> Path:
    return PB_DIR / ("pocketbase.exe" if sys.platform == "win32" else "pocketbase")


def asset_name(version: str) -> str:
    """Nom de l'archive officielle pour ce système (ex: pocketbase_0.40.6_linux_amd64.zip)."""
    system = {"linux": "linux", "darwin": "darwin", "win32": "windows"}.get(sys.platform)
    arch = _ARCHITECTURES.get(platform.machine().lower())
    if not system or not arch:
        raise RuntimeError(f"Pas de binaire PocketBase publié pour {sys.platform}/{platform.machine()}.")
    return f"pocketbase_{version}_{system}_{arch}.zip"


def installed_version() -> Optional[str]:
    if not binary_path().exists():
        return None
    try:
        out = subprocess.run([str(binary_path()), "--version"], capture_output=True, text=True, timeout=10).stdout
        return out.strip().split()[-1].lstrip("v") if out.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "smarthome-installer"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def install(settings: Optional[Settings] = None, force: bool = False) -> Path:
    """Télécharge l'archive officielle de POCKETBASE_VERSION, vérifie sa somme SHA-256 (checksums.txt de la même
    publication) et extrait le binaire dans pocketbase/. Ne fait rien si cette version est déjà installée."""
    s = settings or get_settings()
    version = s.POCKETBASE_VERSION.lstrip("v")
    if not force and installed_version() == version:
        print(f"✅ [POCKETBASE] Version {version} déjà installée ({binary_path()}).")
        return binary_path()

    name = asset_name(version)
    base = f"{RELEASES_URL}/v{version}"
    print(f"⬇️  [POCKETBASE] Téléchargement de {name}...")
    checksums = _download(f"{base}/checksums.txt").decode()
    expected = next((line.split()[0] for line in checksums.splitlines() if line.strip().endswith(name)), None)
    if not expected:
        raise RuntimeError(f"{name} absent de checksums.txt de la version {version}.")
    archive = _download(f"{base}/{name}")
    if hashlib.sha256(archive).hexdigest() != expected:
        raise RuntimeError(f"Somme de contrôle invalide pour {name} : archive refusée.")

    target = binary_path()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        member = next((n for n in zf.namelist() if Path(n).name == target.name), None)
        if member is None:
            raise RuntimeError(f"{target.name} introuvable dans {name}.")
        PB_DIR.mkdir(exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(zf.read(member))
        tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        tmp.replace(target)
    print(f"✅ [POCKETBASE] Version {version} installée : {target}")
    return target


def _base_args() -> list[str]:
    return ["--dir", str(DATA_DIR), "--migrationsDir", str(MIGRATIONS_DIR)]


def create_admin(email: str, password: str):
    """Crée (ou met à jour) le compte administrateur de PocketBase, celui de l'interface http://.../_/."""
    if not binary_path().exists():
        raise RuntimeError("PocketBase n'est pas installé : python -m core.pocketbase install")
    result = subprocess.run([str(binary_path()), "superuser", "upsert", email, password, *_base_args()],
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"code {result.returncode}")


def _address(settings: Settings) -> tuple[str, int]:
    url = urllib.parse.urlsplit(settings.POCKETBASE_URL)
    return url.hostname or "127.0.0.1", url.port or (443 if url.scheme == "https" else 80)


def is_local(settings: Settings) -> bool:
    return _address(settings)[0] in LOCAL_HOSTS


def is_running(settings: Settings, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{settings.POCKETBASE_URL.rstrip('/')}/api/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def serve_command(settings: Settings) -> list[str]:
    host, port = _address(settings)
    host = f"[{host}]" if ":" in host else host
    # Pas de migrations générées depuis l'interface : seules celles du projet (versionnées) s'appliquent
    return [str(binary_path()), "serve", "--http", f"{host}:{port}", "--automigrate=false", *_base_args()]


class PocketBaseProcess:
    """PocketBase lancé par SmartHome : arrêté avec lui."""

    def __init__(self, process: subprocess.Popen, log):
        self.process = process
        self._log = log

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._log.close()


def ensure_running(settings: Optional[Settings] = None) -> Optional[PocketBaseProcess]:
    """Lance PocketBase si SmartHome en a besoin et qu'il ne répond pas. Ne lève jamais : un problème est affiché
    (la passerelle refusera alors les connexions par compte, le jeton maître restant utilisable)."""
    s = settings or get_settings()
    if s.AUTH_PROVIDER not in ("pocketbase", "pb") or not s.POCKETBASE_AUTOSTART:
        return None
    if is_running(s):
        print(f"🗂️  [POCKETBASE] Déjà en marche : {s.POCKETBASE_URL}")
        return None
    if not is_local(s):
        print(f"⚠️ [POCKETBASE] {s.POCKETBASE_URL} ne répond pas (adresse distante : non lancé par SmartHome).")
        return None
    if not binary_path().exists():
        print("⚠️ [POCKETBASE] Binaire absent : python -m core.pocketbase install (ou relancez ./install.sh).")
        return None

    PB_DIR.mkdir(exist_ok=True)
    log = open(LOG_FILE, "ab")
    try:
        process = subprocess.Popen(serve_command(s), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   cwd=str(PB_DIR))
    except OSError as e:
        log.close()
        print(f"⚠️ [POCKETBASE] Lancement impossible : {e}")
        return None
    handle = PocketBaseProcess(process, log)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            handle.stop()
            print(f"⚠️ [POCKETBASE] Arrêté au démarrage (code {process.returncode}) : voir {LOG_FILE}")
            return None
        if is_running(s, timeout=0.5):
            print(f"🗂️  [POCKETBASE] Lancé : {s.POCKETBASE_URL} (administration : {s.POCKETBASE_URL.rstrip('/')}/_/)")
            return handle
        time.sleep(0.2)
    print(f"⚠️ [POCKETBASE] Pas de réponse après {STARTUP_TIMEOUT_SECONDS:.0f} s : voir {LOG_FILE}")
    return handle


def _ask_admin():
    print("Compte administrateur de PocketBase (interface /_/ : comptes du foyer et leurs rôles).")
    email = input("  E-mail : ").strip()
    password = getpass.getpass("  Mot de passe (10 caractères minimum) : ")
    if password != getpass.getpass("  Confirmation : "):
        raise RuntimeError("Les mots de passe ne correspondent pas.")
    create_admin(email, password)
    print(f"✅ [POCKETBASE] Administrateur {email} prêt.")


def main(argv: list[str]) -> int:
    s = get_settings()
    command = argv[0] if argv else "status"
    try:
        if command == "install":
            install(s, force="--force" in argv)
        elif command == "admin":
            _ask_admin()
        elif command == "serve":
            if not binary_path().exists():
                install(s)
            print(f"🗂️  [POCKETBASE] {' '.join(serve_command(s))}")
            return subprocess.call(serve_command(s), cwd=str(PB_DIR))
        elif command == "status":
            print("🧪 [DEBUG] PocketBase")
            print(f"  • Annuaire  : AUTH_PROVIDER={s.AUTH_PROVIDER}")
            print(f"  • Binaire   : {binary_path()} ({installed_version() or 'absent'}, attendu {s.POCKETBASE_VERSION})")
            print(f"  • Adresse   : {s.POCKETBASE_URL} ({'locale' if is_local(s) else 'distante'}, "
                  f"{'répond' if is_running(s) else 'ne répond pas'})")
            print(f"  • Lancement : {'par SmartHome' if s.POCKETBASE_AUTOSTART else 'manuel'}")
        else:
            print(__doc__)
            return 2
    except (RuntimeError, OSError, urllib.error.URLError) as e:
        print(f"❌ [POCKETBASE] {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print()
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
