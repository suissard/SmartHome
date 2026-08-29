#!/usr/bin/env bash
# Script pour lancer une application de manière détachée pour SmartHome
# Usage : open_app.sh <nom_app> (ex: open_app.sh firefox, open_app.sh musique, open_app.sh terminal)

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

