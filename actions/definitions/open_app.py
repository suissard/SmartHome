"""
Module d'action pour le lancement d'applications installées.
Contient les métadonnées et le script bash multi-environnements embarqué.
"""

from typing import List
from actions.base import BaseAction

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
            description="Lancer une application installée (ex: firefox, spotify, code, calculatrice).",
            script_code=_OPEN_APP_SCRIPT,
            has_args=True,
            args_hint="<application>",
            example_prompt="Ouvre Firefox.",
            example_response="[OPEN firefox] J'ouvre Firefox."
        )

    def build_args(self, args: str = "") -> List[str]:
        app = (args or "").strip()
        return [app] if app else []


ACTIONS = [OpenAppAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/definitions/open_app.py")
    code, out, err = ACTIONS[0].execute_sync("non_existing_app")
    print(f"Code : {code} | Erreur attendue : {err.strip()}")
