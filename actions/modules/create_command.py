"""
Module d'action de création de commandes par IA (réservé aux superadministrateurs : AUTH_SUPERADMIN_TOOLS).
Envoie la consigne de l'utilisateur et le guide actions/CUSTOM_COMMAND_GUIDE.md à un agent IA local
(par défaut Antigravity : `agy --dangerously-skip-permissions`), avec le modèle et le répertoire configurés.
L'agent tourne en arrière-plan (journal dans ACTIONS_AGENT_LOG_DIR) ; une notification signale la fin.
La nouvelle commande est chargée au prochain redémarrage de SmartHome.
"""

import atexit
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from actions.base import BaseAction
from core.config import Settings, get_settings

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_PROMPT_TEMPLATE = """Tu es un agent de développement chargé d'ajouter UNE commande personnalisée à l'assistant vocal SmartHome.

Répertoire du projet : {directory}
Système cible : {platform}

## Consigne de l'utilisateur (superadministrateur)
{request}

## Guide à suivre impérativement
{guide}
"""


def _resolve(path: str) -> Path:
    """Chemin du .env : `~` développé, relatif à la racine du projet."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else ROOT_DIR / p


def agent_directory(settings: Settings) -> Path:
    return _resolve(settings.ACTIONS_AGENT_DIR) if settings.ACTIONS_AGENT_DIR.strip() else ROOT_DIR


def build_prompt(request: str, settings: Settings) -> str:
    """Consigne + guide précis envoyés à l'agent."""
    guide_path = _resolve(settings.ACTIONS_AGENT_GUIDE)
    guide = guide_path.read_text(encoding="utf-8")
    return _PROMPT_TEMPLATE.format(
        directory=agent_directory(settings), platform=sys.platform, request=request.strip(), guide=guide.strip(),
    )


def build_command(prompt: str, settings: Settings) -> List[str]:
    """Ligne de commande de l'agent : commande de base, modèle, répertoire, délai, puis la consigne."""
    cmd = shlex.split(settings.ACTIONS_AGENT_COMMAND, posix=sys.platform != "win32")
    if settings.ACTIONS_AGENT_MODEL.strip():
        cmd += ["--model", settings.ACTIONS_AGENT_MODEL.strip()]
    cmd += ["--add-dir", str(agent_directory(settings))]
    cmd += ["--print-timeout", f"{settings.ACTIONS_AGENT_TIMEOUT}s"]
    cmd += ["-p", prompt]
    return cmd


def _notify(message: str):
    from actions.registry import get_command_by_tag
    notify = get_command_by_tag("NOTIFY")
    if notify is not None:
        notify.execute(message)


_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


def active_agent_count() -> int:
    with _ACTIVE_LOCK:
        return sum(1 for proc in _ACTIVE_PROCESSES if proc.poll() is None)


def stop_active_agents():
    """Termine proprement les agents create_command lancés par ce processus à l'arrêt."""
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE_PROCESSES)
    for proc in procs:
        if proc.poll() is not None:
            continue
        try:
            if sys.platform != "win32":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except OSError:
            pass


atexit.register(stop_active_agents)


def _watch(process: subprocess.Popen, log_path: Path, log_file):
    """Attend la fin de l'agent (thread d'arrière-plan) et prévient l'utilisateur."""
    try:
        code = process.wait()
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_PROCESSES.discard(process)
        log_file.close()
    if code == 0:
        print(f"✅ [ACTIONS] Agent terminé : {log_path}")
        _notify("Nouvelle commande prête : redémarre SmartHome pour la charger.")
    else:
        print(f"❌ [ACTIONS] Agent en échec (code {code}) : {log_path}")
        _notify(f"Création de commande en échec (code {code}), voir {log_path.name}.")


