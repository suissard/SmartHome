"""
Interface de configuration en ligne de commande et menu interactif (`smarthome config`).

Permet à un utilisateur de tout régler (profil, microphone, clé OpenRouter, passerelle et jeton,
Ollama, nom de l'assistant, paramètres avancés) sans jamais ouvrir de fichier `.env` à la main,
tout en offrant des sous-commandes directes (`show`, `path`, `get`, `set`, `unset`, `mic`, `key`,
`token`, `edit`) pour les scripts et les utilisateurs avancés.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
from typing import Any, Optional

from core import profiles, settings_store
from core.config import ENV_FILE, Settings, get_settings, load_settings, set_settings
from core.menu import Option, answered, ask_text, choose, note, style


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return any(word in upper for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))


def _reload_settings() -> Settings:
    fresh = load_settings(ENV_FILE)
    set_settings(fresh)
    return fresh


def _apply_updates(updates: dict[str, Any]) -> list[str]:
    current = get_settings()
    new, changed = settings_store.set_fields(current, updates, ENV_FILE)
    set_settings(new)
    return changed


def list_input_devices() -> list[tuple[int, str, int]]:
    """Retourne la liste des microphones détectés : `[(index, nom, canaux_entrée)]`."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            (idx, str(dev.get("name", f"Périphérique {idx}")), int(dev.get("max_input_channels", 0)))
            for idx, dev in enumerate(devices)
            if int(dev.get("max_input_channels", 0)) > 0
        ]
    except Exception:
        pass

    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            result = []
            for idx in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(idx)
                channels = int(info.get("maxInputChannels", 0))
                if channels > 0:
                    result.append((idx, str(info.get("name", f"Périphérique {idx}")), channels))
            return result
        finally:
            pa.terminate()
    except Exception:
        return []


def _format_value(name: str, value: Any, raw: bool = False) -> str:
    if not raw and value and _is_secret(name):
        return "Configuré (masqué)"
    if value is None:
        return "(défaut système)"
    return str(value)


def cmd_path() -> int:
    print(f"Fichier de configuration : {ENV_FILE}")
    print(f"Profil actif             : {profiles.active_profile()} ({profiles.profile_path(profiles.active_profile())})")
    override = profiles.local_overrides_path()
    if override.is_file():
        print(f"Surcharges du profil     : {override}")
    return 0


def cmd_show(show_all: bool = False) -> int:
    s = _reload_settings()
    active = profiles.active_profile()
    print(f"Configuration SmartHome (profil : {active})")
    print(f"Fichier utilisateur : {ENV_FILE}" + ("" if ENV_FILE.exists() else " (défauts intégrés, non créé)"))
    print("-" * 60)
    data = s.model_dump()
    if show_all:
        for name, value in data.items():
            print(f"  {name:<30} = {_format_value(name, value)}")
        return 0

    keys = [
        "ASSISTANT_NAME",
        "LLM_PROVIDER",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
        "OPENROUTER_MODEL",
        "OPENROUTER_API_KEY",
        "STT_PROVIDER",
        "WHISPER_MODEL",
        "TTS_PROVIDER",
        "TTS_VOICE",
        "WAKEWORD_ENABLED",
        "AUDIO_INPUT_DEVICE_INDEX",
        "GATEWAY_ENABLED",
        "GATEWAY_HOST",
        "GATEWAY_PORT",
        "GATEWAY_AUTH_TOKEN",
        "AUTH_PROVIDER",
    ]
    for name in keys:
        print(f"  {name:<30} = {_format_value(name, data[name])}")
    print("\nAstuce : `smarthome config show --all` pour voir toutes les variables.")
    return 0


def cmd_get(name: str, raw: bool = False) -> int:
    key = name.strip().upper()
    s = _reload_settings()
    if key not in Settings.model_fields:
        print(f"❌ Paramètre inconnu : {key}", file=sys.stderr)
        return 1
    value = getattr(s, key)
    print(_format_value(key, value, raw=raw))
    return 0


