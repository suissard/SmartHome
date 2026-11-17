#!/usr/bin/env bash
# Arrêt de SmartHome (service systemd ou processus autonome).
#   ./stop.sh             Arrête le service systemd et tout processus SmartHome actif
#   ./stop.sh --disable   Arrête et désactive le démarrage automatique (systemd)
#   ./stop.sh --status    Affiche l'état d'exécution sans arrêter
#   ./stop.sh --restart   Redémarre SmartHome via systemd ou ./start.sh
# Installation Docker (compose.env) : arrête aussi le conteneur ; Ollama en conteneur reste actif (--all pour l'arrêter).
set -eo pipefail

C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_CYAN="\033[1;36m"
C_RESET="\033[0m"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

UNIT="smarthome.service"
# shellcheck source=docker/lib.sh
source "$ROOT_DIR/docker/lib.sh"

DISABLE=false
SHOW_STATUS_ONLY=false
DO_RESTART=false
STOP_ALL=false

for arg in "$@"; do
    case "$arg" in
        --status|-s)
            SHOW_STATUS_ONLY=true
            ;;
        --disable|-d)
            DISABLE=true
            ;;
        --restart|-r)
            DO_RESTART=true
            ;;
        --all|-a)
            STOP_ALL=true
            ;;
        --help|-h)
            echo "Usage : ./stop.sh [options]"
            echo ""
            echo "Options :"
            echo "  (sans option)    Arrête le service systemd et tout processus SmartHome actif"
            echo "  --disable, -d    Arrête et désactive le lancement automatique au démarrage"
            echo "  --restart, -r    Arrête puis relance SmartHome"
            echo "  --status, -s     Affiche l'état actuel (sans rien modifier)"
            echo "  --all, -a        Docker : arrête aussi le conteneur Ollama"
            echo "  --help, -h       Affiche cette aide"
            exit 0
            ;;
        *)
            echo "Option inconnue : $arg (utilisez --help pour voir les options)" >&2
            exit 1
            ;;
    esac
done

is_user_service_active() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet "$UNIT" 2>/dev/null
}

is_system_service_active() {
    command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$UNIT" 2>/dev/null
}

user_service_exists() {
    [[ -f "$HOME/.config/systemd/user/$UNIT" ]] || (command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files "$UNIT" >/dev/null 2>&1)
}

