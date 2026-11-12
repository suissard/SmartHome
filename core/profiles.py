"""
Profils de configuration de SmartHome (dossier `profiles/`).

Un profil est un fichier `profiles/<nom>.env` qui ne contient que les réglages propres à une
architecture (fournisseurs, modèles). Ordre de priorité des valeurs :
profil / réglages utilisateur > variables de la machine (os.environ) > valeurs par défaut.
Les secrets (OPENROUTER_API_KEY, jetons) restent dans `.env`.
Un réglage du profil modifié depuis l'interface web va dans `profiles/<nom>.local.env` (non versionné),
qui complète le profil sans modifier le fichier livré.

Choix du profil : `python main.py --profile local-lfm`, variable `SMARTHOME_PROFILE`, ou menu
au démarrage de `./start.sh` (`--no-menu` pour le passer, `--setup` pour l'assistant pas à pas de core/wizard.py). Sans choix, le dernier profil choisi
dans le menu s'applique (`profiles/.last`, non versionné), sinon le profil par défaut (`mix`).
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from core.menu import Option, answered, choose

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
_DEFAULT_PROFILES_DIR = PROFILES_DIR
DEFAULT_PROFILE = "hybrid"
PROFILE_ENV_VAR = "SMARTHOME_PROFILE"
LAST_PROFILE_FILE = ".last"


def user_profiles_dir() -> Path:
    """Dossier des profils modifiables par l'utilisateur (`perso.env`, `*.local.env`, `.last`).
    Utilise `~/.config/smarthome/profiles` par défaut, sauf si `PROFILES_DIR` a été redirigé (tests)
    ou si un `.env` local existe déjà à la racine du projet (rétrocompatibilité)."""
    if PROFILES_DIR != _DEFAULT_PROFILES_DIR or (BASE_DIR / ".env").is_file():
        return PROFILES_DIR
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "smarthome" / "profiles"


def list_profiles() -> list[str]:
    """Noms des profils disponibles (défaut en premier, puis ordre alphabétique)."""
    dirs = [PROFILES_DIR]
    user_dir = user_profiles_dir()
    if user_dir != PROFILES_DIR and user_dir.is_dir():
        dirs.append(user_dir)
    found = {
        p.stem
        for d in dirs
        for p in d.glob("*.env")
        if not p.stem.endswith(".local")
    }
    return sorted(found, key=lambda n: (n != DEFAULT_PROFILE, n))


def profile_path(name: str) -> Path:
    user_path = user_profiles_dir() / f"{name}.env"
    if user_path.is_file():
        return user_path
    path = PROFILES_DIR / f"{name}.env"
    if path.is_file():
        return path
    raise SystemExit(f"❌ [CONFIG] Profil inconnu : {name!r} (disponibles : {', '.join(list_profiles())})")


def describe_profile(name: str) -> str:
    """Première ligne de commentaire du profil (« # Titre : description »)."""
    for line in profile_path(name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def _last_profile_file() -> Optional[Path]:
    for directory in dict.fromkeys((user_profiles_dir(), PROFILES_DIR)):
        candidate = directory / LAST_PROFILE_FILE
        if candidate.is_file():
            return candidate
    return None


def has_saved_profile() -> bool:
    """Indique si l'utilisateur a déjà mémorisé un profil de démarrage."""
    return _last_profile_file() is not None


def last_profile() -> str:
    """Dernier profil choisi dans le menu (profil par défaut s'il n'y en a pas ou s'il n'existe plus)."""
    marker = _last_profile_file()
    if marker is None:
        return DEFAULT_PROFILE
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PROFILE
    return name if name in list_profiles() else DEFAULT_PROFILE


def remember_profile(name: str):
    target_dir = user_profiles_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / LAST_PROFILE_FILE).write_text(f"{name}\n", encoding="utf-8")


def active_profile() -> str:
    return (os.environ.get(PROFILE_ENV_VAR) or "").strip() or last_profile()


def local_overrides_path(name: Optional[str] = None) -> Path:
    """Fichier non versionné des réglages du profil modifiés depuis l'interface web ou la CLI."""
    return user_profiles_dir() / f"{name or active_profile()}.local.env"


def profile_values(name: Optional[str] = None) -> dict[str, str]:
    """Réglages du profil (actif par défaut) et de sa surcharge locale, sans interpolation de variables."""
    target = name or active_profile()
    values = dict(dotenv_values(profile_path(target), interpolate=False))
    if user_profiles_dir() != PROFILES_DIR:
        legacy_local = PROFILES_DIR / f"{target}.local.env"
        if legacy_local.is_file():
            values.update(dotenv_values(legacy_local, interpolate=False))
    local = local_overrides_path(target)
    if local.is_file():
        values.update(dotenv_values(local, interpolate=False))
    return {k: v for k, v in values.items() if v is not None}


def shadowed_by_environment(name: Optional[str] = None) -> dict[str, str]:
    """Réglages du profil masqués par une variable d'environnement (vide : le profil supplante la machine)."""
    return {}


def warn_shadowed_profile():
    shadowed = shadowed_by_environment()
    if shadowed:
        print(f"⚠️ [CONFIG] Le profil {active_profile()!r} est masqué par des variables d'environnement : {', '.join(shadowed)}.")
        print(f"   Elles viennent du terminal (ex: `source .env`) : ouvrez un nouveau terminal ou `unset {' '.join(shadowed)}`.")


def pop_profile_argument(argv: list[str]) -> Optional[str]:
    """Retire `--profile <nom>` / `--profile=<nom>` de argv et le place dans SMARTHOME_PROFILE."""
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            name = argv[i + 1]
            del argv[i:i + 2]
        elif arg.startswith("--profile="):
            name = arg.split("=", 1)[1]
            del argv[i]
        else:
            continue
        profile_path(name)
        os.environ[PROFILE_ENV_VAR] = name
        return name
    return None


def choose_profile(setup: bool = False) -> str:
    """Menu de démarrage, positionné sur le dernier profil (sur l'assistant de configuration au premier lancement).
    Mémorise et retourne le nom du profil. `setup` ouvre directement l'assistant."""
    while True:
        name = _run_setup() if setup else _pick_from_menu()
        setup = False  # assistant annulé : retour au menu
        if name:
            remember_profile(name)
            answered("Profil", name)
            return name


def _pick_from_menu() -> Optional[str]:
    names, last = list_profiles(), last_profile()
    first_launch = not has_saved_profile()
    options = [Option("Configurer pas à pas", None, "Quelques questions pour créer votre configuration")]
    for name in names:
        options.append(Option(name, name, describe_profile(name).split(" : ", 1)[-1],
                              "" if first_launch or name != last else "dernier choix"))
    picked = choose("SmartHome · choix du profil", options, 0 if first_launch else names.index(last) + 1)
    return picked.value or _run_setup()


def _run_setup() -> Optional[str]:
    from core.wizard import run_wizard
    return run_wizard()


if __name__ == "__main__":
    print(f"🧪 [DEBUG] Profils disponibles (actif : {active_profile()}) :")
    for n in list_profiles():
        print(f"  • {n:<14} {describe_profile(n)}")
