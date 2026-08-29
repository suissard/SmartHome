#!/usr/bin/env python3
"""
🧪 SmartHome — Testeur Manuel d'Actions & Commandes Système
Ce script permet de tester individuellement ou interactivement chaque commande et script d'action.
"""

import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

# Ajout de la racine du projet dans le sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from actions.manager import ActionManager, get_action_manager
from actions.commands import COMMAND_REGISTRY, get_all_commands

# Couleurs ANSI
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_header(title: str):
    print(f"\n{CYAN}{'=' * 65}")
    print(f" {BOLD}{title}{RESET}{CYAN}")
    print(f"{'=' * 65}{RESET}")


def check_system_environment():
    """Diagnostique les utilitaires système disponibles."""
    print_header("🔍 Diagnostic de l'Environnement Système")
    
    tools = [
        ("Serveur audio", ["pactl", "wpctl", "amixer"]),
        ("Contrôle multimédia", ["playerctl", "busctl", "dbus-send", "qdbus6", "qdbus"]),
        ("Notifications", ["notify-send", "kdialog", "zenity"]),
        ("Gestion d'écran", ["kscreen-doctor", "hyprctl", "swaymsg", "wlopm", "xset"]),
        ("Verrouillage", ["loginctl", "xdg-screensaver", "gnome-screensaver-command", "hyprlock", "swaylock"]),
        ("Lanceur d'applications", ["gtk-launch", "kstart5", "kstart", "gio", "xdg-open"]),
        ("Extinction / Redémarrage", ["systemctl", "shutdown", "reboot"])
    ]

    print(f"  • Session : {BOLD}{os.environ.get('XDG_CURRENT_DESKTOP', 'Inconnu')}{RESET} ({os.environ.get('XDG_SESSION_TYPE', 'Inconnu')})")
    print(f"  • Display : {os.environ.get('DISPLAY', 'N/A')} | Wayland : {os.environ.get('WAYLAND_DISPLAY', 'N/A')}\n")

    for category, binaries in tools:
        found = [b for b in binaries if shutil.which(b)]
        if found:
            status = f"{GREEN}✓ {', '.join(found)}{RESET}"
        else:
            status = f"{RED}✗ Aucun ({', '.join(binaries)}){RESET}"
        print(f"  {category:<25} : {status}")
    print()


