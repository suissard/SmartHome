# Fonctions Docker partagées par install.sh, start.sh et stop.sh (fichier sourcé, jamais exécuté seul).
#
# compose.env (non versionné, écrit par install.sh, complété par start.sh) décrit l'installation Docker :
#   SMARTHOME_MODE=voice|server     Service lancé : assistant vocal ou passerelle seule
#   SMARTHOME_OLLAMA=true|false     Ollama dans un conteneur (profil Compose « ollama »)
#   SMARTHOME_GPU=true|false        Carte NVIDIA pour ce conteneur (compose.gpu.yaml)
#   SMARTHOME_RESTART=no|unless-stopped  Redémarrage par Docker (serveur avec démarrage automatique)
#   SMARTHOME_UID / _GID / _RUNTIME_DIR, DISPLAY, WAYLAND_DISPLAY : session de l'hôte (relus à chaque lancement)
#   SMARTHOME_IMAGE_HASH            Empreinte de Dockerfile + requirements.txt de la dernière image construite
# Il sert aussi de --env-file à Compose : le .env du projet (celui de l'application) n'est jamais lu par Compose.

SMARTHOME_ROOT="${SMARTHOME_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_ENV_FILE="$SMARTHOME_ROOT/compose.env"
SMARTHOME_IMAGE="smarthome:local"
DOCKER=()

docker_mode_installed() { [[ -f "$COMPOSE_ENV_FILE" ]]; }

compose_env_get() {
    # compose_env_get CLÉ [défaut]
    local value=""
    [[ -f "$COMPOSE_ENV_FILE" ]] && value="$(sed -n "s/^$1=//p" "$COMPOSE_ENV_FILE" | tail -n 1)"
    echo "${value:-${2:-}}"
}

compose_env_set() {
    # compose_env_set CLÉ VALEUR (remplace ou ajoute la ligne)
    local key="$1" value="$2" tmp
    if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then
        printf '# Installation Docker de SmartHome (install.sh) — relu par start.sh et stop.sh, voir docker/lib.sh\n' >"$COMPOSE_ENV_FILE"
    fi
    tmp="$(mktemp)"
    grep -v "^$key=" "$COMPOSE_ENV_FILE" >"$tmp" || true
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
    cat "$tmp" >"$COMPOSE_ENV_FILE"
    rm -f "$tmp"
}

docker_init() {
    # Choisit `docker` ou `sudo docker` (utilisateur pas encore dans le groupe docker effectif). 1 si Docker est inutilisable.
    command -v docker >/dev/null 2>&1 || return 1
    if docker info >/dev/null 2>&1; then
        DOCKER=(docker)
    elif [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
        DOCKER=(sudo docker)
    else
        return 1
    fi
    "${DOCKER[@]}" compose version >/dev/null 2>&1
}

smarthome_mode() {
    # voice | server (SMARTHOME_MODE_OVERRIDE : ./start.sh --server ponctuel)
    echo "${SMARTHOME_MODE_OVERRIDE:-$(compose_env_get SMARTHOME_MODE voice)}"
}

smarthome_service() {
    [[ "$(smarthome_mode)" == "server" ]] && echo smarthome-server || echo smarthome
}

compose() {
    local files=(-f "$SMARTHOME_ROOT/compose.yaml")
    [[ "$(compose_env_get SMARTHOME_GPU false)" == "true" ]] && files+=(-f "$SMARTHOME_ROOT/compose.gpu.yaml")
    local profiles=(--profile "$(smarthome_mode)")
    [[ "$(compose_env_get SMARTHOME_OLLAMA false)" == "true" ]] && profiles+=(--profile ollama)
    "${DOCKER[@]}" compose --project-directory "$SMARTHOME_ROOT" --env-file "$COMPOSE_ENV_FILE" "${files[@]}" "${profiles[@]}" "$@"
}

refresh_session_env() {
    # Utilisateur et session de l'hôte : le conteneur prend son UID et son serveur son
    local uid
    uid="$(id -u)"
    compose_env_set SMARTHOME_UID "$uid"
    compose_env_set SMARTHOME_GID "$(id -g)"
    compose_env_set SMARTHOME_RUNTIME_DIR "${XDG_RUNTIME_DIR:-/run/user/$uid}"
    compose_env_set DISPLAY "${DISPLAY:-}"
    compose_env_set WAYLAND_DISPLAY "${WAYLAND_DISPLAY:-}"
    # Le .env du projet doit exister : sinon la configuration irait dans le HOME du conteneur et serait perdue
    if [[ ! -f "$SMARTHOME_ROOT/.env" ]]; then
        : >"$SMARTHOME_ROOT/.env"
        chmod 600 "$SMARTHOME_ROOT/.env" 2>/dev/null || true
    fi
}

image_hash() {
    cat "$SMARTHOME_ROOT/Dockerfile" "$SMARTHOME_ROOT/requirements.txt" "$SMARTHOME_ROOT/docker/asound.conf" | sha256sum | cut -c1-16
}

ensure_image() {
    # Reconstruit l'image si elle manque, si --build est demandé ou si Dockerfile / requirements.txt ont changé
    local force="${1:-false}" wanted
    wanted="$(image_hash)"
    if $force || ! "${DOCKER[@]}" image inspect "$SMARTHOME_IMAGE" >/dev/null 2>&1 \
        || [[ "$(compose_env_get SMARTHOME_IMAGE_HASH)" != "$wanted" ]]; then
        echo "🐳 Construction de l'image SmartHome (quelques minutes la première fois)…" >&2
        compose build "$(smarthome_service)" >&2 || return 1
        compose_env_set SMARTHOME_IMAGE_HASH "$wanted"
    fi
}

in_container() {
    # in_container COMMANDE... : commande ponctuelle dans un conteneur jetable (passerelle non lancée).
    # Terminal interactif conservé si stdin et stdout en sont un (menus, questions), sinon -T (sortie capturable).
    local tty=(-T)
    [[ -t 0 && -t 1 ]] && tty=()
    compose run --rm --no-deps "${tty[@]}" smarthome-server "$@"
}

in_voice_container() {
    # Idem avec le son de la session (remise à niveau du son, tests audio)
    local tty=(-T)
    [[ -t 0 && -t 1 ]] && tty=()
    compose run --rm --no-deps "${tty[@]}" smarthome "$@"
}
