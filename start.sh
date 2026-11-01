#!/usr/bin/env bash
# Lancement de SmartHome (après ./install.sh).
#   ./start.sh                Assistant vocal (micro + haut-parleur)
#   ./start.sh --server       Passerelle seule, sans micro (python -m gateway)
#   ./start.sh --reset-sound  Rétablit le son système après un arrêt brutal
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PY="$ROOT_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "❌ Environnement absent : lancez d'abord ./install.sh" >&2; exit 1; }

if [[ "${1:-}" == "--server" ]]; then
    shift
    exec "$PY" -m gateway "$@"
fi
exec "$PY" main.py "$@"
