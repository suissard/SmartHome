"""
Point d'entrée unifié de la commande Linux `smarthome`.

Sous-commandes :
  smarthome                 Démarre l'assistant vocal (menu de profil en terminal interactif)
  smarthome start           Idem (options : --profile, --no-menu, --setup, --server)
  smarthome server          Démarre la passerelle web seule (sans micro)
  smarthome setup           Assistant de configuration pas à pas (sans éditer de fichier)
  smarthome config          Menu ou commandes de réglage (micro, clé API, jeton, Ollama...)
  smarthome status          Affiche l'état d'exécution et la configuration active
  smarthome stop            Arrête SmartHome (service systemd et/ou processus actif)
  smarthome restart         Redémarre SmartHome
  smarthome logs            Affiche les journaux du service systemd
  smarthome reset-sound     Rétablit le son système après un arrêt brutal
  smarthome install-desktop Installe (ou retire avec --uninstall) le raccourci d'application Linux
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from core import profiles
from core.menu import Option, answered, choose

BASE_DIR = Path(__file__).resolve().parent.parent
UNIT_NAME = "smarthome.service"
APP_VERSION = "0.1.0"


def _refuse_root():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("❌ Ne lancez pas SmartHome avec sudo : relancez `smarthome` avec votre utilisateur.", file=sys.stderr)
        sys.exit(1)


def _apply_profile_flag(profile_name: Optional[str]):
    if profile_name:
        profiles.profile_path(profile_name)
        os.environ[profiles.PROFILE_ENV_VAR] = profile_name


def _run_reset_sound() -> int:
    os.chdir(BASE_DIR)
    from audio.ducking import AudioDucker
    AudioDucker.reset_all()
    return 0


def _run_assistant(profile: Optional[str] = None, no_menu: bool = False, setup: bool = False, server: bool = False) -> int:
    _refuse_root()
    os.chdir(BASE_DIR)
    _apply_profile_flag(profile)

    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    if setup or (not no_menu and not os.environ.get(profiles.PROFILE_ENV_VAR) and interactive):
        os.environ[profiles.PROFILE_ENV_VAR] = profiles.choose_profile(setup=setup)

    if server:
        from gateway.__main__ import main as gateway_main
        gateway_main()
        return 0

    from core.restart import restart_if_requested
    import main as assistant_main

    assistant_main.main()
    restart_if_requested()
    return 0


def _run_setup() -> int:
    _refuse_root()
    os.chdir(BASE_DIR)
    from core.wizard import run_wizard
    created = run_wizard()
    if not created:
        print("Configuration annulée.")
        return 1
    profiles.remember_profile(created)
    os.environ[profiles.PROFILE_ENV_VAR] = created
    answered("Profil enregistré", created)
    if sys.stdin.isatty() and sys.stderr.isatty():
        picked = choose("Que faire maintenant ?", [
            Option("Démarrer SmartHome maintenant", "start"),
            Option("Terminer (lancer plus tard avec `smarthome`)", "exit"),
        ])
        if picked.value == "start":
            return _run_assistant(profile=created, no_menu=True)
    return 0


# ---- Gestion du service systemd & processus locaux ----

def _systemctl_ok(user: bool, *args: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    cmd = ["systemctl", "--user", *args] if user else ["systemctl", *args]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def _user_service_exists() -> bool:
    unit_file = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    return unit_file.is_file() or _systemctl_ok(True, "list-unit-files", UNIT_NAME)


def _system_service_exists() -> bool:
    unit_file = Path("/etc/systemd/system") / UNIT_NAME
    return unit_file.is_file() or _systemctl_ok(False, "list-unit-files", UNIT_NAME)


def _local_pids() -> list[int]:
    if not shutil.which("pgrep"):
        return []
    pattern = rf"({BASE_DIR}/\.venv/bin/(python|smarthome)|{BASE_DIR}/main\.py|{BASE_DIR}/pocketbase/pocketbase serve)"
    res = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    if res.returncode != 0:
        return []
    own = {os.getpid(), os.getppid()}
    pids = []
    for token in res.stdout.split():
        if token.isdigit():
            pid = int(token)
            if pid not in own:
                pids.append(pid)
    return pids


def _cmd_status() -> int:
    from core.config import ENV_FILE, get_settings
    from llm.providers import LLM_PROVIDERS

    print("🔍 État de SmartHome :")
    active = False
    if _systemctl_ok(True, "is-active", "--quiet", UNIT_NAME):
        print("  • Service systemd (utilisateur) : ACTIF")
        active = True
    elif _user_service_exists():
        print("  • Service systemd (utilisateur) : arrêté")

    if _systemctl_ok(False, "is-active", "--quiet", UNIT_NAME):
        print("  • Service systemd (système)     : ACTIF")
        active = True
    elif _system_service_exists():
        print("  • Service systemd (système)     : arrêté")

    pids = _local_pids()
    if pids:
        print(f"  • Processus local               : ACTIF (PID: {', '.join(map(str, pids))})")
        active = True

    if not active:
        print("  • Exécution                     : arrêté")

    s = get_settings()
    active_prof = profiles.active_profile()
    print("\n📋 Configuration :")
    print(f"  • Profil actif                  : {active_prof}")
    print(f"  • Fichier utilisateur           : {ENV_FILE}" + ("" if ENV_FILE.exists() else " (défauts intégrés)"))
    print(f"  • Cerveau LLM                   : {LLM_PROVIDERS.get(s.LLM_PROVIDER).describe(s)}")
    print(f"  • Écoute STT / Voix TTS         : {s.STT_PROVIDER} / {s.TTS_PROVIDER}")
    gw = f"ws://{s.GATEWAY_HOST}:{s.GATEWAY_PORT}/ws" if s.GATEWAY_ENABLED else "désactivée"
    print(f"  • Passerelle web                : {gw}")
    return 0


def _cmd_stop(disable: bool = False) -> tuple[bool, bool, bool]:
    print("🛑 Arrêt de SmartHome...")
    stopped = False
    was_user = False
    was_system = False

    if _systemctl_ok(True, "is-active", "--quiet", UNIT_NAME):
        print(f"  • Arrêt du service systemd utilisateur ({UNIT_NAME})...")
        subprocess.run(["systemctl", "--user", "stop", UNIT_NAME], check=False)
        stopped = True
        was_user = True
        if disable:
            subprocess.run(["systemctl", "--user", "disable", UNIT_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print("  • Démarrage automatique utilisateur désactivé.")

    if _systemctl_ok(False, "is-active", "--quiet", UNIT_NAME):
        print(f"  • Arrêt du service systemd système ({UNIT_NAME})...")
        prefix = [] if (hasattr(os, "geteuid") and os.geteuid() == 0) else ["sudo"]
        subprocess.run([*prefix, "systemctl", "stop", UNIT_NAME], check=False)
        stopped = True
        was_system = True
        if disable:
            subprocess.run([*prefix, "systemctl", "disable", UNIT_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print("  • Démarrage automatique système désactivé.")

    pids = _local_pids()
    if pids:
        print(f"  • Arrêt des processus locaux (PID: {', '.join(map(str, pids))})...")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(15):
            time.sleep(0.2)
            pids = _local_pids()
            if not pids:
                break
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        stopped = True

    try:
        _run_reset_sound()
    except Exception:
        pass

    if stopped:
        print("✅ SmartHome a été arrêté.")
    else:
        print("ℹ️  SmartHome n'était pas en cours d'exécution.")
    return stopped, was_user, was_system


def _cmd_restart() -> int:
    _, was_user, was_system = _cmd_stop(disable=False)
    print("\n🚀 Redémarrage de SmartHome...")
    if was_user or _user_service_exists():
        subprocess.run(["systemctl", "--user", "start", UNIT_NAME], check=True)
        print("✅ Service systemd utilisateur relancé (`smarthome logs -f`).")
        return 0
    if was_system or _system_service_exists():
        prefix = [] if (hasattr(os, "geteuid") and os.geteuid() == 0) else ["sudo"]
        subprocess.run([*prefix, "systemctl", "start", UNIT_NAME], check=True)
        print("✅ Service systemd système relancé (`smarthome logs -f`).")
        return 0
    return _run_assistant(no_menu=True)


def _cmd_logs(follow: bool = False, lines: int = 50) -> int:
    if not shutil.which("journalctl"):
        print("❌ `journalctl` est introuvable sur ce système.", file=sys.stderr)
        return 1
    if _user_service_exists():
        cmd = ["journalctl", "--user", "-u", UNIT_NAME, "-n", str(lines)]
    elif _system_service_exists():
        cmd = ["journalctl", "-u", UNIT_NAME, "-n", str(lines)]
    else:
        print("ℹ️  Aucun service systemd `smarthome.service` installé (lancez `./install.sh --service` pour l'activer).")
        return 1
    if follow:
        cmd.append("-f")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


# ---- Raccourci d'application Linux (.desktop) ----

def _desktop_paths() -> tuple[Path, Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    desktop = data_home / "applications" / "smarthome.desktop"
    icon = data_home / "icons" / "hicolor" / "scalable" / "apps" / "smarthome.svg"
    return desktop, icon


def install_desktop_entry(uninstall: bool = False) -> int:
    desktop, icon = _desktop_paths()
    if uninstall:
        removed = False
        for path in (desktop, icon):
            if path.exists():
                path.unlink()
                removed = True
        if shutil.which("update-desktop-database"):
            subprocess.run(["update-desktop-database", str(desktop.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print("✅ Raccourci SmartHome supprimé." if removed else "ℹ️  Aucun raccourci SmartHome trouvé.")
        return 0

    local_bin = Path.home() / ".local" / "bin" / "smarthome"
    venv_bin = BASE_DIR / ".venv" / "bin" / "smarthome"
    exec_path = local_bin if local_bin.exists() else (venv_bin if venv_bin.exists() else Path(sys.argv[0]).resolve())

    src_icon = BASE_DIR / "gateway" / "web" / "icon.svg"
    icon_value = "audio-input-microphone"
    if src_icon.is_file():
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_icon, icon)
        icon_value = str(icon)

    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "\n".join([
            "[Desktop Entry]",
            "Type=Application",
            "Name=SmartHome",
            "GenericName=Assistant vocal local",
            "Comment=Assistant vocal domotique 100 % local",
            f"Exec={exec_path} start",
            f"Icon={icon_value}",
            "Terminal=true",
            "Categories=Utility;AudioVideo;",
            "Keywords=assistant;voice;domotique;jarvis;smarthome;",
            "",
        ]),
        encoding="utf-8",
    )
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(desktop.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    print(f"✅ Raccourci d'application installé : {desktop}")
    return 0


def _build_start_options(parser: argparse.ArgumentParser):
    parser.add_argument("--profile", help="Profil de configuration (ex: hybrid, mix, local-lfm)")
    parser.add_argument("--no-menu", action="store_true", help="Démarre sans menu sur le dernier profil utilisé")
    parser.add_argument("--setup", action="store_true", help="Ouvre l'assistant de configuration pas à pas")
    parser.add_argument("--server", action="store_true", help="Lance la passerelle web seule (sans micro)")
    parser.add_argument("--reset-sound", action="store_true", help="Rétablit le son système après un arrêt brutal")


def main(argv: Optional[list[str]] = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    # `smarthome` sans sous-commande (ou avec options directes comme `--profile cloud`) -> `smarthome start`
    if not raw_argv or (raw_argv[0].startswith("-") and raw_argv[0] not in ("-h", "--help", "-V", "--version")):
        raw_argv = ["start", *raw_argv]

    if raw_argv[0] == "config":
        from core.cli_config import handle_config
        return handle_config(raw_argv[1:])

    parser = argparse.ArgumentParser(
        prog="smarthome",
        description="SmartHome — Assistant vocal domotique 100 % local.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"smarthome {APP_VERSION}")
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Démarre l'assistant vocal (commande par défaut)")
    _build_start_options(p_start)

    p_server = sub.add_parser("server", help="Démarre uniquement la passerelle web (sans micro)")
    p_server.add_argument("--profile", help="Profil de configuration")

    sub.add_parser("setup", help="Assistant interactif de configuration pas à pas")
    sub.add_parser("config", help="Régler micro, clé API, jeton, Ollama... sans éditer de fichier")
    sub.add_parser("status", help="Affiche l'état d'exécution et la configuration active")

    p_stop = sub.add_parser("stop", help="Arrête SmartHome (service systemd et/ou processus)")
    p_stop.add_argument("--disable", "-d", action="store_true", help="Désactive aussi le démarrage automatique")

    sub.add_parser("restart", help="Redémarre SmartHome")

    p_logs = sub.add_parser("logs", help="Affiche les journaux du service systemd")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Suit les journaux en direct")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Nombre de lignes à afficher")

    sub.add_parser("reset-sound", help="Rétablit le son système après un arrêt brutal")

    p_desk = sub.add_parser("install-desktop", help="Installe le raccourci d'application dans le menu Linux")
    p_desk.add_argument("--uninstall", action="store_true", help="Supprime le raccourci d'application")

    args = parser.parse_args(raw_argv)

    if args.command == "start":
        if args.reset_sound:
            return _run_reset_sound()
        return _run_assistant(profile=args.profile, no_menu=args.no_menu, setup=args.setup, server=args.server)
    if args.command == "server":
        return _run_assistant(profile=args.profile, no_menu=True, server=True)
    if args.command == "setup":
        return _run_setup()
    if args.command == "status":
        return _cmd_status()
    if args.command == "stop":
        _cmd_stop(disable=args.disable)
        return 0
    if args.command == "restart":
        return _cmd_restart()
    if args.command == "logs":
        return _cmd_logs(follow=args.follow, lines=args.lines)
    if args.command == "reset-sound":
        return _run_reset_sound()
    if args.command == "install-desktop":
        return install_desktop_entry(uninstall=args.uninstall)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
