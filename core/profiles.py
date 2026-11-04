"""
Profils de configuration de SmartHome (dossier `profiles/`).

Un profil est un fichier `profiles/<nom>.env` qui ne contient que les réglages propres à une
architecture (fournisseurs, modèles). Ordre de priorité des valeurs :
variables d'environnement > profil > `.env` > valeurs par défaut.
Les secrets (OPENROUTER_API_KEY, jetons) restent dans `.env`.
Un réglage du profil modifié depuis l'interface web va dans `profiles/<nom>.local.env` (non versionné),
qui complète le profil sans modifier le fichier livré.

Choix du profil : `python main.py --profile local-lfm`, variable `SMARTHOME_PROFILE`, ou menu
au démarrage de `./start.sh` (`--no-menu` pour le passer, `--setup` pour l'assistant pas à pas de core/wizard.py). Sans choix, le dernier profil choisi
dans le menu s'applique (`profiles/.last`, non versionné), sinon le profil par défaut (`mix`).
"""

import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from core.menu import Option, answered, choose

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
DEFAULT_PROFILE = "mix"
PROFILE_ENV_VAR = "SMARTHOME_PROFILE"
LAST_PROFILE_FILE = ".last"


def list_profiles() -> list[str]:
    """Noms des profils disponibles (défaut en premier, puis ordre alphabétique)."""
    names = sorted(p.stem for p in PROFILES_DIR.glob("*.env") if not p.stem.endswith(".local"))
    return sorted(names, key=lambda n: (n != DEFAULT_PROFILE, n))


def profile_path(name: str) -> Path:
    path = PROFILES_DIR / f"{name}.env"
    if not path.is_file():
        raise SystemExit(f"❌ [CONFIG] Profil inconnu : {name!r} (disponibles : {', '.join(list_profiles())})")
    return path


def describe_profile(name: str) -> str:
    """Première ligne de commentaire du profil (« # Titre : description »)."""
    for line in profile_path(name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def last_profile() -> str:
    """Dernier profil choisi dans le menu (profil par défaut s'il n'y en a pas ou s'il n'existe plus)."""
    try:
        name = (PROFILES_DIR / LAST_PROFILE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PROFILE
    return name if name in list_profiles() else DEFAULT_PROFILE


def remember_profile(name: str):
    (PROFILES_DIR / LAST_PROFILE_FILE).write_text(f"{name}\n", encoding="utf-8")


def active_profile() -> str:
    return (os.environ.get(PROFILE_ENV_VAR) or "").strip() or last_profile()


def local_overrides_path(name: Optional[str] = None) -> Path:
    """Fichier non versionné des réglages du profil modifiés depuis l'interface web."""
    return PROFILES_DIR / f"{name or active_profile()}.local.env"


def profile_values(name: Optional[str] = None) -> dict[str, str]:
    """Réglages du profil (actif par défaut) et de sa surcharge locale, sans interpolation de variables."""
    values = dict(dotenv_values(profile_path(name or active_profile()), interpolate=False))
    local = local_overrides_path(name)
    if local.is_file():
        values.update(dotenv_values(local, interpolate=False))
    return {k: v for k, v in values.items() if v is not None}


def shadowed_by_environment(name: Optional[str] = None) -> dict[str, str]:
    """Réglages du profil masqués par une variable d'environnement de valeur différente ({variable: valeur de l'environnement}).
    Typique : un `source .env` dans le terminal, dont les variables exportées l'emportent sur le profil."""
    return {k: os.environ[k] for k, v in profile_values(name).items()
            if (os.environ.get(k) or "").strip() and os.environ[k] != v}


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
    first_launch = not (PROFILES_DIR / LAST_PROFILE_FILE).exists()
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