system_service_exists() {
    [[ -f "/etc/systemd/system/$UNIT" ]] || (command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$UNIT" >/dev/null 2>&1)
}

get_local_pids() {
    # Python de SmartHome et PocketBase lancé par lui (comptes utilisateurs), orphelin après un arrêt forcé
    pgrep -f "(${ROOT_DIR}/.venv/bin/python|${ROOT_DIR}/main\.py|${ROOT_DIR}/pocketbase/pocketbase serve)" 2>/dev/null || true
}

# Conteneurs Docker de SmartHome en cours d'exécution (vide sans installation Docker)
DOCKER_OK=false
if docker_mode_installed && docker_init; then
    DOCKER_OK=true
fi
docker_running() {
    $DOCKER_OK && compose ps --status running --services 2>/dev/null | grep -E "^(smarthome|smarthome-server)$" || true
}

if [[ "$SHOW_STATUS_ONLY" == true ]]; then
    echo -e "${C_CYAN}🔍 État de SmartHome :${C_RESET}"
    active=false

    if $DOCKER_OK; then
        running="$(docker_running | xargs)"
        if [[ -n "$running" ]]; then
            echo -e "  • Conteneur Docker              : ${C_GREEN}ACTIF${C_RESET} ($running)"
            active=true
        else
            echo -e "  • Conteneur Docker              : arrêté"
        fi
        if [[ "$(compose_env_get SMARTHOME_OLLAMA false)" == "true" ]]; then
            if compose ps --status running --services 2>/dev/null | grep -qx ollama; then
                echo -e "  • Conteneur Ollama              : ${C_GREEN}ACTIF${C_RESET}"
            else
                echo -e "  • Conteneur Ollama              : arrêté"
            fi
        fi
    elif docker_mode_installed; then
        echo -e "  • Conteneur Docker              : ${C_YELLOW}Docker inaccessible${C_RESET}"
    fi

    if is_user_service_active; then
        echo -e "  • Service systemd (utilisateur) : ${C_GREEN}ACTIF (en cours d'exécution)${C_RESET}"
        active=true
    elif user_service_exists; then
        echo -e "  • Service systemd (utilisateur) : inactif / arrêté"
    fi

    if is_system_service_active; then
        echo -e "  • Service systemd (système)     : ${C_GREEN}ACTIF (en cours d'exécution)${C_RESET}"
        active=true
    elif system_service_exists; then
        echo -e "  • Service systemd (système)     : inactif / arrêté"
    fi

    pids="$(get_local_pids)"
    if [[ -n "$pids" ]]; then
        pid_list=$(echo $pids | xargs)
        echo -e "  • Processus python local        : ${C_GREEN}ACTIF${C_RESET} (PID: $pid_list)"
        active=true
    fi

    if [[ "$active" == false ]]; then
        echo -e "\n${C_YELLOW}SmartHome n'est pas en cours d'exécution.${C_RESET}"
    fi
    exit 0
fi

stopped_anything=false
was_user_service=false
was_system_service=false

echo -e "${C_CYAN}🛑 Arrêt de SmartHome...${C_RESET}"

# 1. Service utilisateur systemd
if is_user_service_active; then
    echo "  • Arrêt du service systemd utilisateur ($UNIT)..."
    systemctl --user stop "$UNIT"
    stopped_anything=true
    was_user_service=true

    if [[ "$DISABLE" == true ]]; then
        systemctl --user disable "$UNIT" >/dev/null 2>&1 || true
        echo "  • Démarrage automatique utilisateur désactivé."
    fi
fi

# 2. Service système systemd
if is_system_service_active; then
    echo "  • Arrêt du service systemd système ($UNIT)..."
    if [[ "$EUID" -eq 0 ]]; then
        systemctl stop "$UNIT"
    else
        sudo systemctl stop "$UNIT"
    fi
    stopped_anything=true
    was_system_service=true

    if [[ "$DISABLE" == true ]]; then
        if [[ "$EUID" -eq 0 ]]; then
            systemctl disable "$UNIT" >/dev/null 2>&1 || true
        else
            sudo systemctl disable "$UNIT" >/dev/null 2>&1 || true
        fi
        echo "  • Démarrage automatique système désactivé."
    fi
fi

# 3. Conteneurs Docker (arrêt normal : SIGINT, son rétabli, PocketBase arrêté)
if $DOCKER_OK; then
    running="$(docker_running | xargs)"
    if [[ -n "$running" ]]; then
        echo "  • Arrêt du conteneur Docker ($running)..."
        # shellcheck disable=SC2086
        compose stop $running >/dev/null
        stopped_anything=true
    fi
    if $STOP_ALL && compose ps --status running --services 2>/dev/null | grep -qx ollama; then
        echo "  • Arrêt du conteneur Ollama..."
        compose stop ollama >/dev/null
    fi
    if [[ "$DISABLE" == true && "$(compose_env_get SMARTHOME_RESTART no)" != "no" ]]; then
        compose_env_set SMARTHOME_RESTART no
        "${DOCKER[@]}" update --restart=no smarthome-smarthome-server-1 >/dev/null 2>&1 || true
        echo "  • Redémarrage automatique par Docker désactivé."
    fi
fi

# 4. Processus locaux autonomes résiduels
pids="$(get_local_pids)"
if [[ -n "$pids" ]]; then
    pid_list=$(echo $pids | xargs)
    echo "  • Arrêt des processus locaux résiduels (PID: $pid_list)..."
    for pid in $pids; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    # Attente brève de l'arrêt gracieux
    for _ in {1..15}; do
        sleep 0.2
        pids="$(get_local_pids)"
        [[ -z "$pids" ]] && break
    done
    # Forcer l'arrêt si un processus persiste
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            kill -KILL "$pid" 2>/dev/null || true
        done
    fi
    stopped_anything=true
fi

# 5. Remise d'équerre du son au cas où (ducking) ; en Docker, l'arrêt normal du conteneur s'en charge
if [[ -x "$ROOT_DIR/start.sh" && "$DOCKER_OK" == false ]]; then
    "$ROOT_DIR/start.sh" --reset-sound >/dev/null 2>&1 || true
fi

if [[ "$stopped_anything" == true ]]; then
    echo -e "${C_GREEN}✅ SmartHome a été arrêté avec succès.${C_RESET}"
else
    echo -e "${C_YELLOW}ℹ️ SmartHome n'était pas en cours d'exécution.${C_RESET}"
fi

# Redémarrage si demandé
if [[ "$DO_RESTART" == true ]]; then
    echo -e "\n${C_CYAN}🚀 Redémarrage de SmartHome...${C_RESET}"
    if [[ "$was_user_service" == true ]] || user_service_exists; then
        systemctl --user start "$UNIT"
        echo -e "${C_GREEN}✅ Service systemd utilisateur relancé.${C_RESET}"
        echo "  • Journal en direct : journalctl --user -u smarthome -f"
    elif [[ "$was_system_service" == true ]] || system_service_exists; then
        if [[ "$EUID" -eq 0 ]]; then
            systemctl start "$UNIT"
        else
            sudo systemctl start "$UNIT"
        fi
        echo -e "${C_GREEN}✅ Service systemd système relancé.${C_RESET}"
        echo "  • Journal en direct : sudo journalctl -u smarthome -f"
    elif $DOCKER_OK; then
        exec "$ROOT_DIR/start.sh" --no-menu --detach
    else
        exec "$ROOT_DIR/start.sh"
    fi
    exit 0
fi

# Aide pour relancer
echo ""
echo "Pour relancer SmartHome :"
if user_service_exists; then
    echo "  • Via systemd : systemctl --user start smarthome"
    echo "  • Ou en direct : ./start.sh"
elif system_service_exists; then
    echo "  • Via systemd : sudo systemctl start smarthome"
    echo "  • Ou en direct : ./start.sh"
else
    echo "  • Lancer l'assistant : ./start.sh"
fi
