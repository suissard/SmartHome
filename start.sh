#!/usr/bin/env bash
# Lancement de SmartHome (après ./install.sh).
#   ./start.sh                Assistant vocal (micro + haut-parleur)
#   ./start.sh --server       Passerelle seule, sans micro (python -m gateway)
#   ./start.sh --profile cloud  Profil de configuration (profiles/*.env) ; sans option, menu si terminal interactif
#   ./start.sh --reset-sound  Rétablit le son système après un arrêt brutal
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PY="$ROOT_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "❌ Environnement absent : lancez d'abord ./install.sh" >&2; exit 1; }

# Profil : --profile <nom> > SMARTHOME_PROFILE > menu (terminal interactif) > défaut (mix)
args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile) export SMARTHOME_PROFILE="${2:?--profile demande un nom}"; shift 2 ;;
        --profile=*) export SMARTHOME_PROFILE="${1#*=}"; shift ;;
        *) args+=("$1"); shift ;;
    esac
done
set -- "${args[@]+"${args[@]}"}"
if [[ -z "${SMARTHOME_PROFILE:-}" && -t 0 && "${1:-}" != "--reset-sound" ]]; then
    SMARTHOME_PROFILE="$("$PY" -m core.profiles choose)"
    export SMARTHOME_PROFILE
fi

if [[ "${1:-}" == "--server" ]]; then
    shift
    exec "$PY" -m gateway "$@"
fi
exec "$PY" main.py "$@"
