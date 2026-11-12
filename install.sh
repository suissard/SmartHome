#!/usr/bin/env bash
# Script d'installation SmartHome — Linux (Debian/Ubuntu, Fedora, Arch, openSUSE), macOS et serveurs sans écran.
#
#   ./install.sh                  Questions pas à pas (machine, profil, Ollama, paquets, modèles, service)
#   ./install.sh --server         Serveur sans micro : passerelle réseau seule (python -m gateway)
#   ./install.sh --service        Ajoute le démarrage automatique (systemd)
#   ./install.sh -y               Sans question : options de la ligne de commande et .env
#   ./install.sh --help           Toutes les options
#
# Dans un terminal interactif, l'assistant core/install_wizard.py demande ce qu'il faut installer ; les options
# ci-dessous servent de choix par défaut (et --no-* retire la question correspondante).
# Le script est idempotent : le relancer met à jour les dépendances sans écraser le .env existant.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="$ROOT_DIR/.venv"
XDG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/smarthome"
if [[ -n "${SMARTHOME_ENV_FILE:-}" ]]; then
    ENV_FILE="$SMARTHOME_ENV_FILE"
elif [[ -f "$ROOT_DIR/.env" ]]; then
    ENV_FILE="$ROOT_DIR/.env"
else
    ENV_FILE="$XDG_CONFIG_DIR/config.env"
fi
MIN_PYTHON="3.10"

MODE="desktop"
WITH_SERVICE=false
SYSTEM_DEPS="all"        # all (base + outils des actions) | base | none
OLLAMA_CHOICE="auto"     # auto (selon le .env, avec confirmation) | install | use | remote | none
OLLAMA_REMOTE_HOST=""
OLLAMA_PULL=""           # modèles choisis dans l'assistant (sinon déduits du .env)
DOWNLOAD_MODELS=true
ACCOUNTS=""              # true | false (comptes PocketBase de la PWA) ; vide : selon AUTH_PROVIDER du .env
ASK_ACCOUNTS=true
ASSUME_YES=false
NO_MENU=false
WIZARD_RAN=false
PROFILE=""
PYTHON_BIN=""
GATEWAY_BIND=""

usage() {
    cat <<EOF
Usage : ./install.sh [options]

  --server          Mode serveur sans micro : passerelle seule, écoute réseau, jeton généré
  --service         Installe un service systemd (utilisateur en poste, système en serveur)
  --host ADRESSE    Adresse d'écoute de la passerelle en mode serveur (défaut : 0.0.0.0)
  --python CHEMIN   Interpréteur Python à utiliser (≥ $MIN_PYTHON)
  --no-system-deps  Ne pas installer les paquets système (apt, dnf, pacman, zypper, brew)
  --no-ollama       Ne pas installer Ollama ni télécharger de modèle LLM
  --no-models       Ne télécharger aucun modèle (openWakeWord, Whisper, Ollama)
  --accounts        Comptes utilisateurs de la PWA (PocketBase téléchargé, AUTH_PROVIDER=pocketbase)
  --no-accounts     Ne pas poser la question des comptes (le .env décide)
  --no-menu         Pas de questions pas à pas : options ci-dessus et .env
  -y, --yes         Répondre oui à toutes les questions (implique --no-menu)
  -h, --help        Afficher cette aide
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --server) MODE="server" ;;
        --service) WITH_SERVICE=true ;;
        --host) GATEWAY_BIND="${2:?--host attend une adresse}"; shift ;;
        --python) PYTHON_BIN="${2:?--python attend un chemin}"; shift ;;
        --no-system-deps) SYSTEM_DEPS="none" ;;
        --no-ollama) OLLAMA_CHOICE="none" ;;
        --no-models) DOWNLOAD_MODELS=false ;;
        --accounts) ACCOUNTS=true ;;
        --no-accounts) ASK_ACCOUNTS=false ;;
        --no-menu) NO_MENU=true ;;
        -y|--yes) ASSUME_YES=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Option inconnue : $1" >&2; usage; exit 1 ;;
    esac
    shift
