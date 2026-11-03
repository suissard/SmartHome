"""
Profils de configuration de SmartHome (dossier `profiles/`).

Un profil est un fichier `profiles/<nom>.env` qui ne contient que les réglages propres à une
architecture (fournisseurs, modèles). Ordre de priorité des valeurs :
variables d'environnement > profil > `.env` > valeurs par défaut.
Les secrets (OPENROUTER_API_KEY, jetons) restent dans `.env`.
Un réglage du profil modifié depuis l'interface web va dans `profiles/<nom>.local.env` (non versionné),
qui complète le profil sans modifier le fichier livré.

Choix du profil : `python main.py --profile local-lfm`, variable `SMARTHOME_PROFILE`, ou menu
au démarrage de `./start.sh`. Sans choix, le profil par défaut (`mix`) s'applique.
"""

import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
DEFAULT_PROFILE = "mix"
PROFILE_ENV_VAR = "SMARTHOME_PROFILE"


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


def active_profile() -> str:
    return (os.environ.get(PROFILE_ENV_VAR) or "").strip() or DEFAULT_PROFILE


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


def choose_profile() -> str:
    """Menu interactif (sur stderr) ; Entrée = profil par défaut. Retourne le nom choisi."""
    names = list_profiles()
    print("\nChoisissez un profil :", file=sys.stderr)
    for i, name in enumerate(names, 1):
        mark = " (défaut)" if name == DEFAULT_PROFILE else ""
        print(f"  {i}. {name}{mark} — {describe_profile(name)}", file=sys.stderr)
    while True:
        answer = input(f"Numéro ou nom [{DEFAULT_PROFILE}] : ").strip()
        if not answer:
            return DEFAULT_PROFILE
        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if answer in names:
            return answer
        print("Choix invalide.", file=sys.stderr)


if __name__ == "__main__":
    # `python -m core.profiles` liste les profils ; `choose` affiche le nom choisi (utilisé par start.sh)
    if len(sys.argv) > 1 and sys.argv[1] == "choose":
        print(choose_profile())
    else:
        print(f"🧪 [DEBUG] Profils disponibles (actif : {active_profile()}) :")
        for n in list_profiles():
            print(f"  • {n:<14} {describe_profile(n)}")