class CreateCommandAction(BaseAction):
    def __init__(self):
        super().__init__(
            tag="CREATE_COMMAND",
            description=(
                "Créer une nouvelle commande SmartHome personnalisée en confiant sa programmation à un agent IA du PC. "
                "À utiliser seulement quand l'utilisateur demande explicitement de créer, ajouter ou programmer une "
                "nouvelle commande ; l'argument décrit précisément ce que la commande doit faire."
            ),
            # Lancement géré en Python (execute_sync), identique sous Linux et Windows
            script_code="exit 0",
            script_code_windows="exit 0",
            has_args=True,
            args_hint="<description détaillée de la commande à créer>",
            example_prompt="Crée une commande qui vide la corbeille.",
            example_response="[CREATE_COMMAND Une commande qui vide la corbeille de l'utilisateur] "
                             "C'est lancé, je te préviens quand la commande est prête.",
            danger="confirm",
            done_message="C'est lancé, je te préviens quand la commande est prête.",
        )

    def launch(self, request: str, settings: Optional[Settings] = None) -> Tuple[int, str, str]:
        """Démarre l'agent en arrière-plan et rend la main immédiatement."""
        s = settings or get_settings()
        request = (request or "").strip()
        if not request:
            return 1, "", "Décris la commande à créer."
        if len(request) > s.ACTIONS_AGENT_MAX_REQUEST_CHARS:
            return 1, "", f"Consigne trop longue (maximum {s.ACTIONS_AGENT_MAX_REQUEST_CHARS} caractères)."
        directory = agent_directory(s)
        if not directory.is_dir():
            return 1, "", f"Répertoire de l'agent introuvable : {directory}"
        try:
            cmd = build_command(build_prompt(request, s), s)
        except OSError as e:
            return 1, "", f"Guide illisible : {e}"
        log_dir = _resolve(s.ACTIONS_AGENT_LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"create_command_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        log_file.write(f"# Consigne : {request}\n# Modèle : {s.ACTIONS_AGENT_MODEL}\n# Répertoire : {directory}\n\n")
        log_file.flush()
        try:
            print(f"🤖 [ACTIONS] Agent lancé ({cmd[0]}, modèle {s.ACTIONS_AGENT_MODEL}) dans {directory}")
            # Lancé par systemd, SmartHome n'a pas ~/.local/bin dans son PATH : même recherche que les agents
            from core.agents import search_path
            path = search_path(s)
            cmd = [shutil.which(cmd[0], path=path) or cmd[0], *cmd[1:]]
            process = subprocess.Popen(
                cmd, cwd=str(directory), stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                env={**os.environ, "PATH": path},
                **({"start_new_session": True} if sys.platform != "win32" else {}),
            )
        except OSError as e:
            log_file.close()
            return 1, "", f"Impossible de lancer l'agent « {cmd[0]} » : {e}"
        with _ACTIVE_LOCK:
            _ACTIVE_PROCESSES.add(process)
        threading.Thread(target=_watch, args=(process, log_path, log_file), daemon=True,
                         name="create-command-agent").start()
        return 0, f"Agent lancé, journal : {log_path}", ""

    def execute_sync(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return self.launch(args)

    def execute_sync_windows(self, args: str = "", timeout: float = 10.0) -> Tuple[int, str, str]:
        return self.launch(args)

    def execute(self, args: str = "", dry_run: bool = False) -> bool:
        if dry_run:
            print(f"🔍 [ACTIONS] [DRY RUN] Tag [{self.tag}] avec args: {args}")
            return True
        code, out, err = self.launch(args)
        if code != 0:
            print(f"❌ [ACTIONS] [{self.tag}] {err}")
        return code == 0

    def execute_windows(self, args: str = "", dry_run: bool = False) -> bool:
        return self.execute(args, dry_run=dry_run)


ACTIONS = [CreateCommandAction()]


if __name__ == "__main__":
    print("🧪 [DEBUG] Test du module actions/modules/create_command.py (sans lancer l'agent)")
    s = get_settings()
    cmd = build_command(build_prompt("Une commande qui vide la corbeille.", s), s)
    print("Commande :", " ".join(shlex.quote(c) for c in cmd[:-1]), "<consigne>")
    print(f"Répertoire : {agent_directory(s)}")
    print(f"Consigne envoyée : {len(cmd[-1])} caractères")