done

# --- Affichage ---------------------------------------------------------------
if [[ -t 1 ]]; then
    C_CYAN=$'\e[36m'; C_YELLOW=$'\e[33m'; C_GREEN=$'\e[32m'; C_RED=$'\e[31m'; C_RESET=$'\e[0m'
else
    C_CYAN=""; C_YELLOW=""; C_GREEN=""; C_RED=""; C_RESET=""
fi
step() { echo; echo "${C_CYAN}▶ $*${C_RESET}"; }
info() { echo "  ${C_YELLOW}$*${C_RESET}"; }
ok()   { echo "  ${C_GREEN}✔ $*${C_RESET}"; }
warn() { echo "  ${C_YELLOW}⚠️  $*${C_RESET}"; }
die()  { echo "${C_RED}❌ $*${C_RESET}" >&2; exit 1; }

confirm() {
    $ASSUME_YES && return 0
    [[ -t 0 ]] || return 1
    local answer
    read -r -p "  $1 [o/N] " answer
    [[ "$answer" =~ ^[oOyY] ]]
}

have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [[ $EUID -ne 0 ]]; then
    have sudo && SUDO="sudo"
fi

OS="$(uname -s)"
case "$OS" in
    Linux|Darwin) ;;
    MINGW*|MSYS*|CYGWIN*) die "Sous Windows, lancez install.ps1 dans PowerShell." ;;
    *) die "Système non pris en charge : $OS" ;;
esac

PKG_MANAGER=""
if [[ "$OS" == "Darwin" ]]; then
    have brew && PKG_MANAGER="brew"
else
    for candidate in apt-get dnf pacman zypper; do
        have "$candidate" && { PKG_MANAGER="$candidate"; break; }
    done
fi

# --- 0. Questions pas à pas ---------------------------------------------------
run_wizard() {
    # Python du système (≥ 3.9, bibliothèque standard seule) : le venv n'existe pas encore.
    local py="" candidate
    for candidate in "$PYTHON_BIN" python3 python; do
        [[ -n "$candidate" ]] && have "$candidate" \
            && "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null \
            && { py="$candidate"; break; }
    done
    if [[ -z "$py" ]]; then
        warn "Python 3 absent : pas de questions pas à pas, installation selon les options et le .env."
        return
    fi

    local platform plan status=0
    platform="$([[ "$OS" == "Darwin" ]] && echo darwin || echo linux)"
    plan="$("$py" "$ROOT_DIR/core/install_wizard.py" --platform "$platform" --mode "$MODE" \
        --pkg-manager "$PKG_MANAGER" --host "${GATEWAY_BIND:-0.0.0.0}" \
        --system-deps "$([[ $SYSTEM_DEPS != none ]] && echo true || echo false)" \
        --ollama "$([[ $OLLAMA_CHOICE != none ]] && echo true || echo false)" \
        --models "$DOWNLOAD_MODELS" --service "$WITH_SERVICE" --accounts "$ASK_ACCOUNTS")" || status=$?
    case "$status" in
        0) ;;
        1) exit 0 ;;   # « Annuler » dans le récapitulatif
        130) echo; exit 130 ;;
        *) die "L'assistant d'installation a échoué (relancez avec --no-menu pour s'en passer)." ;;
    esac

    local key value
    while IFS='=' read -r key value; do
        case "$key" in
            MODE) MODE="$value" ;;
            SYSTEM_DEPS) SYSTEM_DEPS="$value" ;;
            OLLAMA) OLLAMA_CHOICE="$value" ;;
            OLLAMA_HOST) OLLAMA_REMOTE_HOST="$value" ;;
            OLLAMA_PULL) OLLAMA_PULL="$value" ;;
            DOWNLOAD_MODELS) DOWNLOAD_MODELS="$value" ;;
            WITH_SERVICE) WITH_SERVICE="$value" ;;
            GATEWAY_BIND) GATEWAY_BIND="$value" ;;
            PROFILE) PROFILE="$value" ;;
            ACCOUNTS) [[ -n "$value" ]] && ACCOUNTS="$value" ;;
        esac
    done <<<"$plan"
    WIZARD_RAN=true
}