def cmd_set(key: str, value: Optional[str] = None) -> int:
    if "=" in key and value is None:
        key, value = key.split("=", 1)
    if value is None:
        print("❌ Valeur manquante : `smarthome config set CLE VALEUR`", file=sys.stderr)
        return 1
    field = key.strip().upper()
    parsed: Any = None if field in ("AUDIO_INPUT_DEVICE_INDEX", "AUDIO_OUTPUT_DEVICE_INDEX") and value.strip().lower() in ("", "auto", "none", "default") else value
    try:
        _reload_settings()
        changed = _apply_updates({field: parsed})
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    if changed:
        print(f"✅ {field} enregistré ({_format_value(field, getattr(get_settings(), field))}).")
    else:
        print(f"ℹ️  {field} avait déjà cette valeur.")
    return 0


def cmd_unset(key: str) -> int:
    field = key.strip().upper()
    if field not in Settings.model_fields:
        print(f"❌ Paramètre inconnu : {field}", file=sys.stderr)
        return 1
    if settings_store.unset_field(field, ENV_FILE):
        _reload_settings()
        print(f"✅ {field} réinitialisé à sa valeur par défaut ({_format_value(field, getattr(get_settings(), field))}).")
    else:
        print(f"ℹ️  {field} utilisait déjà la valeur par défaut.")
    return 0


def cmd_mic(choice: Optional[str] = None) -> int:
    s = _reload_settings()
    devices = list_input_devices()
    if choice is not None:
        raw = choice.strip().lower()
        target = None if raw in ("auto", "none", "default", "") else int(raw)
        _apply_updates({"AUDIO_INPUT_DEVICE_INDEX": target})
        label = "défaut du système" if target is None else f"index {target}"
        print(f"✅ Microphone configuré sur : {label}.")
        return 0

    current = s.AUDIO_INPUT_DEVICE_INDEX
    print(f"Microphone actuel : {'défaut du système' if current is None else f'index {current}'}")
    if not devices:
        print("⚠️ Aucun périphérique d'entrée audio détecté (ou PyAudio/sounddevice indisponible).")
        return 1
    for idx, name, channels in devices:
        marker = " ← actuel" if current == idx else ""
        print(f"  [{idx}] {name} ({channels} canal/canaux){marker}")
    print("\nPour sélectionner : `smarthome config mic <index>` (ou `smarthome config mic auto`).")
    return 0


def cmd_key(value: Optional[str] = None) -> int:
    _reload_settings()
    key = value
    if key is None:
        if not sys.stdin.isatty():
            print("❌ Fournissez la clé en argument ou lancez depuis un terminal interactif.", file=sys.stderr)
            return 1
        key = ask_text("Clé API OpenRouter (laisser vide pour annuler)", secret=True)
        if not key:
            print("Aucune modification.")
            return 0
    _apply_updates({"OPENROUTER_API_KEY": key.strip()})
    print(f"✅ Clé API OpenRouter enregistrée dans {ENV_FILE}.")
    return 0


def cmd_token(generate: bool = False) -> int:
    s = _reload_settings()
    if generate:
        token = secrets.token_hex(32)
        _apply_updates({"GATEWAY_AUTH_TOKEN": token})
        print(f"✅ Nouveau jeton de passerelle généré :\n  {token}")
        return 0
    if s.GATEWAY_AUTH_TOKEN:
        print(s.GATEWAY_AUTH_TOKEN)
        return 0
    print("Aucun jeton configuré. Lancez `smarthome config token --generate` pour en créer un.")
    return 0


def cmd_edit() -> int:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.exists():
        ENV_FILE.write_text("# Configuration avancée SmartHome\n", encoding="utf-8")
        try:
            ENV_FILE.chmod(0o600)
        except OSError:
            pass
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or shutil.which("vi")
    if not editor:
        print(f"Fichier de configuration : {ENV_FILE}")
        return 0
    return subprocess.call([editor, str(ENV_FILE)])


