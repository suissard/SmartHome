#!/usr/bin/env python3
"""
🔌 SmartHome MCP Server (Model Context Protocol)
Expose toutes les capacités de SmartHome sous forme de serveur MCP standardisé :
- Outils (Tools) : Actions OS, multimédia, volume, notifications, TTS, audio feedback, ducking, STT, LLM.
- Ressources (Resources) : Statut système, catalogue d'actions, historique de conversation, configuration.
- Prompts (Prompts) : Assistants et planificateurs domotiques.

Transports supportés :
- stdio (local : Claude Desktop, Antigravity IDE, Cursor, VS Code)
- sse / streamable-http (réseau : LAN, Home Assistant, Web apps, clients distants)
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Assure la résolution des modules depuis la racine du projet
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer

from core.config import (
    MCP_TRANSPORT,
    MCP_HOST,
    MCP_PORT,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OLLAMA_HOST,
    OPENROUTER_MODEL,
    STT_PROVIDER,
    WHISPER_MODEL,
    OPENROUTER_STT_MODEL,
    TTS_PROVIDER,
    TTS_MODEL_PATH,
    OPENROUTER_TTS_MODEL,
    OPENROUTER_TTS_VOICE,
    FOLLOW_UP_TIMEOUT,
    LLM_HISTORY_MESSAGES,
    ACTIONS_ENABLED,
    ACTIONS_DYNAMIC_PROMPT,
    DUCKING_ENABLED,
    DUCKING_VOLUME_PERCENT,
)
from actions.manager import get_action_manager
from actions.registry import get_all_commands, get_command_by_tag
from llm.llm import (
    ask_llm,
    get_history,
    clear_history,
    add_history_message,
    get_default_system_prompt,
)

# Singletons audio initialisés paresseusement (lazy-loading) pour un démarrage instantané
_tts_instance = None
_feedback_instance = None
_ducker_instance = None
_transcriber_instance = None


def _get_tts():
    """Charge ou retourne l'instance TextToSpeech."""
    global _tts_instance
    if _tts_instance is None:
        try:
            from audio.tts import TextToSpeech
            _tts_instance = TextToSpeech()
        except Exception as e:
            print(f"⚠️ [MCP] Impossible d'initialiser le TTS : {e}", file=sys.stderr)
            return None
    return _tts_instance


def _get_feedback():
    """Charge ou retourne l'instance FeedbackManager."""
    global _feedback_instance
    if _feedback_instance is None:
        try:
            from audio.feedback import FeedbackManager
            tts = _get_tts()
            _feedback_instance = FeedbackManager(tts=tts)
        except Exception as e:
            print(f"⚠️ [MCP] Impossible d'initialiser FeedbackManager : {e}", file=sys.stderr)
            return None
    return _feedback_instance


def _get_ducker():
    """Charge ou retourne l'instance AudioDucker."""
    global _ducker_instance
    if _ducker_instance is None:
        try:
            from audio.ducking import AudioDucker
            _ducker_instance = AudioDucker()
        except Exception as e:
            print(f"⚠️ [MCP] Impossible d'initialiser AudioDucker : {e}", file=sys.stderr)
            return None
    return _ducker_instance


def _get_transcriber():
    """Charge ou retourne l'instance VoiceTranscriber."""
    global _transcriber_instance
    if _transcriber_instance is None:
        try:
            from audio.transcribe import VoiceTranscriber
            _transcriber_instance = VoiceTranscriber()
        except Exception as e:
            print(f"⚠️ [MCP] Impossible d'initialiser VoiceTranscriber : {e}", file=sys.stderr)
            return None
    return _transcriber_instance


# Initialisation du serveur MCP
app = MCPServer(
    name="smarthome",
    instructions="Serveur MCP SmartHome universel : automatisation domotique, contrôle système OS, synthèse vocale, audio et raisonnement IA."
)


# ============================================================================
# 🛠️ OUTILS MCP (TOOLS) — ACTIONS SYSTÈME & OS
# ============================================================================

@app.tool()
def list_actions() -> list[dict]:
    """
    Retourne la liste complète de toutes les commandes et actions système disponibles dans SmartHome.
    Chaque entrée comprend le tag, la description, les arguments attendus et des exemples.
    """
    commands = get_all_commands()
    result = []
    for cmd in commands:
        result.append({
            "tag": cmd.tag,
            "description": cmd.description,
            "has_args": cmd.has_args,
            "args_hint": cmd.args_hint,
            "example_prompt": cmd.example_prompt,
            "example_response": cmd.example_response,
            "enabled": cmd.enabled,
        })
    return result