if ! $ASSUME_YES && ! $NO_MENU && [[ -t 0 && -t 2 ]]; then
    run_wizard
fi
# Les étapes suivantes lisent la configuration du profil choisi (core/config.py applique SMARTHOME_PROFILE)
[[ -n "$PROFILE" ]] && export SMARTHOME_PROFILE="$PROFILE"

echo "${C_CYAN}🚀 Installation de SmartHome ($([[ $MODE == server ]] && echo "serveur sans micro" || echo "poste vocal") — $OS)${C_RESET}"

# --- 1. Paquets système ------------------------------------------------------
install_system_deps() {
    step "1/8 Paquets système"
    if [[ "$SYSTEM_DEPS" == "none" ]]; then
        info "Ignoré."
        return
    fi

    # Paquets de base : Python, compilation de PyAudio (PortAudio), lecture audio, ducking (pactl).
    # Paquets « poste » : outils utilisés par les actions (notifications, médias, captures, luminosité).
    local base=() desktop=() cmd=()
    if [[ "$OS" == "Darwin" ]]; then
        have brew || die "Homebrew est requis sur macOS : https://brew.sh"
        brew install python@3.12 portaudio libsndfile
        ok "Paquets Homebrew installés."
        return
    elif [[ "$PKG_MANAGER" == "apt-get" ]]; then
        base=(python3 python3-venv python3-dev python3-pip build-essential portaudio19-dev libportaudio2 libsndfile1 curl ca-certificates openssl)
        desktop=(pulseaudio-utils alsa-utils libnotify-bin playerctl brightnessctl)
        cmd=(apt-get install -y)
        $SUDO apt-get update
    elif [[ "$PKG_MANAGER" == "dnf" ]]; then
        base=(python3 python3-devel python3-pip gcc portaudio-devel libsndfile curl openssl)
        desktop=(pulseaudio-utils alsa-utils libnotify playerctl brightnessctl)
        cmd=(dnf install -y)
    elif [[ "$PKG_MANAGER" == "pacman" ]]; then
        base=(python python-pip base-devel portaudio libsndfile curl openssl)
        desktop=(libpulse alsa-utils libnotify playerctl brightnessctl)
        cmd=(pacman -S --needed --noconfirm)
    elif [[ "$PKG_MANAGER" == "zypper" ]]; then
        base=(python3 python3-devel python3-pip gcc portaudio-devel libsndfile1 curl openssl)
        desktop=(pulseaudio-utils alsa-utils libnotify-tools playerctl brightnessctl)
        cmd=(zypper install -y)
    else
        warn "Gestionnaire de paquets inconnu : installez Python ≥ $MIN_PYTHON, PortAudio (en-têtes de dev) et libsndfile."
        return
    fi

    local packages=("${base[@]}")
    [[ "$MODE" == "desktop" && "$SYSTEM_DEPS" == "all" ]] && packages+=("${desktop[@]}")
    info "${cmd[0]} : ${packages[*]}"
    $SUDO "${cmd[@]}" "${packages[@]}" || die "Échec de l'installation des paquets système."
    ok "Paquets système installés."
}

# --- 2. Python & environnement virtuel --------------------------------------
python_ok() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= tuple(map(int, '$MIN_PYTHON'.split('.'))) else 1)" 2>/dev/null
}

find_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
        python_ok "$PYTHON_BIN" || die "$PYTHON_BIN n'est pas un Python ≥ $MIN_PYTHON."
        return
    fi
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if have "$candidate" && python_ok "$candidate"; then
            PYTHON_BIN="$(command -v "$candidate")"
            return
        fi
    done
    die "Python ≥ $MIN_PYTHON introuvable (option --python pour en indiquer un)."
}

