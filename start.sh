#!/usr/bin/env bash
# Lancement de SmartHome (après ./install.sh). Par défaut dans Docker (compose.yaml), sinon dans le venv (--native).
#   ./start.sh                  Assistant vocal (ou passerelle seule si installé avec --server), dans ce terminal
#   ./start.sh -d               En arrière-plan (journal : docker compose logs -f, arrêt : ./stop.sh)
#   ./start.sh --server         Passerelle seule, sans micro
#   ./start.sh --profile cloud  Profil de configuration (profiles/*.env) ; sans option, menu si terminal interactif
#   ./start.sh --no-menu        Pas de menu : reprend le dernier profil choisi
#   ./start.sh --setup          Configuration pas à pas (crée le profil perso)
#   ./start.sh --build          Reconstruit l'image Docker avant de lancer
#   ./start.sh --reset-sound    Rétablit le son système après un arrêt brutal
#   ./start.sh --native         Sans Docker : environnement .venv (./install.sh --native)
set -euo pipefail

# En root, l'assistant ne joint pas le serveur audio de la session (PipeWire / PulseAudio) et ses actions visent le mauvais bureau
if [[ "$EUID" -eq 0 ]]; then
    echo "❌ Ne lancez pas SmartHome avec sudo : relancez ./start.sh sans sudo." >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PY="$ROOT_DIR/.venv/bin/python"
# shellcheck source=docker/lib.sh
source "$ROOT_DIR/docker/lib.sh"

native=false
for arg in "$@"; do [[ "$arg" == "--native" ]] && native=true; done
# Installation sans Docker (ancienne installation, ou ./install.sh --native)
if ! docker_mode_installed && [[ -x "$PY" ]]; then
    native=true
fi

# ---- Sans Docker : venv --------------------------------------------------------
run_native() {
    [[ -x "$PY" ]] || { echo "❌ Environnement absent : lancez d'abord ./install.sh --native" >&2; exit 1; }
    local args=()
    for arg in "$@"; do [[ "$arg" == "--native" || "$arg" == "-d" || "$arg" == "--detach" || "$arg" == "--build" || "$arg" == "--foreground" ]] || args+=("$arg"); done
    set -- "${args[@]+"${args[@]}"}"
    if [[ -x "$ROOT_DIR/.venv/bin/smarthome" ]]; then
        exec "$ROOT_DIR/.venv/bin/smarthome" start "$@"
    fi

    # Repli si l'environnement n'a pas encore été réinstallé avec la commande `smarthome`
    # Profil : --profile <nom> > SMARTHOME_PROFILE > menu (terminal interactif) > dernier choix > défaut (hybrid)
    args=()
    local menu=true setup=False
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile) export SMARTHOME_PROFILE="${2:?--profile demande un nom}"; shift 2 ;;
            --profile=*) export SMARTHOME_PROFILE="${1#*=}"; shift ;;
            --no-menu) menu=false; shift ;;
            --setup) setup=True; shift ;;
            *) args+=("$1"); shift ;;
        esac
    done
    set -- "${args[@]+"${args[@]}"}"
    if [[ "$setup" == True ]] || [[ "$menu" == true && -z "${SMARTHOME_PROFILE:-}" && -t 0 && "${1:-}" != "--reset-sound" ]]; then
        SMARTHOME_PROFILE="$("$PY" -c "from core.profiles import choose_profile; print(choose_profile(setup=$setup))")"
        export SMARTHOME_PROFILE
    fi

    if [[ "${1:-}" == "--server" ]]; then
        shift
        exec "$PY" -m gateway "$@"
    fi
    exec "$PY" main.py "$@"
}

if $native; then
    run_native "$@"
fi

# ---- Docker ----------------------------------------------------------------------
docker_mode_installed || { echo "❌ SmartHome n'est pas installé : lancez d'abord ./install.sh" >&2; exit 1; }
docker_init || {
    echo "❌ Docker est introuvable ou inaccessible (service arrêté ?). Relancez ./install.sh, ou : sudo systemctl start docker" >&2
    exit 1
}

profile="${SMARTHOME_PROFILE:-}"
menu=true
setup=false
detach=false
foreground=false
build=false
reset_sound=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile) profile="${2:?--profile demande un nom}"; shift ;;
        --profile=*) profile="${1#*=}" ;;
        --no-menu) menu=false ;;
        --setup) setup=true ;;
        --server) export SMARTHOME_MODE_OVERRIDE=server ;;
                -d|--detach) detach=true ;;
        --foreground) foreground=true; menu=false ;;   # service systemd : premier plan, sans menu
        --build) build=true ;;
        --reset-sound) reset_sound=true ;;
        --native) ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Option inconnue : $1 (./start.sh --help)" >&2; exit 1 ;;
    esac
    shift
done

refresh_session_env
ensure_image "$build" || { echo "❌ Construction de l'image impossible." >&2; exit 1; }

if $reset_sound; then
    in_voice_container python -m core.cli reset-sound
    exit $?
fi

# Profil : --profile <nom> > SMARTHOME_PROFILE > menu (terminal interactif) > dernier choix > défaut (hybrid).
# Le choix est mémorisé dans profiles/.last (monté dans le conteneur), que le service relit avec --no-menu.
if [[ -n "$profile" ]]; then
    in_container python -c "import sys; from core import profiles; profiles.profile_path(sys.argv[1]); profiles.remember_profile(sys.argv[1])" "$profile" \
        || exit 1
elif $setup || { $menu && [[ -t 0 && -t 2 ]]; }; then
    in_container python -c "import sys; from core.profiles import choose_profile; choose_profile(setup=sys.argv[1] == 'True')" "$($setup && echo True || echo False)" \
        || exit $?
fi

service="$(smarthome_service)"
if [[ "$(compose_env_get SMARTHOME_OLLAMA false)" == "true" ]]; then
    compose up -d ollama
fi

if $detach; then
    compose up -d --no-deps --force-recreate "$service"
    echo "✅ SmartHome tourne en arrière-plan."
    echo "  • Journal en direct : docker compose --env-file compose.env logs -f $service"
    echo "  • Arrêter           : ./stop.sh"
    exit 0
fi

# Premier plan (comme sans Docker) : Ctrl+C arrête SmartHome
$foreground || echo "🐳 SmartHome démarre dans Docker (Ctrl+C pour arrêter, ./start.sh -d pour l'arrière-plan)…"
compose up --no-deps --force-recreate --no-log-prefix --attach "$service" "$service"