# ---- Menu interactif (sans jamais éditer de fichier à la main) ----

def _menu_profile():
    names = profiles.list_profiles()
    current = profiles.active_profile()
    options = [
        Option(name, name, profiles.describe_profile(name).split(" : ", 1)[-1], "actif" if name == current else "")
        for name in names
    ]
    options.append(Option("Retour", None))
    idx = names.index(current) if current in names else 0
    picked = choose("Choisir le profil d'architecture", options, idx)
    if picked.value:
        profiles.remember_profile(picked.value)
        os.environ[profiles.PROFILE_ENV_VAR] = picked.value
        _reload_settings()
        answered("Profil actif", picked.value)


def _menu_mic():
    s = _reload_settings()
    devices = list_input_devices()
    if not devices:
        note("Aucun microphone détecté sur cette machine.")
        return
    options = [Option("Défaut du système", None, "Recommandé dans la plupart des cas",
                      "actuel" if s.AUDIO_INPUT_DEVICE_INDEX is None else "")]
    default_idx = 0
    for pos, (idx, name, channels) in enumerate(devices, 1):
        is_current = s.AUDIO_INPUT_DEVICE_INDEX == idx
        if is_current:
            default_idx = pos
        options.append(Option(f"[{idx}] {name}", idx, f"{channels} canal(aux)", "actuel" if is_current else ""))
    picked = choose("Choisir le microphone d'entrée", options, default_idx)
    _apply_updates({"AUDIO_INPUT_DEVICE_INDEX": picked.value})
    answered("Microphone", picked.label)


def _menu_openrouter_key():
    s = _reload_settings()
    status = "déjà configurée" if s.OPENROUTER_API_KEY else "non configurée"
    picked = choose(f"Clé API OpenRouter ({status})", [
        Option("Saisir / remplacer la clé", "set", "Stockée de manière sécurisée (droits 600)"),
        Option("Effacer la clé", "clear"),
        Option("Retour", "back"),
    ])
    if picked.value == "set":
        key = ask_text("Clé API OpenRouter", secret=True)
        if key:
            _apply_updates({"OPENROUTER_API_KEY": key})
            answered("Clé OpenRouter", "enregistrée")
    elif picked.value == "clear":
        settings_store.unset_field("OPENROUTER_API_KEY", ENV_FILE)
        _reload_settings()
        answered("Clé OpenRouter", "effacée")


def _menu_gateway():
    while True:
        s = _reload_settings()
        state = "activée" if s.GATEWAY_ENABLED else "désactivée"
        token_state = "configuré" if s.GATEWAY_AUTH_TOKEN else "aucun"
        picked = choose(f"Passerelle web & téléphone ({state}, {s.GATEWAY_HOST}:{s.GATEWAY_PORT})", [
            Option("Désactiver la passerelle" if s.GATEWAY_ENABLED else "Activer la passerelle", "toggle",
                   "Interface web PWA et contrôle depuis un téléphone"),
            Option("Écoute réseau (0.0.0.0) vs locale (127.0.0.1)", "host",
                   f"Actuel : {s.GATEWAY_HOST}"),
            Option("Générer un nouveau jeton d'accès", "gen_token", f"État actuel : {token_state}"),
            Option("Afficher le jeton actuel", "show_token") if s.GATEWAY_AUTH_TOKEN else Option("Retour", "back"),
            Option("Retour", "back"),
        ])
        if picked.value in (None, "back"):
            return
        if picked.value == "toggle":
            updates: dict[str, Any] = {"GATEWAY_ENABLED": not s.GATEWAY_ENABLED}
            if not s.GATEWAY_ENABLED and not s.GATEWAY_AUTH_TOKEN and s.GATEWAY_HOST not in ("127.0.0.1", "localhost", "::1"):
                updates["GATEWAY_AUTH_TOKEN"] = secrets.token_hex(32)
            _apply_updates(updates)
            answered("Passerelle", "activée" if not s.GATEWAY_ENABLED else "désactivée")
        elif picked.value == "host":
            host = choose("Adresse d'écoute de la passerelle", [
                Option("Locale uniquement (127.0.0.1)", "127.0.0.1", "Accessible sur cette machine ou via Tailscale Serve"),
                Option("Tout le réseau (0.0.0.0)", "0.0.0.0", "Accessible depuis le Wi-Fi / LAN (jeton requis)"),
            ], 0 if s.GATEWAY_HOST == "127.0.0.1" else 1).value
            updates = {"GATEWAY_HOST": host}
            if host != "127.0.0.1" and not s.GATEWAY_AUTH_TOKEN:
                updates["GATEWAY_AUTH_TOKEN"] = secrets.token_hex(32)
                note("Un jeton de sécurité a été généré automatiquement.")
            _apply_updates(updates)
            answered("Adresse passerelle", host)
        elif picked.value == "gen_token":
            token = secrets.token_hex(32)
            _apply_updates({"GATEWAY_AUTH_TOKEN": token})
            answered("Jeton généré", token)
        elif picked.value == "show_token":
            note(f"Jeton actuel : {s.GATEWAY_AUTH_TOKEN}")