setup_venv() {
    step "2/8 Environnement Python"
    find_python
    info "Interpréteur : $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"
    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        "$PYTHON_BIN" -m venv "$VENV_DIR" || die "Création du venv impossible (paquet python3-venv manquant ?)."
        ok "Environnement .venv créé."
    else
        ok "Environnement .venv déjà présent."
    fi
    VPY="$VENV_DIR/bin/python"

    step "3/8 Dépendances Python"
    "$VPY" -m pip install --upgrade pip wheel
    "$VPY" -m pip install -r requirements.txt || die "Échec de pip install -r requirements.txt."
    "$VPY" -m pip install --no-deps --no-build-isolation -e "$ROOT_DIR" || die "Échec de l'installation de la commande smarthome."
    ok "Dépendances et commande smarthome installées."
}

# --- 4. Configuration (sans copier .env.example) -----------------------------
set_env() {
    # Remplace (ou ajoute) KEY=VALUE dans le fichier utilisateur en créant le dossier au besoin.
    "$VPY" - "$ENV_FILE" "$1" "$2" <<'PY'
import os, re, sys
from pathlib import Path

path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
created = not path.exists()
path.parent.mkdir(parents=True, exist_ok=True)
lines = path.read_text(encoding="utf-8").splitlines() if not created else []
pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
for i, line in enumerate(lines):
    if pattern.match(line):
        lines[i] = f"{key}={value}"
        break
else:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
if created:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
PY
}

setting() {
    # Lit une valeur validée par core/config.py (réglages utilisateur > variables d'environnement > défauts).
    "$VPY" -c "from core.config import get_settings; print(getattr(get_settings(), '$1'))"
}

setup_env() {
    step "4/8 Configuration"
    if [[ -f "$ENV_FILE" ]]; then
        ok "Configuration existante conservée ($ENV_FILE)."
    else
        ok "Configuration par défaut intégrée prête ($ENV_FILE créé au besoin)."
    fi

    if [[ -n "$PROFILE" ]]; then
        "$VPY" -c "import sys; from core.profiles import remember_profile; remember_profile(sys.argv[1])" "$PROFILE"
        ok "Profil « $PROFILE » retenu (modifiable avec 'smarthome config' ou au lancement)."
    fi
    if [[ -n "$OLLAMA_REMOTE_HOST" ]]; then
        set_env OLLAMA_HOST "$OLLAMA_REMOTE_HOST"
        ok "Ollama distant : $OLLAMA_REMOTE_HOST."
    fi

    if [[ "$MODE" == "server" ]]; then
        local host="${GATEWAY_BIND:-0.0.0.0}"
        set_env GATEWAY_HOST "$host"
        if [[ -z "$(setting GATEWAY_AUTH_TOKEN)" ]]; then
            local token
            token="$("$VPY" -c 'import secrets; print(secrets.token_hex(32))')"
            set_env GATEWAY_AUTH_TOKEN "$token"
            ok "Jeton de passerelle généré (consultable avec 'smarthome config token')."
        fi
        ok "Passerelle : écoute sur $host:$(setting GATEWAY_PORT)."
    fi

    "$VPY" -c "from core.config import get_settings; get_settings()" || die "La configuration contient une valeur invalide ($ENV_FILE)."
    ok "Configuration valide."
}