@app.tool()
def execute_action(tag: str, args: str = "", dry_run: bool = False) -> str:
    """
    Exécute une action système spécifique par son tag (ex: VOLUME, NOTIFY, OPEN, MEDIA_PLAY_PAUSE, LOCK, SCREEN_OFF, SHUTDOWN, REBOOT, MUTE, UNMUTE).

    Args:
        tag: Le nom du tag de commande (insensible à la casse, ex: 'VOLUME', 'NOTIFY', 'OPEN').
        args: Les arguments optionnels passés à la commande (ex: '50', 'firefox', 'Rappel réunion').
        dry_run: Si True, simule l'exécution sans modifier l'état du système.
    """
    cmd = get_command_by_tag(tag)
    if not cmd:
        return f"❌ Action inconnue : [{tag.upper()}]. Utilisez list_actions() pour consulter les actions disponibles."

    if dry_run:
        return f"🔍 [DRY RUN] Action [{cmd.tag}] simulée avec succès. Arguments: '{args}'"

    code, out, err = cmd.execute_sync(args)
    if code == 0:
        msg = f"✅ Action [{cmd.tag}] exécutée avec succès."
        if out.strip():
            msg += f" Sortie: {out.strip()}"
        return msg
    else:
        err_msg = err.strip() or out.strip() or f"Code d'erreur {code}"
        return f"⚠️ Action [{cmd.tag}] terminée avec une erreur: {err_msg}"


@app.tool()
def set_volume(volume: str) -> str:
    """
    Règle ou ajuste le volume sonore du système.

    Args:
        volume: Niveau de volume souhaité (0-100, 'up', 'down', '+5%', '-5%', 'mute', 'unmute', 'toggle').
    """
    clean_val = volume.strip().lower()
    if clean_val == "mute":
        return execute_action("MUTE")
    elif clean_val in ("unmute", "demute"):
        return execute_action("UNMUTE")
    return execute_action("VOLUME", clean_val)


@app.tool()
def media_control(command: str) -> str:
    """
    Contrôle la lecture multimédia sur les applications compatibles MPRIS2 (Spotify, Firefox, VLC, etc.).

    Args:
        command: Action multimédia à effectuer ('play-pause', 'play', 'pause', 'next', 'previous', 'stop').
    """
    cmd_clean = command.strip().lower().replace("_", "-")
    if cmd_clean in ("next", "suivant"):
        return execute_action("MEDIA_NEXT")
    elif cmd_clean in ("previous", "prev", "precedent"):
        return execute_action("MEDIA_PREV")
    else:
        return execute_action("MEDIA_PLAY_PAUSE")


@app.tool()
def send_notification(message: str, title: str = "SmartHome") -> str:
    """
    Affiche une notification visuelle sur le bureau Linux (via notify-send, kdialog ou zenity).

    Args:
        message: Le message texte à afficher dans la notification.
        title: Le titre de la notification (défaut: 'SmartHome').
    """
    args = f"{title} {message}" if title != "SmartHome" else message
    return execute_action("NOTIFY", args)


@app.tool()
def open_application(app_name: str) -> str:
    """
    Lance une application installée sur l'ordinateur par son nom ou sa catégorie.

    Args:
        app_name: Nom de l'application ou catégorie (ex: 'firefox', 'chrome', 'spotify', 'code', 'terminal', 'calculatrice', 'fichiers').
    """
    return execute_action("OPEN", app_name)


@app.tool()
def lock_session() -> str:
    """
    Verrouille immédiatement la session utilisateur courante du bureau.
    """
    return execute_action("LOCK")


@app.tool()
def screen_off() -> str:
    """
    Met les écrans en veille / éteint l'affichage (DPMS off).
    """
    return execute_action("SCREEN_OFF")


@app.tool()
def system_power(action: str) -> str:
    """
    Contrôle l'alimentation du système (extinction ou redémarrage).

    Args:
        action: Type d'action ('shutdown' pour éteindre, 'reboot' pour redémarrer).
    """
    act = action.strip().lower()
    if act in ("shutdown", "eteindre", "poweroff", "off"):
        return execute_action("SHUTDOWN")
    elif act in ("reboot", "redemarrer", "restart"):
        return execute_action("REBOOT")
    else:
        return f"⚠️ Action d'alimentation non reconnue : '{action}'. Valeurs possibles : 'shutdown', 'reboot'."