def _ollama_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _menu_ollama():
    s = _reload_settings()
    reachable = _ollama_reachable(s.OLLAMA_HOST)
    state = "joignable" if reachable else "injoignable"
    picked = choose(f"Serveur Ollama ({s.OLLAMA_HOST} · {state})", [
        Option("Local (http://localhost:11434)", "local"),
        Option("Adresse personnalisée (machine distante)", "custom"),
        Option("Retour", "back"),
    ])
    if picked.value == "local":
        _apply_updates({"OLLAMA_HOST": "http://localhost:11434"})
        answered("Ollama", "http://localhost:11434")
    elif picked.value == "custom":
        url = ask_text(f"Adresse d'Ollama [{s.OLLAMA_HOST}]")
        if url:
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            if ":" not in url.split("//", 1)[1]:
                url += ":11434"
            url = url.rstrip("/")
            _apply_updates({"OLLAMA_HOST": url})
            answered("Ollama", url + (" (en ligne)" if _ollama_reachable(url) else " (hors ligne pour l'instant)"))


def _menu_identity():
    s = _reload_settings()
    picked = choose(f"Assistant « {s.ASSISTANT_NAME} »", [
        Option("Changer le nom de l'assistant", "name", f"Actuel : {s.ASSISTANT_NAME}"),
        Option("Désactiver le mot-clé" if s.WAKEWORD_ENABLED else "Activer le mot-clé", "wake",
               "Écoute continue du mot-clé sur l'ordinateur"),
        Option("Retour", "back"),
    ])
    if picked.value == "name":
        name = ask_text(f"Nouveau nom [{s.ASSISTANT_NAME}]")
        if name:
            _apply_updates({"ASSISTANT_NAME": name})
            answered("Nom de l'assistant", name)
    elif picked.value == "wake":
        _apply_updates({"WAKEWORD_ENABLED": not s.WAKEWORD_ENABLED})
        answered("Mot-clé", "activé" if not s.WAKEWORD_ENABLED else "désactivé")