def run_script_direct(script_name: str, *args):
    """Exécute un script bash directement et affiche sa sortie."""
    script_path = ROOT_DIR / "actions" / "scripts" / script_name
    if not script_path.exists():
        print(f"{RED}❌ Script introuvable : {script_path}{RESET}")
        return False, "Fichier non trouvé"

    # Vérification des droits d'exécution
    if not os.access(script_path, os.X_OK):
        script_path.chmod(script_path.stat().st_mode | 0o755)

    cmd = [str(script_path)] + list(args)
    print(f"{CYAN}🚀 Exécution de : {' '.join(cmd)}{RESET}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            print(f"{GREEN}✓ Succès (Code 0){RESET}")
            if res.stdout.strip():
                print(f"  Sortie stdout : {res.stdout.strip()}")
            return True, res.stdout
        else:
            print(f"{RED}✗ Échec (Code {res.returncode}){RESET}")
            if res.stderr.strip():
                print(f"  Sortie stderr : {res.stderr.strip()}")
            return False, res.stderr
    except Exception as e:
        print(f"{RED}⚠️ Erreur d'exécution : {e}{RESET}")
        return False, str(e)


def test_notify(msg: str = "Test de notification SmartHome"):
    print_header("📢 Test Notification de Bureau ([NOTIFY])")
    run_script_direct("notify.sh", "SmartHome Test", msg)


def test_volume(action: str = "up"):
    print_header(f"🔊 Test Volume Audio ([VOLUME / MUTE / UNMUTE]) -> {action}")
    run_script_direct("volume.sh", action)


def test_media(action: str = "play-pause"):
    print_header(f"🎵 Test Multimédia ([MEDIA_PLAY_PAUSE / NEXT / PREV]) -> {action}")
    run_script_direct("media.sh", action)


def test_open_app(app_name: str = "calculatrice"):
    print_header(f"🚀 Test Lancement Application ([OPEN {app_name}])")
    run_script_direct("open_app.sh", app_name)


def test_screen_off():
    print_header("🖥️ Test Extinction / Veille Écran ([SCREEN_OFF])")
    confirm = input("⚠️ L'écran va s'éteindre (bougez la souris pour le rallumer). Continuer ? [O/n] : ").strip().lower()
    if confirm in ("", "o", "oui", "y", "yes"):
        run_script_direct("screen_off.sh")
    else:
        print("Annulé.")


def test_lock():
    print_header("🔒 Test Verrouillage de Session ([LOCK])")
    confirm = input("⚠️ Votre session va être verrouillée. Continuer ? [O/n] : ").strip().lower()
    if confirm in ("", "o", "oui", "y", "yes"):
        run_script_direct("lock.sh")
    else:
        print("Annulé.")


def test_pipeline_simulation():
    print_header("🤖 Test du Pipeline ActionManager (Simulation Réponses LLM)")
    manager = ActionManager(enabled=True)

    test_cases = [
        ("[NOTIFY Alerte test SmartHome] J'ai affiché une notification de rappel.", False),
        ("[VOLUME 45] Volume sonore ajusté à quarante-cinq pourcent.", False),
        ("[MUTE] Son coupé instantanément.", False),
        ("[UNMUTE] Son réactivé.", False),
        ("[MEDIA_PLAY_PAUSE] Lecture multimédia basculée.", False),
        ("[OPEN calculatrice] J'ouvre la calculatrice pour vous.", False),
        ("[SHUTDOWN] Extinction demandée.", True),  # Dry run
        ("[REBOOT] Redémarrage demandé.", True),    # Dry run
    ]

    for raw_text, is_critical in test_cases:
        print(f"\n--- 📥 Réponse LLM Simulée : « {raw_text} » ---")
        clean_text, actions = manager.extract_actions(raw_text)
        print(f"  • Texte épuré pour TTS : « {clean_text} »")
        print(f"  • Actions extraites     : {[a['tag'] for a in actions]}")

        for act in actions:
            tag = act["tag"]
            if is_critical:
                print(f"  {YELLOW}🛡️ [SÉCURITÉ] Action critique {tag} testée en DRY RUN uniquement{RESET}")
                manager.execute_action(act, dry_run=True)
            else:
                manager.execute_action(act, dry_run=False)


def interactive_menu():
    manager = ActionManager(enabled=True)

    while True:
        print_header("🏠 SmartHome — Menu de Test Manuel des Actions")
        print(f" {BOLD}1.{RESET} 📢 Tester Notification ([NOTIFY])")
        print(f" {BOLD}2.{RESET} 🔊 Tester Volume : Augmenter (+5%)")
        print(f" {BOLD}3.{RESET} 🔉 Tester Volume : Diminuer (-5%)")
        print(f" {BOLD}4.{RESET} 🔇 Tester Volume : Couper le son (Mute)")
        print(f" {BOLD}5.{RESET} 🔊 Tester Volume : Réactiver le son (Unmute)")
        print(f" {BOLD}6.{RESET} 🎚️ Tester Volume : Régler à 40%")
        print(f" {BOLD}7.{RESET} ⏯️ Tester Multimédia : Play / Pause")
        print(f" {BOLD}8.{RESET} ⏭️ Tester Multimédia : Suivant")
        print(f" {BOLD}9.{RESET} ⏮️ Tester Multimédia : Précédent")
        print(f" {BOLD}10.{RESET} 🚀 Tester Lancement App : Calculatrice")
        print(f" {BOLD}11.{RESET} 🚀 Tester Lancement App : Navigateur")
        print(f" {BOLD}12.{RESET} 🚀 Tester Lancement App : Terminal")
        print(f" {BOLD}13.{RESET} 🖥️ Tester Extinction Écran ([SCREEN_OFF])")
        print(f" {BOLD}14.{RESET} 🔒 Tester Verrouillage Session ([LOCK])")
        print(f" {BOLD}15.{RESET} 🤖 Simulation complète du pipeline LLM -> Actions")
        print(f" {BOLD}16.{RESET} 🔍 Re-vérifier l'environnement système")
        print(f" {BOLD}0.{RESET} 🚪 Quitter")

        try:
            choice = input(f"\n{BOLD}Votre choix [0-16] : {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSortie.")
            break

        if choice == "0":
            print("\nAu revoir !")
            break
        elif choice == "1":
            msg = input("Message de notification (défaut: 'Test réussi !') : ").strip() or "Test réussi !"
            test_notify(msg)
        elif choice == "2":
            test_volume("up")
        elif choice == "3":
            test_volume("down")
        elif choice == "4":
            test_volume("mute")
        elif choice == "5":
            test_volume("unmute")
        elif choice == "6":
            test_volume("40")
        elif choice == "7":
            test_media("play-pause")
        elif choice == "8":
            test_media("next")
        elif choice == "9":
            test_media("previous")
        elif choice == "10":
            test_open_app("calculatrice")
        elif choice == "11":
            test_open_app("navigateur")
        elif choice == "12":
            test_open_app("terminal")
        elif choice == "13":
            test_screen_off()
        elif choice == "14":
            test_lock()
        elif choice == "15":
            test_pipeline_simulation()
        elif choice == "16":
            check_system_environment()
        else:
            print(f"{RED}Choix invalide.{RESET}")

        try:
            input(f"\n{YELLOW}Appuyez sur Entrée pour continuer...{RESET}")
        except (KeyboardInterrupt, EOFError):
            break


def main():
    parser = argparse.ArgumentParser(description="Testeur d'actions système SmartHome")
    parser.add_argument("--action", choices=["notify", "volume", "media", "open", "screen_off", "lock", "diag", "pipeline", "all"],
                        help="Action spécifique à exécuter")
    parser.add_argument("--args", default="", help="Argument optionnel pour l'action (ex: '50', 'play-pause', 'firefox')")
    parser.add_argument("--diag", action="store_true", help="Afficher le diagnostic système et quitter")

    args = parser.parse_args()

    if args.diag or args.action == "diag":
        check_system_environment()
        return

    if args.action:
        if args.action == "notify":
            test_notify(args.args or "Notification de test SmartHome")
        elif args.action == "volume":
            test_volume(args.args or "toggle")
        elif args.action == "media":
            test_media(args.args or "play-pause")
        elif args.action == "open":
            test_open_app(args.args or "calculatrice")
        elif args.action == "screen_off":
            test_screen_off()
        elif args.action == "lock":
            test_lock()
        elif args.action == "pipeline":
            test_pipeline_simulation()
        elif args.action == "all":
            check_system_environment()
            test_notify("Test Global SmartHome")
            test_volume("up")
            test_media("play-pause")
            test_pipeline_simulation()
        return

    # Lancement du menu interactif
    check_system_environment()
    interactive_menu()


if __name__ == "__main__":
    main()