# ============================================================================
# 🔊 OUTILS MCP (TOOLS) — AUDIO, VOIX & RETOURS SONORES
# ============================================================================

@app.tool()
def tts_speak(text: str) -> str:
    """
    Synthétise et énonce vocalement le texte fourni sur les haut-parleurs via le moteur TTS configuré (Piper local ou OpenRouter).

    Args:
        text: Le texte à prononcer à haute voix.
    """
    tts = _get_tts()
    if not tts:
        return "⚠️ Synthèse vocale non disponible (TTS non initialisé)."

    clean_text = text.strip()
    if not clean_text:
        return "⚠️ Aucun texte fourni pour la synthèse vocale."

    try:
        tts.speak(clean_text)
        return f"🔊 Texte vocalisé avec succès : « {clean_text} »"
    except Exception as e:
        return f"⚠️ Erreur lors de la synthèse vocale : {e}"


@app.tool()
def play_feedback_sound(sound_name: str = "ding", volume: float = 0.5) -> str:
    """
    Joue un signal sonore doux ou un carillon harmonique procédural.

    Args:
        sound_name: Nom du son ('wake', 'ding', 'sleep', 'beep', 'pop', 'chime_up', 'chime_down').
        volume: Volume sonore entre 0.0 et 1.0 (défaut: 0.5).
    """
    feedback = _get_feedback()
    if not feedback:
        return "⚠️ Module de feedback sonore non disponible."

    try:
        feedback.play_sound(sound_name, volume=volume)
        return f"🔔 Son '{sound_name}' joué avec succès (volume {volume})."
    except Exception as e:
        return f"⚠️ Erreur lors de la lecture du son '{sound_name}' : {e}"


@app.tool()
def set_system_ducking(duck: bool = True, volume_percent: int = 20) -> str:
    """
    Atténue (ducking) ou rétablit (unducking) le volume des applications tierces (musique, vidéos, jeux).

    Args:
        duck: True pour baisser le volume des applications, False pour rétablir les volumes initiaux.
        volume_percent: Niveau sonore résiduel en % lorsque duck=True (défaut: 20%).
    """
    ducker = _get_ducker()
    if not ducker:
        return "⚠️ Module d'atténuation audio (Ducking) non disponible."

    try:
        if duck:
            success = ducker.duck(target_percent=volume_percent)
            state = "atténué" if success else "inchangé (aucun flux externe actif)"
            return f"🔉 Atténuation audio activée à {volume_percent}% ({state})."
        else:
            ducker.unduck()
            return "🔊 Volumes d'origine de toutes les applications rétablis."
    except Exception as e:
        return f"⚠️ Erreur lors de la gestion du ducking : {e}"


@app.tool()
def stt_transcribe_file(audio_path: str) -> str:
    """
    Transcrit un fichier audio (.wav) en texte à l'aide du moteur de transcription configuré (faster-whisper ou OpenRouter).

    Args:
        audio_path: Chemin absolu ou relatif vers le fichier audio à transcrire.
    """
    path = Path(audio_path).resolve()
    if not path.exists():
        return f"❌ Fichier audio introuvable : {audio_path}"

    transcriber = _get_transcriber()
    if not transcriber:
        return "⚠️ Moteur de transcription non disponible."

    try:
        if transcriber.provider == "openrouter":
            if not transcriber.client:
                return "⚠️ Client OpenRouter non configuré."
            with open(path, "rb") as f:
                data = f.read()
            audio_tuple = (path.name, data, "audio/wav")
            res = transcriber.client.audio.transcriptions.create(
                model=OPENROUTER_STT_MODEL,
                file=audio_tuple,
                language=transcriber.language if transcriber.language else None
            )
            text = res.text.strip() if hasattr(res, "text") else ""
        else:
            segments, _ = transcriber.model.transcribe(
                str(path),
                language=transcriber.language,
                beam_size=transcriber.beam_size,
                condition_on_previous_text=False
            )
            text = " ".join([seg.text for seg in segments]).strip()

        return text or "(Aucune parole détectée dans le fichier audio)"
    except Exception as e:
        return f"⚠️ Erreur lors de la transcription du fichier : {e}"