# --- 5. Modèles locaux (openWakeWord, Whisper) -------------------------------
download_local_models() {
    step "5/8 Modèles locaux"
    if ! $DOWNLOAD_MODELS; then
        info "Ignoré (modèles téléchargés au premier lancement)."
        return
    fi
    if [[ "$MODE" == "desktop" ]]; then
        "$VPY" -c "import os, sys, openwakeword, openwakeword.utils as u; getattr(u, 'download_models', lambda: None)(); d = os.path.join(os.path.dirname(openwakeword.__file__), 'resources', 'models'); sys.exit(0 if all(os.path.isfile(os.path.join(d, f)) for f in ('melspectrogram.onnx', 'embedding_model.onnx', 'silero_vad.onnx')) else 1)" \
            && ok "Modèles openWakeWord (analyse audio + VAD Silero)." \
            || warn "Téléchargement des modèles openWakeWord impossible (relancez plus tard)."
    fi
    local stt fallback
    stt="$(setting STT_PROVIDER)"; fallback="$(setting STT_FALLBACK_PROVIDER)"
    if [[ "$stt" == "whisper" || "$fallback" == "whisper" ]]; then
        local model
        model="$(setting WHISPER_MODEL)"
        "$VPY" -c "from core.config import get_settings as g; s=g(); from faster_whisper import WhisperModel; WhisperModel(s.WHISPER_MODEL, device=s.WHISPER_DEVICE, compute_type=s.WHISPER_COMPUTE_TYPE)" \
            && ok "Modèle Whisper « $model »." \
            || warn "Téléchargement du modèle Whisper impossible (il le sera au premier lancement)."
    fi
    if [[ "$(setting TTS_PROVIDER)" == "piper" ]]; then
        "$VPY" -c "import sys; from pathlib import Path; from core.config import TTS_MODEL_PATH as p; sys.exit(0 if Path(p).is_file() else 1)" \
            && ok "Voix Piper présente." || warn "Voix Piper introuvable (TTS_VOICE / TTS_MODEL_PATH dans .env)."
    fi
}

# --- 6. Ollama ---------------------------------------------------------------
ollama_up() { curl -fsS --max-time 3 "$1/api/tags" >/dev/null 2>&1; }