def run_config_menu() -> int:
    while True:
        s = _reload_settings()
        mic_label = "défaut" if s.AUDIO_INPUT_DEVICE_INDEX is None else f"index {s.AUDIO_INPUT_DEVICE_INDEX}"
        key_label = "configurée" if s.OPENROUTER_API_KEY else "absente"
        gw_label = f"{'active' if s.GATEWAY_ENABLED else 'inactive'} ({s.GATEWAY_HOST}:{s.GATEWAY_PORT})"
        picked = choose(f"SmartHome · Configuration ({profiles.active_profile()})", [
            Option("Assistant complet pas à pas", "wizard", "Configurer écoute, cerveau IA, voix et confort"),
            Option("Profil d'architecture", "profile", f"Actuel : {profiles.active_profile()}"),
            Option("Microphone d'entrée", "mic", f"Actuel : {mic_label}"),
            Option("Clé API OpenRouter", "key", f"État : {key_label}"),
            Option("Passerelle web & téléphone", "gateway", f"État : {gw_label}"),
            Option("Serveur Ollama", "ollama", f"Adresse : {s.OLLAMA_HOST}"),
            Option("Nom & mot-clé", "identity", f"{s.ASSISTANT_NAME} · mot-clé {'on' if s.WAKEWORD_ENABLED else 'off'}"),
            Option("Voir le résumé complet", "show", f"Stocké dans {ENV_FILE}"),
            Option("Ouvrir le fichier brut (avancé)", "edit", str(ENV_FILE)),
            Option("Quitter", "quit"),
        ])
        action = picked.value
        if action in (None, "quit"):
            return 0
        if action == "wizard":
            from core.wizard import run_wizard
            created = run_wizard()
            if created:
                profiles.remember_profile(created)
                os.environ[profiles.PROFILE_ENV_VAR] = created
                _reload_settings()
        elif action == "profile":
            _menu_profile()
        elif action == "mic":
            _menu_mic()
        elif action == "key":
            _menu_openrouter_key()
        elif action == "gateway":
            _menu_gateway()
        elif action == "ollama":
            _menu_ollama()
        elif action == "identity":
            _menu_identity()
        elif action == "show":
            print("", file=sys.stderr)
            cmd_show(show_all=False)
            print(style("2", "\nAppuyez sur Entrée pour revenir au menu..."), end="", file=sys.stderr, flush=True)
            input()
        elif action == "edit":
            cmd_edit()


def handle_config(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="smarthome config", description="Configuration de SmartHome sans éditer de fichier.")
    sub = parser.add_subparsers(dest="action")

    p_show = sub.add_parser("show", help="Affiche la configuration active")
    p_show.add_argument("--all", action="store_true", help="Affiche toutes les variables")

    sub.add_parser("path", help="Affiche les chemins des fichiers de configuration")

    p_get = sub.add_parser("get", help="Lit la valeur d'un paramètre")
    p_get.add_argument("key")
    p_get.add_argument("--raw", action="store_true", help="Affiche aussi les secrets en clair")

    p_set = sub.add_parser("set", help="Modifie un paramètre (CLE VALEUR ou CLE=VALEUR)")
    p_set.add_argument("key")
    p_set.add_argument("value", nargs="?")

    p_unset = sub.add_parser("unset", help="Réinitialise un paramètre à sa valeur par défaut")
    p_unset.add_argument("key")

    p_mic = sub.add_parser("mic", help="Liste ou choisit le microphone")
    p_mic.add_argument("index", nargs="?", help="Index du micro ou 'auto'")

    p_key = sub.add_parser("key", help="Enregistre la clé API OpenRouter")
    p_key.add_argument("value", nargs="?")

    p_token = sub.add_parser("token", help="Affiche ou génère le jeton de passerelle")
    p_token.add_argument("--generate", action="store_true", help="Génère un nouveau jeton aléatoire")

    sub.add_parser("edit", help="Ouvre le fichier de configuration dans l'éditeur (avancé)")

    args = parser.parse_args(argv)
    if args.action is None:
        if sys.stdin.isatty() and sys.stderr.isatty():
            return run_config_menu()
        return cmd_show(show_all=False)
    if args.action == "show":
        return cmd_show(show_all=args.all)
    if args.action == "path":
        return cmd_path()
    if args.action == "get":
        return cmd_get(args.key, raw=args.raw)
    if args.action == "set":
        return cmd_set(args.key, args.value)
    if args.action == "unset":
        return cmd_unset(args.key)
    if args.action == "mic":
        return cmd_mic(args.index)
    if args.action == "key":
        return cmd_key(args.value)
    if args.action == "token":
        return cmd_token(generate=args.generate)
    if args.action == "edit":
        return cmd_edit()
    return 1
