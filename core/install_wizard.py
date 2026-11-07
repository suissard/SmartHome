"""
Assistant d'installation pas à pas (`./install.sh`, `install.ps1` dans un terminal interactif).

Il tourne AVANT la création du venv, avec le Python du système : bibliothèque standard uniquement.
`core/menu.py` est chargé par son chemin (importer le paquet `core` chargerait pydantic via core/config.py).

Chaque étape pose une question seulement si elle a un sens (ex : l'emplacement d'Ollama n'est demandé que si
le profil choisi s'en sert). Les questions s'affichent sur stderr ; le plan d'installation est écrit sur stdout,
une ligne `CLÉ=valeur` par réglage, lu par le script d'installation :

    MODE=desktop|server          SYSTEM_DEPS=all|base|none     OLLAMA=install|use|remote|none
    OLLAMA_HOST=<url>            OLLAMA_PULL=<modèles,séparés> DOWNLOAD_MODELS=true|false
    WITH_SERVICE=true|false      GATEWAY_BIND=<adresse>        PROFILE=<nom ou vide>
    ACCOUNTS=true|false          (comptes utilisateurs de la PWA avec PocketBase)

Code de sortie : 0 plan validé, 1 installation annulée, 130 interruption (q / Ctrl+C).
"""

import argparse
import importlib.util
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT_DIR / "profiles"
DEFAULT_PROFILE = "hybrid"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def _load_menu():
    spec = importlib.util.spec_from_file_location("smarthome_menu", Path(__file__).resolve().parent / "menu.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


menu = _load_menu()
GoBack, Option, answered, ask_text, choose, note, style = (
    menu.GoBack, menu.Option, menu.answered, menu.ask_text, menu.choose, menu.note, menu.style)

# Modèles Ollama proposés quand le profil sera choisi plus tard (ceux des profils livrés)
OLLAMA_SUGGESTIONS = [
    ("lfm3-audio", "Léger : écoute, réfléchit et parle (profils mix, local-lfm)"),
    ("gemma4:12b", "Grosse machine : comprend l'audio et réfléchit (profil local-gemma)"),
    ("nimble", "Modèle de décision : choisit une commande, réponses types (profil local-decision)"),
]

# Outils utilisés par les actions du poste : commande testée → rôle
DESKTOP_TOOLS = {
    "pactl": "volume et ducking",
    "aplay": "lecture audio ALSA",
    "notify-send": "notifications",
    "playerctl": "médias",
    "brightnessctl": "luminosité",
}


# ---- Lecture de la configuration (sans python-dotenv) ----
def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def list_profiles() -> list[str]:
    names = sorted(p.stem for p in PROFILES_DIR.glob("*.env") if not p.stem.endswith(".local"))
    return sorted(names, key=lambda n: (n != DEFAULT_PROFILE, n))


def describe_profile(name: str) -> str:
    try:
        for line in (PROFILES_DIR / f"{name}.env").read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                return line.lstrip("# ").strip().split(" : ", 1)[-1]
    except OSError:
        pass
    return ""


def last_profile() -> Optional[str]:
    try:
        name = (PROFILES_DIR / ".last").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name if name in list_profiles() else None


def effective_values(profile: Optional[str]) -> dict[str, str]:
    """Même ordre de priorité que core/config.py (hors variables d'environnement) : profil > .env > .env.example."""
    values = read_env_file(ROOT_DIR / ".env.example")
    values.update(read_env_file(ROOT_DIR / ".env"))
    if profile:
        values.update(read_env_file(PROFILES_DIR / f"{profile}.env"))
        values.update(read_env_file(PROFILES_DIR / f"{profile}.local.env"))
    return values


def profile_needs(values: dict[str, str]) -> dict:
    """Logiciels et modèles qu'une configuration demande."""
    llm = values.get("LLM_PROVIDER", "ollama").lower()
    stt = values.get("STT_PROVIDER", "whisper").lower()
    fallback = values.get("STT_FALLBACK_PROVIDER", "whisper").lower()
    tts = values.get("TTS_PROVIDER", "piper").lower()
    direct = stt in ("direct", "none", "bypass")
    pull = []
    if llm == "ollama":
        pull.append(values.get("OLLAMA_MODEL", ""))
    if stt == "ollama" or (direct and fallback == "ollama"):
        pull.append(values.get("OLLAMA_STT_MODEL", ""))
    if tts == "ollama":
        pull.append(values.get("OLLAMA_TTS_MODEL", ""))
    pull = list(dict.fromkeys(m for m in pull if m))
    return {
        "ollama": bool(pull),
        "ollama_models": pull,
        "whisper": stt == "whisper" or (direct and fallback == "whisper"),
        "whisper_model": values.get("WHISPER_MODEL", "base"),
        "piper": tts == "piper",
        "openrouter": "openrouter" in (llm, stt, tts) or (direct and fallback == "openrouter"),
    }


def ollama_reachable(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


class InstallWizard:
    STEPS = ["step_mode", "step_profile", "step_ollama", "step_ollama_models", "step_packages",
             "step_models", "step_host", "step_accounts", "step_service"]

    def __init__(self, args):
        self.args = args
        self.platform = args.platform
        self.mode = args.mode
        self.profile: Optional[str] = None
        self.needs: dict = profile_needs(effective_values(None))
        self.values: dict[str, str] = {}
        self.ollama = "none"
        self.ollama_host = effective_values(None).get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
        self.ollama_pull: list[str] = []
        self.system_deps = "none"
        self.download_models = False
        self.service = args.service
        self.gateway_bind = args.host
        self.accounts = effective_values(None).get("AUTH_PROVIDER", "none").lower() in ("pocketbase", "pb")
        self.summary: dict[str, str] = {}

    # ---- Étapes applicables ----
    def applies(self, step: str) -> bool:
        if step == "step_ollama":
            return self.args.ollama
        if step == "step_ollama_models":
            return self.args.ollama and self.ollama != "none" and self.profile is None
        if step == "step_packages":
            return self.args.system_deps and self.platform != "windows"
        if step == "step_models":
            return self.args.models
        if step == "step_host":
            return self.mode == "server"
        if step == "step_accounts":
            return self.args.accounts
        if step == "step_service":
            return self.platform != "darwin"
        return True

    def title(self, step: str, text: str) -> str:
        active = [s for s in self.STEPS if self.applies(s)]
        return f"Installation · étape {active.index(step) + 1}/{len(active)} · {text}"

    def ask(self, step: str, text: str, options: list, index: int = 0):
        first = next(s for s in self.STEPS if self.applies(s))
        return choose(self.title(step, text), options, index, can_go_back=step != first)

    # ---- Étapes ----
    def step_mode(self):
        self.mode = self.ask("step_mode", "Sur quel type de machine installez-vous SmartHome ?", [
            Option("Poste vocal", "desktop", "Micro et haut-parleur : l'assistant écoute le mot-clé et répond à voix haute"),
            Option("Serveur sans micro", "server", "Passerelle réseau seule : téléphones et navigateurs s'y connectent"),
        ], 0 if self.mode == "desktop" else 1).value
        answered("Machine", "poste vocal" if self.mode == "desktop" else "serveur sans micro")
        self.summary["Machine"] = "poste vocal" if self.mode == "desktop" else "serveur sans micro"

    def step_profile(self):
        names, last = list_profiles(), last_profile()
        options = []
        for name in names:
            needs = profile_needs(effective_values(name))
            parts = []
            if needs["ollama"]:
                parts.append("Ollama : " + ", ".join(needs["ollama_models"]))
            if needs["openrouter"]:
                parts.append("clé OpenRouter")
            if needs["whisper"]:
                parts.append("Whisper")
            if needs["piper"]:
                parts.append("Piper")
            tag = "déjà choisi" if name == last else ""
            options.append(Option(name, name, describe_profile(name) + (f"  [{' + '.join(parts)}]" if parts else ""), tag))
        options.append(Option("Je choisirai plus tard", None, "Menu de ./start.sh (ou ./start.sh --setup)"))
        index = names.index(last) if last else 0
        option = self.ask("step_profile", "Quelle architecture voulez-vous utiliser ?", options, index)
        self.profile = option.value
        self.needs = profile_needs(effective_values(self.profile))
        answered("Profil", self.profile or "plus tard")
        self.summary["Profil"] = self.profile or "choisi au premier lancement"

    def step_ollama(self):
        host = self.ollama_host
        installed = shutil.which("ollama") is not None
        running = ollama_reachable(host)
        state = "en marche" if running else ("installé, arrêté" if installed else "absent")
        needed = self.needs["ollama"] or self.profile is None
        why = (f"Le profil {self.profile} en a besoin ({', '.join(self.needs['ollama_models'])})" if self.profile
               else "Utilisé par la plupart des profils (modèles locaux)")
        if installed or running:
            options = [Option("Utiliser l'Ollama de cette machine", "use", f"{host} · {state}"),
                       Option("Ollama tourne sur une autre machine", "remote", "Je donne son adresse"),
                       Option("Ne pas utiliser Ollama", "none")]
            index = 0 if needed else 2
        elif needed:
            options = [Option("Installer Ollama", "install", why),
                       Option("Ollama tourne sur une autre machine", "remote", "Je donne son adresse"),
                       Option("Ne pas installer Ollama", "none", "Le profil ne fonctionnera pas sans lui")]
            index = 0
        else:
            options = [Option("Ne pas installer Ollama", "none", f"Le profil {self.profile} n'en a pas besoin"),
                       Option("Installer Ollama quand même", "install", "Pour essayer des modèles locaux plus tard"),
                       Option("Ollama tourne sur une autre machine", "remote", "Je donne son adresse")]
            index = 0
        self.ollama = self.ask("step_ollama", f"Ollama (modèles d'IA locaux) · {state}", options, index).value
        if self.ollama == "remote":
            url = ask_text(f"Adresse d'Ollama [{host}]") or host
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            if ":" not in url.split("//", 1)[1]:
                url += ":11434"
            self.ollama_host = url.rstrip("/")
            if not ollama_reachable(self.ollama_host):
                note(f"{self.ollama_host} ne répond pas pour l'instant : l'adresse est tout de même retenue.")
        self.ollama_pull = list(self.needs["ollama_models"]) if self.ollama != "none" and self.profile else []
        label = {"install": "à installer", "use": "déjà là", "remote": self.ollama_host, "none": "non"}[self.ollama]
        answered("Ollama", label)
        self.summary["Ollama"] = label

    def step_ollama_models(self):
        options = [Option(name, [name], detail) for name, detail in OLLAMA_SUGGESTIONS]
        options.append(Option("Aucun pour l'instant", [], "ollama pull <modèle> plus tard"))
        self.ollama_pull = self.ask("step_ollama_models", "Quel modèle Ollama préparer ?", options).value
        answered("Modèle Ollama", ", ".join(self.ollama_pull) or "aucun")

    def step_packages(self):
        manager = self.args.pkg_manager or "inconnu"
        if self.platform == "darwin":
            options = [Option("Oui", "base", "Homebrew : python, portaudio, libsndfile"),
                       Option("Non, je les gère moi-même", "none")]
        elif not self.args.pkg_manager:
            note("Gestionnaire de paquets non reconnu : installez Python ≥ 3.10, PortAudio (dev) et libsndfile.")
            self.system_deps = "none"
            return
        else:
            missing = [f"{cmd} ({role})" for cmd, role in DESKTOP_TOOLS.items() if shutil.which(cmd) is None]
            options = []
            if self.mode == "desktop":
                options.append(Option("Tout installer", "all", "Base + outils des actions : "
                                      + (", ".join(missing) + " manquant(s)" if missing else "déjà présents")))
            options += [Option("Base seulement", "base", "Python, compilation de PyAudio (PortAudio), libsndfile, curl"),
                        Option("Rien, je les gère moi-même", "none", "Aucune commande sudo")]
        option = self.ask("step_packages", f"Paquets système ({manager}, droits sudo) ?", options)
        self.system_deps = option.value
        answered("Paquets système", option.label.lower())
        self.summary["Paquets système"] = f"{option.label.lower()} ({manager})"

    def step_models(self):
        items = []
        if self.mode == "desktop":
            items.append("openWakeWord (mot-clé)")
        if self.needs["whisper"]:
            items.append(f"Whisper {self.needs['whisper_model']}")
        if self.ollama_pull and self.ollama != "none":
            items.append("Ollama : " + ", ".join(self.ollama_pull))
        if not items:
            self.download_models = False
            return
        self.download_models = self.ask("step_models", "Télécharger les modèles maintenant ?", [
            Option("Oui", True, " · ".join(items)),
            Option("Non, plus tard", False, "Ils seront téléchargés au premier lancement (premier démarrage plus long)"),
        ]).value
        answered("Modèles", "maintenant" if self.download_models else "plus tard")
        self.summary["Modèles"] = " · ".join(items) if self.download_models else "plus tard"

    def step_host(self):
        options = [Option("Tout le réseau", "0.0.0.0", "Accessible depuis les autres appareils (protégé par jeton)"),
                   Option("Cette machine seulement", "127.0.0.1", "Derrière un proxy ou Tailscale Serve")]
        if self.gateway_bind not in ("", "0.0.0.0", "127.0.0.1"):
            options.insert(0, Option(self.gateway_bind, self.gateway_bind, "Adresse passée en option"))
        option = self.ask("step_host", "Sur quelle adresse la passerelle doit-elle écouter ?", options)
        self.gateway_bind = option.value
        answered("Écoute", self.gateway_bind)
        self.summary["Écoute de la passerelle"] = self.gateway_bind

    def step_accounts(self):
        self.accounts = self.ask("step_accounts", "Comptes utilisateurs pour l'interface web (téléphones, navigateurs) ?", [
            Option("Non, un seul jeton", False, "Comme avant : le jeton de la passerelle (QR code) donne l'accès complet"),
            Option("Oui, un compte par personne", True,
                   "PocketBase (téléchargé et lancé par SmartHome) : rôles admin / membre / invité"),
        ], 1 if self.accounts else 0).value
        answered("Comptes", "un par personne (PocketBase)" if self.accounts else "jeton unique")
        self.summary["Comptes"] = "un par personne (PocketBase)" if self.accounts else "jeton unique"

    def step_service(self):
        how = {"windows": "Tâche planifiée à l'ouverture de session",
               "linux": "Service systemd " + ("système" if self.mode == "server" else "utilisateur")}[self.platform]
        self.service = self.ask("step_service", "Démarrer SmartHome automatiquement ?", [
            Option("Non", False, "Lancement à la main : ./start.sh"), Option("Oui", True, how),
        ], 1 if self.service else 0).value
        answered("Démarrage automatique", "oui" if self.service else "non")
        self.summary["Démarrage automatique"] = "oui" if self.service else "non"

    # ---- Déroulement ----
    def run(self) -> bool:
        while True:
            self.summary = {}
            step = 0
            while step < len(self.STEPS):
                name = self.STEPS[step]
                if not self.applies(name):
                    step += 1
                    continue
                try:
                    getattr(self, name)()
                    step += 1
                except GoBack:
                    step -= 1
                    while step > 0 and not self.applies(self.STEPS[step]):
                        step -= 1
                    step = max(step, 0)
            self.print_summary()
            answer = choose("Tout est prêt", [
                Option("Lancer l'installation", "go"), Option("Recommencer", "again"), Option("Annuler", "cancel"),
            ]).value
            if answer == "go":
                return True
            if answer == "cancel":
                return False

    def print_summary(self):
        print("", file=sys.stderr)
        for label, value in self.summary.items():
            print(f"    {style('2', label + ' :')} {value}", file=sys.stderr)
        if self.profile and self.needs["openrouter"] and not effective_values(None).get("OPENROUTER_API_KEY"):
            note("Ce profil demande une clé OpenRouter : OPENROUTER_API_KEY dans .env, ou ./start.sh --setup.")
        if self.profile and self.needs["ollama"] and self.ollama == "none":
            note("Sans Ollama, ce profil ne pourra pas fonctionner.")

    def plan(self) -> dict[str, str]:
        return {
            "MODE": self.mode,
            "SYSTEM_DEPS": self.system_deps if self.applies("step_packages") else "none",
            "OLLAMA": self.ollama if self.args.ollama else "none",
            "OLLAMA_HOST": self.ollama_host if self.ollama == "remote" else "",
            "OLLAMA_PULL": ",".join(self.ollama_pull) if self.ollama != "none" else "",
            "DOWNLOAD_MODELS": "true" if self.download_models and self.args.models else "false",
            "WITH_SERVICE": "true" if self.service and self.applies("step_service") else "false",
            "GATEWAY_BIND": self.gateway_bind if self.mode == "server" else "",
            "PROFILE": self.profile or "",
            "ACCOUNTS": ("true" if self.accounts else "false") if self.args.accounts else "",
        }


def parse_args(argv=None):
    def flag(value: str) -> bool:
        return value.lower() in ("1", "true", "yes", "oui")

    parser = argparse.ArgumentParser(description="Assistant d'installation de SmartHome")
    parser.add_argument("--platform", choices=["linux", "darwin", "windows"], required=True)
    parser.add_argument("--mode", choices=["desktop", "server"], default="desktop")
    parser.add_argument("--pkg-manager", default="")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--system-deps", type=flag, default=True)
    parser.add_argument("--ollama", type=flag, default=True)
    parser.add_argument("--models", type=flag, default=True)
    parser.add_argument("--service", type=flag, default=False)
    parser.add_argument("--accounts", type=flag, default=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    wizard = InstallWizard(parse_args(argv))
    if not wizard.run():
        print("  Installation annulée.", file=sys.stderr)
        return 1
    for key, value in wizard.plan().items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