setup_ollama() {
    step "6/8 Ollama (LLM local)"
    if [[ "$OLLAMA_CHOICE" == "none" ]]; then
        info "Ignoré."
        return
    fi
    local llm stt fallback tts host models=()
    llm="$(setting LLM_PROVIDER)"; stt="$(setting STT_PROVIDER)"; tts="$(setting TTS_PROVIDER)"
    fallback="$(setting STT_FALLBACK_PROVIDER)"
    if $WIZARD_RAN; then
        # Modèles choisis dans l'assistant (ceux du profil, ou la suggestion si le profil viendra plus tard)
        IFS=',' read -r -a models <<<"$OLLAMA_PULL"
    else
        [[ "$llm" == "ollama" ]] && models+=("$(setting OLLAMA_MODEL)")
        [[ "$stt" == "ollama" || ( "$stt" =~ ^(direct|none|bypass)$ && "$fallback" == "ollama" ) ]] \
            && models+=("$(setting OLLAMA_STT_MODEL)")
        [[ "$tts" == "ollama" ]] && models+=("$(setting OLLAMA_TTS_MODEL)")
        if [[ ${#models[@]} -eq 0 ]]; then
            info "Aucun fournisseur Ollama configuré (LLM_PROVIDER=$llm) : rien à faire."
            return
        fi
    fi
    host="$(setting OLLAMA_HOST)"

    if [[ "$OLLAMA_CHOICE" == "remote" ]]; then
        ollama_up "$host" || { warn "Ollama distant injoignable sur $host : modèles non téléchargés."; return; }
    elif ! have ollama && ! ollama_up "$host"; then
        # « install » a déjà été validé dans l'assistant ; « auto » (sans assistant) demande confirmation
        if [[ "$OLLAMA_CHOICE" == "install" ]] \
            || confirm "Ollama n'est pas installé. L'installer maintenant (script officiel ollama.com) ?"; then
            info "Installation d'Ollama…"
            if [[ "$OS" == "Darwin" ]]; then
                brew install ollama && brew services start ollama
            else
                curl -fsSL https://ollama.com/install.sh | sh
            fi
        else
            warn "Ollama absent : installez-le depuis https://ollama.com puis relancez ce script."
            return
        fi
    fi

    if ! ollama_up "$host"; then
        info "Démarrage du service Ollama…"
        if have systemctl && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
            $SUDO systemctl enable --now ollama || true
        else
            nohup ollama serve >/dev/null 2>&1 &
        fi
        for _ in $(seq 1 15); do ollama_up "$host" && break; sleep 1; done
    fi
    ollama_up "$host" || { warn "Ollama ne répond pas sur $host : modèles non téléchargés."; return; }
    ok "Ollama joignable sur $host."

    if ! $DOWNLOAD_MODELS || [[ ${#models[@]} -eq 0 ]]; then
        return
    fi
    local model
    for model in $(printf '%s\n' "${models[@]}" | sort -u); do
        info "Téléchargement du modèle $model (peut être long)…"
        if have ollama; then
            OLLAMA_HOST="$host" ollama pull "$model"
        else
            # Ollama distant sans client local : bibliothèque Python ollama du venv
            "$VPY" -c "import sys, ollama; ollama.Client(host=sys.argv[1]).pull(sys.argv[2])" "$host" "$model"
        fi && ok "Modèle $model prêt." || warn "Échec du téléchargement de $model."
    done
}

# --- 7. Comptes utilisateurs (PocketBase) ------------------------------------
setup_accounts() {
    step "7/8 Comptes utilisateurs (PocketBase)"
    if [[ "$ACCOUNTS" == "true" ]]; then
        set_env AUTH_PROVIDER pocketbase
    elif [[ "$ACCOUNTS" == "false" && "$(setting AUTH_PROVIDER)" == "pocketbase" ]]; then
        set_env AUTH_PROVIDER none
    fi
    if [[ "$(setting AUTH_PROVIDER)" != "pocketbase" ]]; then
        ok "Désactivés : le jeton de la passerelle donne l'accès (AUTH_PROVIDER=none)."
        return
    fi

    # Les comptes servent à la PWA : passerelle active, jeton maître (accès administrateur) obligatoire hors loopback
    if [[ "$MODE" != "server" && "$(setting GATEWAY_ENABLED)" != "True" ]]; then
        set_env GATEWAY_ENABLED true
        ok "Passerelle activée (GATEWAY_ENABLED=true)."
    fi
    if [[ -z "$(setting GATEWAY_AUTH_TOKEN)" ]]; then
        set_env GATEWAY_AUTH_TOKEN "$("$VPY" -c 'import secrets; print(secrets.token_hex(32))')"
        ok "Jeton administrateur généré (GATEWAY_AUTH_TOKEN dans .env)."
    fi

    "$VPY" -m core.pocketbase install || { warn "PocketBase non installé : relancez ./install.sh ou .venv/bin/python -m core.pocketbase install."; return; }
    if [[ ! -d "$ROOT_DIR/pocketbase/pb_data" && -t 0 ]] && ! $ASSUME_YES && confirm "Créer maintenant le compte administrateur de PocketBase ?"; then
        "$VPY" -m core.pocketbase admin || warn "Compte non créé : .venv/bin/python -m core.pocketbase admin"
    elif [[ ! -d "$ROOT_DIR/pocketbase/pb_data" ]]; then
        info "Compte administrateur à créer : .venv/bin/python -m core.pocketbase admin"
    fi
    ok "SmartHome lance PocketBase lui-même. Comptes du foyer : $(setting POCKETBASE_URL)/_/ (collection users, champ role)."
}

# --- 8. Lanceur CLI, menu bureau & service -----------------------------------
setup_launcher() {
    local bin_dir="$HOME/.local/bin"
    local target="$ROOT_DIR/.venv/bin/smarthome"
    if [[ -x "$target" ]]; then
        mkdir -p "$bin_dir"
        ln -sf "$target" "$bin_dir/smarthome"
        ok "Commande installée : $bin_dir/smarthome"
        case ":$PATH:" in
            *":$bin_dir:"*) ;;
            *) warn "$bin_dir n'est pas dans votre PATH actuel (ajoutez : export PATH=\"\$HOME/.local/bin:\$PATH\")." ;;
        esac
    fi
    if [[ "$OS" == "Linux" && "$MODE" == "desktop" ]]; then
        "$VPY" -m core.cli install-desktop >/dev/null 2>&1 \
            && ok "Raccourci ajouté dans le menu d'applications Linux." \
            || warn "Raccourci bureau non installé (lancez : smarthome install-desktop)."
    fi
}

setup_service() {
    step "8/8 Lancement"
    chmod +x "$ROOT_DIR/start.sh" 2>/dev/null || true
    setup_launcher
    if ! $WITH_SERVICE; then
        info "Pas de démarrage automatique (relancez l'installation ou option --service pour l'ajouter)."
        return
    fi
    if ! have systemctl; then
        warn "systemd absent : démarrage automatique non configuré (utilisez 'smarthome')."
        return
    fi

    local unit="smarthome.service"
    local smarthome_bin="$ROOT_DIR/.venv/bin/smarthome"
    if [[ "$MODE" == "server" ]]; then
        # Service système : tourne sans session ouverte, sous l'utilisateur courant.
        local user="${SUDO_USER:-$USER}"
        $SUDO tee "/etc/systemd/system/$unit" >/dev/null <<EOF
[Unit]
Description=SmartHome — passerelle de l'assistant vocal
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=$user
WorkingDirectory=$ROOT_DIR
ExecStart=$smarthome_bin server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable --now "$unit"
        ok "Service système $unit actif (journal : smarthome logs -f)."
    else
        # Service utilisateur : accès au micro et à PipeWire/PulseAudio de la session.
        local dir="$HOME/.config/systemd/user"
        mkdir -p "$dir"
        cat >"$dir/$unit" <<EOF
[Unit]
Description=SmartHome — assistant vocal
After=pipewire.service pulseaudio.service

[Service]
WorkingDirectory=$ROOT_DIR
ExecStart=$smarthome_bin start --no-menu
ExecStopPost=$smarthome_bin reset-sound
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable --now "$unit"
        ok "Service utilisateur $unit actif (journal : smarthome logs -f)."
    fi
}

install_system_deps
setup_venv
setup_env
download_local_models
setup_ollama
setup_accounts
setup_service

echo
if $WITH_SERVICE; then
    echo "${C_GREEN}🚀 SmartHome est installé et actif via systemd.${C_RESET}"
    echo "  • Il tourne en arrière-plan et se relancera automatiquement au démarrage du PC."
    echo "  • Configurer (micro, clé API...) : smarthome config"
    echo "  • Suivre les logs en direct      : smarthome logs -f"
    echo "  • État / Arrêter / Redémarrer    : smarthome status | smarthome stop | smarthome restart"
else
    echo "${C_GREEN}✅ SmartHome est installé.${C_RESET}"
    if [[ "$MODE" == "server" ]]; then
        echo "  • Lancer la passerelle  : smarthome server"
        echo "  • Voir / créer le jeton : smarthome config token"
        echo "  • Accès HTTPS (micro du téléphone) : docs/MISE_EN_SERVICE.md, étape 3 (Tailscale)"
    else
        echo "  • Lancer l'assistant    : smarthome"
        echo "  • Régler micro / API    : smarthome config"
    fi
    # Proposition de lancement immédiat si exécuté dans un terminal interactif
    if [[ -t 0 && -t 1 ]]; then
        echo
        read -r -p "Voulez-vous lancer SmartHome maintenant (smarthome) ? [O/n] " answer || true
        if [[ -z "$answer" || "$answer" =~ ^[oOyY] ]]; then
            echo "🚀 Lancement de SmartHome..."
            if [[ "$MODE" == "server" ]]; then
                exec "$ROOT_DIR/.venv/bin/smarthome" server
            else
                exec "$ROOT_DIR/.venv/bin/smarthome"
            fi
        fi
    fi
fi
