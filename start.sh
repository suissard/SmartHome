#!/usr/bin/env bash
# Lancement de SmartHome (après ./install.sh).
#   ./start.sh                Assistant vocal (micro + haut-parleur)
#   ./start.sh --server       Passerelle seule, sans micro (python -m gateway)
#   ./start.sh --profile cloud  Profil de configuration (profiles/*.env) ; sans option, menu si terminal interactif
#   ./start.sh --no-menu      Pas de menu : reprend le dernier profil choisi
#   ./start.sh --setup        Configuration pas à pas (crée le profil perso)
#   ./start.sh --reset-sound  Rétablit le son système après un arrêt brutal
set -euo pipefail

# En root, l'assistant ne joint pas le serveur audio de la session (PipeWire / PulseAudio) et ses actions visent le mauvais bureau
if [[ "$EUID" -eq 0 ]]; then
    echo "❌ Ne lancez pas SmartHome avec sudo : relancez ./start.sh sans sudo." >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PY="$ROOT_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "❌ Environnement absent : lancez d'abord ./install.sh" >&2; exit 1; }

if [[ -x "$ROOT_DIR/.venv/bin/smarthome" ]]; then
    exec "$ROOT_DIR/.venv/bin/smarthome" start "$@"
fi

# Repli si l'environnement n'a pas encore été réinstallé avec la commande `smarthome`
# Profil : --profile <nom> > SMARTHOME_PROFILE > menu (terminal interactif) > dernier choix > défaut (hybrid)
args=()
menu=true
setup=False
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