# ============================================================================
# 🧠 OUTILS MCP (TOOLS) — ASSISTANT & RAISONNEMENT
# ============================================================================

@app.tool()
def ask_assistant(prompt: str, execute_actions: bool = True, speak_response: bool = False) -> str:
    """
    Pose une question ou donne une instruction à l'assistant SmartHome (Ollama ou OpenRouter).
    L'assistant analyse la demande, génère une réponse, déclenche automatiquement les actions système reconnues si demandé, et peut vocaliser la réponse.

    Args:
        prompt: Instruction ou question en langage naturel (ex: 'Mets le volume à 30% et ouvre firefox').
        execute_actions: Si True, exécute automatiquement les commandes système détectées dans la réponse.
        speak_response: Si True, énonce la réponse de l'assistant à haute voix via TTS.
    """
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return "⚠️ Prompt vide."

    try:
        raw_response = ask_llm(prompt=clean_prompt, stream=False, use_history=True)

        processed_text = raw_response
        executed_tags = []

        if execute_actions and ACTIONS_ENABLED and raw_response:
            action_mgr = get_action_manager()
            cleaned_text, detected_actions = action_mgr.extract_actions(raw_response)
            for act in detected_actions:
                action_mgr.execute_action(act)
                executed_tags.append(act.get("tag", ""))
            processed_text = cleaned_text

        if speak_response and processed_text:
            tts = _get_tts()
            if tts:
                tts.speak(processed_text)

        summary = processed_text
        if executed_tags:
            summary += f"\n\n⚡ [Actions exécutées : {', '.join(executed_tags)}]"

        return summary
    except Exception as e:
        return f"⚠️ Erreur lors de la communication avec l'assistant : {e}"


@app.tool()
def get_conversation_history() -> list[dict]:
    """
    Retourne la liste des derniers échanges conversationnels conservés dans la mémoire de l'assistant.
    """
    return get_history()


@app.tool()
def clear_conversation_history() -> str:
    """
    Efface et réinitialise l'historique conversationnel en mémoire de l'assistant.
    """
    clear_history()
    return "🧹 Historique conversationnel réinitialisé avec succès."


# ============================================================================
# 📦 RESSOURCES MCP (RESOURCES)
# ============================================================================

@app.resource("smarthome://status")
def get_status_resource() -> str:
    """
    Retourne l'état complet en temps réel du serveur SmartHome et de ses composants sous format JSON.
    """
    commands = get_all_commands()
    history = get_history()

    status_data = {
        "server": "SmartHome MCP Server",
        "version": "1.0.0",
        "status": "online",
        "providers": {
            "llm": {
                "provider": LLM_PROVIDER,
                "model": OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else OLLAMA_MODEL,
                "host": OLLAMA_HOST if LLM_PROVIDER == "ollama" else "OpenRouter Cloud API",
            },
            "stt": {
                "provider": STT_PROVIDER,
                "model": OPENROUTER_STT_MODEL if STT_PROVIDER == "openrouter" else WHISPER_MODEL,
            },
            "tts": {
                "provider": TTS_PROVIDER,
                "voice": OPENROUTER_TTS_VOICE if TTS_PROVIDER == "openrouter" else Path(TTS_MODEL_PATH).stem,
            }
        },
        "features": {
            "actions_enabled": ACTIONS_ENABLED,
            "actions_count": len(commands),
            "dynamic_prompt": ACTIONS_DYNAMIC_PROMPT,
            "ducking_enabled": DUCKING_ENABLED,
            "ducking_volume_percent": DUCKING_VOLUME_PERCENT,
            "follow_up_timeout_seconds": FOLLOW_UP_TIMEOUT,
            "history_messages_limit": LLM_HISTORY_MESSAGES,
            "active_history_count": len(history),
        }
    }
    return json.dumps(status_data, indent=2, ensure_ascii=False)


@app.resource("smarthome://actions")
def get_actions_resource() -> str:
    """
    Retourne le catalogue complet structuré en JSON de toutes les actions et commandes disponibles.
    """
    commands = get_all_commands()
    actions_catalog = [
        {
            "tag": cmd.tag,
            "description": cmd.description,
            "has_args": cmd.has_args,
            "args_hint": cmd.args_hint,
            "example_prompt": cmd.example_prompt,
            "example_response": cmd.example_response,
            "enabled": cmd.enabled,
        }
        for cmd in commands
    ]
    return json.dumps(actions_catalog, indent=2, ensure_ascii=False)


