"""
Module d'action pour le lancement d'applications installées.
Contient les métadonnées et le script bash multi-environnements embarqué.
"""

from typing import List, Tuple
from actions.base import BaseAction
from core.config import get_settings

# Catégories reconnues par le `case` du script bash ci-dessous (à garder synchronisé)
_CATEGORY_KEYWORDS = {
    "navigateur", "browser", "web", "navigateur web", "google chrome", "chrome",
    "musique", "music", "audio",
    "code", "vscode", "visual studio code", "editeur", "editor",
    "terminal", "console",
    "fichiers", "explorateur", "files", "explorer", "gestionnaire de fichiers",
    "calculatrice", "calc", "calculator",
    "parametres", "settings", "paramètres",
}

# Catégories proposées aux modèles de décision (une seule entrée par catégorie du script)
_DECISION_CATEGORIES = {
    "navigateur": "le navigateur web", "musique": "le lecteur de musique", "code": "l'éditeur de code",
    "terminal": "le terminal", "fichiers": "le gestionnaire de fichiers", "calculatrice": "la calculatrice",
    "paramètres": "les paramètres",
}

_OPEN_APP_SCRIPT = r"""
APP_NAME="$*"

if [ -z "$APP_NAME" ]; then
    echo "Usage : open_app.sh <nom_application>" >&2
    exit 1
fi

# Normalisation du nom (minuscules, suppression des espaces superflus)
APP_LOWER=$(echo "$APP_NAME" | tr '[:upper:]' '[:lower:]' | xargs)

# Fonction pour tenter de lancer un binaire ou une commande
try_launch() {
    local cmd="$1"

    # 1. Tentative gtk-launch
    if command -v gtk-launch >/dev/null 2>&1 && gtk-launch "$cmd" 2>/dev/null; then
        return 0
    fi

    # 2. Tentative kstart / kstart5
    if command -v kstart5 >/dev/null 2>&1 && command -v "$cmd" >/dev/null 2>&1; then
        kstart5 "$cmd" >/dev/null 2>&1 &
        return 0
    fi
    if command -v kstart >/dev/null 2>&1 && command -v "$cmd" >/dev/null 2>&1; then
        kstart "$cmd" >/dev/null 2>&1 &
        return 0
    fi

    # 3. Tentative binaire direct en arrière-plan
    if command -v "$cmd" >/dev/null 2>&1; then
        nohup "$cmd" >/dev/null 2>&1 &
        return 0
    fi

    return 1
}

# Mapping et cascade de candidats selon l'intention
case "$APP_LOWER" in
    navigateur|browser|web|"navigateur web"|"google chrome"|chrome)
        CANDIDATES=("google-chrome" "firefox" "chromium" "brave-browser" "microsoft-edge")
        ;;
    musique|music|audio)
        CANDIDATES=("spotify" "elisa" "rhythmbox" "vlc" "clementine" "strawberry")
        ;;
    code|vscode|"visual studio code"|editeur|editor)
        CANDIDATES=("code" "vscodium" "kate" "gedit" "kwrite" "mousepad")
        ;;
    terminal|console)
        CANDIDATES=("${TERMINAL:-}" "konsole" "gnome-terminal" "xfce4-terminal" "kitty" "alacritty" "xterm")
        ;;
    fichiers|explorateur|files|explorer|"gestionnaire de fichiers")
        CANDIDATES=("dolphin" "nautilus" "thunar" "nemo" "pcmanfm")
        ;;
    calculatrice|calc|calculator)
        CANDIDATES=("kcalc" "gnome-calculator" "galculator" "xcalc")
        ;;
    parametres|settings|"paramètres")
        CANDIDATES=("systemsettings" "gnome-control-center" "xfce4-settings-manager")
        ;;
    *)
        CANDIDATES=("$APP_LOWER")
        ;;
esac

for candidate in "${CANDIDATES[@]}"; do
    [ -z "$candidate" ] && continue
    if try_launch "$candidate"; then
        exit 0
    fi
done

echo "Erreur : Impossible de trouver ou lancer l'application '$APP_NAME'." >&2
exit 1
"""


class OpenAppAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="OPEN",
            done_message="J'ouvre ${ARGS}.",
            description="Lancer une application installée (ex: firefox, spotify, code, calculatrice).",
            script_code=_OPEN_APP_SCRIPT,
            has_args=True,
            args_hint="<application>",
            example_prompt="Ouvre Firefox.",
            example_response="[OPEN firefox] J'ouvre Firefox."
        )

    def decision_choices(self):
        allowed = get_settings().ACTIONS_OPEN_ALLOWED_APPS
        return {**_DECISION_CATEGORIES, **{app: app for app in allowed}}

    def build_args(self, args: str = "") -> List[str]:
        app = (args or "").strip()
        normalized = " ".join(app.lower().split())
        if not normalized:
            return []
        # Liste blanche : empêche le LLM de lancer un binaire arbitraire du PATH (ex: [OPEN poweroff])
        if normalized not in _CATEGORY_KEYWORDS and normalized not in get_settings().ACTIONS_OPEN_ALLOWED_APPS:
            print(f"⛔ [ACTIONS] Application non autorisée pour [OPEN] : '{app}' (voir ACTIONS_OPEN_ALLOWED_APPS)")
            return []
        return [app]

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        cmd_args = self.build_args(args)
        if not cmd_args:
            return 1, "", f"Application non autorisée ou invalide : '{args}'"
        app = cmd_args[0].lower().strip()
        app_map = {
            "navigateur": "chrome", "browser": "chrome", "chrome": "chrome", "google chrome": "chrome",
            "edge": "msedge", "code": "code", "vscode": "code",
            "terminal": "wt", "console": "powershell",
            "fichiers": "explorer", "explorateur": "explorer", "files": "explorer",
            "calculatrice": "calc", "calc": "calc",
            "musique": "spotify",
            "paramètres": "ms-settings:", "parametres": "ms-settings:", "settings": "ms-settings:",
        }
        target = app_map.get(app, app)
        try:
            print(f"🚀 [ACTIONS] [Windows] Lancement de l'application '{target}'...")
            if target.startswith("ms-settings:"):
                import os
                os.startfile(target)
            else:
                import subprocess
                subprocess.Popen(["cmd", "/c", "start", "", target])
            print(f"✅ [ACTIONS] [Windows] Application '{target}' lancée.")
            return 0, f"Application {app} lancée", ""
        except Exception as e:
            print(f"❌ [ACTIONS] [Windows] Erreur ouverture {target} : {e}")
            return -1, "", str(e)

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            return True
        code, out, err = self.execute_sync_windows(args)
        return code == 0


ACTIONS = [OpenAppAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/open_app.py")
    code, out, err = ACTIONS[0].execute_sync("non_existing_app")
    print(f"Code : {code} | Erreur attendue : {err.strip()}")