@app.resource("smarthome://history")
def get_history_resource() -> str:
    """
    Retourne l'historique conversationnel sous forme de liste JSON.
    """
    return json.dumps(get_history(), indent=2, ensure_ascii=False)


@app.resource("smarthome://config")
def get_config_resource() -> str:
    """
    Retourne un résumé des réglages de configuration non-confidentiels sous format JSON.
    """
    cfg = {
        "LLM_PROVIDER": LLM_PROVIDER,
        "OLLAMA_MODEL": OLLAMA_MODEL,
        "OPENROUTER_MODEL": OPENROUTER_MODEL,
        "STT_PROVIDER": STT_PROVIDER,
        "WHISPER_MODEL": WHISPER_MODEL,
        "TTS_PROVIDER": TTS_PROVIDER,
        "TTS_VOICE": Path(TTS_MODEL_PATH).stem,
        "ACTIONS_ENABLED": ACTIONS_ENABLED,
        "DUCKING_ENABLED": DUCKING_ENABLED,
        "DUCKING_VOLUME_PERCENT": DUCKING_VOLUME_PERCENT,
        "FOLLOW_UP_TIMEOUT": FOLLOW_UP_TIMEOUT,
        "LLM_HISTORY_MESSAGES": LLM_HISTORY_MESSAGES,
        "MCP_TRANSPORT": MCP_TRANSPORT,
        "MCP_HOST": MCP_HOST,
        "MCP_PORT": MCP_PORT,
    }
    return json.dumps(cfg, indent=2, ensure_ascii=False)


# ============================================================================
# 💬 PROMPTS MCP (PROMPTS)
# ============================================================================

@app.prompt("smarthome_assistant")
def prompt_smarthome_assistant() -> str:
    """
    Retourne le prompt système complet de SmartHome configuré dynamiquement avec les commandes d'action.
    """
    return get_default_system_prompt()


@app.prompt("smart_home_planner")
def prompt_automation_planner() -> str:
    """
    Modèle de prompt spécialisé pour planifier des séquences domotiques complexes et des automatisations système.
    """
    commands = get_all_commands()
    cmd_list = "\n".join([f"- [{c.tag}]: {c.description}" for c in commands])

    return f"""Tu es l'architecte domotique de SmartHome.
Ton objectif est de décomposer les requêtes utilisateur en séquences précises d'actions exécutables.

Actions disponibles sur cette machine :
{cmd_list}

Instructions :
1. Analyse l'intention utilisateur.
2. Détermine la chronologie des commandes à exécuter.
3. Formate la réponse en utilisant les tags d'actions appropriés.
4. Ajoute une synthèse vocale concise pour confirmer l'exécution.
"""


# ============================================================================
# 🚀 POINT D'ENTRÉE & EXÉCUTION
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Serveur MCP SmartHome (Model Context Protocol) pour automatisation domotique et contrôle OS."
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=MCP_TRANSPORT or "stdio",
        help="Protocole de transport MCP ('stdio' pour clients locaux, 'sse' ou 'streamable-http' pour accès réseau/HTTP)."
    )
    parser.add_argument(
        "--host",
        default=MCP_HOST or "0.0.0.0",
        help="Adresse d'écoute pour les modes SSE / HTTP (défaut: 0.0.0.0)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=MCP_PORT or 8000,
        help="Port d'écoute pour les modes SSE / HTTP (défaut: 8000)."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    transport = args.transport
    host = args.host
    port = args.port

    if transport == "stdio":
        # En mode stdio, aucun message stdout superflu ne doit polluer le flux JSON-RPC
        app.run(transport="stdio")
    elif transport == "sse":
        print(f"🚀 [MCP] Démarrage du serveur SmartHome en mode SSE sur http://{host}:{port}/sse ...", file=sys.stderr)
        app.run(transport="sse", host=host, port=port)
    elif transport == "streamable-http":
        print(f"🚀 [MCP] Démarrage du serveur SmartHome en mode Streamable-HTTP sur http://{host}:{port}/mcp ...", file=sys.stderr)
        app.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
