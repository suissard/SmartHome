"""
Paramètres modifiables à chaud depuis l'interface web : description (type, choix, aide), validation et écriture dans `.env`.

Seuls les champs listés dans `EDITABLE_GROUPS` sont exposés : jamais les secrets (clés, jetons) ni l'exposition réseau
(hôtes, ports), qui restent réservés au fichier `.env`. Chaque champ indique s'il s'applique immédiatement (lu par
AssistantCore à chaque demande) ou seulement au prochain démarrage (lu une fois par main.py, le micro, la voix...).
L'aide affichée est le commentaire qui précède la variable dans `.env.example`.
"""

import json
import re
import sys
import typing
from pathlib import Path
from typing import Any, Optional

import annotated_types
from pydantic import ValidationError

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import BASE_DIR, ENV_FILE, Settings
from core.profiles import local_overrides_path, profile_values

LIVE, RESTART = True, False

# (titre, [(variable, libellé, appliqué immédiatement ?)])
EDITABLE_GROUPS: list[tuple[str, list[tuple[str, str, bool]]]] = [
    ("1. Entrée Audio & Détection", [
        ("WAKEWORD_ENABLED", "Écoute du mot-clé sur l'ordinateur", LIVE),
        ("WAKEWORD_THRESHOLD", "Sensibilité du mot-clé (0-1)", RESTART),
        ("VAD_ENGINE", "Moteur de détection vocale (VAD)", RESTART),
        ("VAD_SPEECH_THRESHOLD", "Probabilité de voix Silero", RESTART),
        ("VOICE_THRESHOLD", "Seuil d'énergie sonore", RESTART),
        ("SILENCE_DURATION", "Silence de fin de phrase (s)", RESTART),
        ("MAX_SPEECH_DURATION", "Durée maximale de parole (s)", RESTART),
        ("BARGE_IN_MODE", "Interruption (barge-in)", RESTART),
        ("BARGE_IN_VOICE_THRESHOLD", "Seuil de voix (mode interruption voice)", RESTART),
        ("BARGE_IN_MIN_DURATION", "Durée de voix pour couper (s)", RESTART),
        ("REMOTE_VOICE_SLEEP", "Veille quand le micro du téléphone est utilisé", RESTART),
        ("REMOTE_VOICE_HOLD", "Délai de garde après le micro du téléphone (s)", RESTART),
        ("FEEDBACK_WAKEWORD_TYPE", "Signal au mot-clé", RESTART),
        ("FEEDBACK_WAKEWORD_SOUND", "Son au mot-clé", RESTART),
        ("FEEDBACK_WAKEWORD_TEXT", "Phrase au mot-clé", RESTART),
    ]),
    ("2. Écoute & Transcription (STT)", [
        ("STT_PROVIDER", "Fournisseur de transcription", RESTART),
        ("STT_FALLBACK_PROVIDER", "Transcription de repli (si le LLM ne gère pas l'audio)", LIVE),
        ("WHISPER_MODEL", "Modèle Whisper", RESTART),
        ("WHISPER_BEAM_SIZE", "Beam size Whisper", RESTART),
        ("WHISPER_VAD_FILTER", "Filtre VAD Whisper", RESTART),
        ("OLLAMA_STT_MODEL", "Modèle STT Ollama", RESTART),
        ("OPENROUTER_STT_MODEL", "Modèle STT OpenRouter", RESTART),
    ]),
    ("3. Cerveau & Intelligence (LLM)", [
        ("ASSISTANT_NAME", "Nom de l'assistant", LIVE),
        ("LLM_PROVIDER", "Fournisseur LLM", LIVE),
        ("OPENROUTER_API_KEY", "Clé API OpenRouter", LIVE),
        ("OLLAMA_MODEL", "Modèle Ollama", LIVE),
        ("OPENROUTER_MODEL", "Modèle OpenRouter", LIVE),
        ("LLM_AUDIO_INPUT", "Mode direct : envoyer l'audio au LLM", LIVE),
        ("LLM_IMAGE_INPUT", "Envoyer les images jointes au LLM", LIVE),
        ("LLM_DECISION_MODELS", "Modèles de décision reconnus", LIVE),
        ("LLM_SYSTEM_PROMPT", "Prompt système", LIVE),
        ("LLM_INJECT_DATETIME", "Date et heure dans le prompt", LIVE),
        ("LLM_THINK", "Réflexion (thinking)", LIVE),
        ("LLM_HISTORY_MESSAGES", "Messages gardés en mémoire", LIVE),
        ("LLM_TOOL_CALLING", "Appel d'outils", LIVE),
        ("LLM_MAX_TOOL_ROUNDS", "Allers-retours d'outils max.", LIVE),
        ("CONVERSATION_END_PHRASES", "Phrases de fin de conversation", LIVE),
        ("CONVERSATION_END_FILLERS", "Mots ignorés autour de la fin", LIVE),
        ("FOLLOW_UP_TIMEOUT", "Écoute active après réponse (s)", RESTART),
    ]),
    ("Modèle de décision", [
        ("LLM_DECISION_PROMPT", "Question de choix de la commande", LIVE),
        ("LLM_DECISION_MIN_CONFIDENCE", "Confiance minimale", LIVE),
        ("LLM_DECISION_MESSAGES", "Messages de confirmation par commande", LIVE),
        ("LLM_DECISION_DONE_TEMPLATE", "Réponse type : commande exécutée", LIVE),
        ("LLM_DECISION_DONE_NO_ARGS_TEMPLATE", "Réponse type : commande sans argument", LIVE),
        ("LLM_DECISION_REFUSED_TEMPLATE", "Réponse : commande non exécutée", LIVE),
        ("LLM_DECISION_UNKNOWN_TEXT", "Réponse : rien compris", LIVE),
        ("LLM_DECISION_TIMEOUT", "Délai maximal (s)", LIVE),
    ]),
    ("4. Actions & Domotique", [
        ("ACTIONS_ENABLED", "Actions système", LIVE),
        ("ACTIONS_OPEN_ALLOWED_APPS", "Applications autorisées", RESTART),
        ("ACTIONS_CONFIRM_DANGEROUS", "Confirmer les actions sensibles", LIVE),
        ("ACTIONS_CONFIRM_TIMEOUT", "Délai de confirmation vocale (s)", RESTART),
        ("ACTIONS_CONFIRM_PROMPT", "Question de confirmation vocale", LIVE),
        # Seul le modèle est modifiable ici : la commande de l'agent reste dans .env (un admin n'est pas superadmin)
        ("ACTIONS_AGENT_MODEL", "Modèle de l'agent créateur de commandes", LIVE),
        # Agents externes (agents.json) : les rôles autorisés et les commandes restent dans les fichiers
        ("AGENTS_ENABLED", "Agents externes (Hermes, Claude...)", LIVE),
        ("AGENTS_DEFAULT_VOICE", "Voix des agents sans voix attitrée", LIVE),
        ("AGENTS_SWITCH_MESSAGE", "Annonce de l'agent", LIVE),
        ("AGENTS_RETURN_MESSAGE", "Annonce du retour à l'assistant", LIVE),
        ("AGENTS_LEAVE_ON_SLEEP", "Retour à l'assistant à la mise en veille", LIVE),
        ("AGENTS_TIMEOUT", "Délai maximal d'une réponse d'agent (s)", LIVE),
        # Images de l'interface web et dossiers de recherche (l'assistant ne peut pas modifier ces dossiers lui-même)
        ("IMAGES_ENABLED", "Images dans la conversation", LIVE),
        ("IMAGES_MAX_BYTES", "Taille maximale d'une image (octets)", LIVE),
        ("IMAGES_NO_VISION_MESSAGE", "Alerte : modèle sans vision", LIVE),
        ("FILES_SEARCH_DIRS", "Dossiers où l'assistant peut chercher", LIVE),
        ("FILES_SEARCH_MAX_RESULTS", "Résultats de recherche max.", LIVE),
        ("FILES_SEARCH_MAX_DEPTH", "Profondeur de recherche max.", LIVE),
    ]),
    ("5. Synthèse Vocale (TTS)", [
        ("TTS_PROVIDER", "Moteur de voix", RESTART),
        ("TTS_VOICE", "Voix Piper", RESTART),
        ("OLLAMA_TTS_MODEL", "Modèle vocal Ollama", RESTART),
        ("OLLAMA_TTS_VOICE", "Voix Ollama", RESTART),
        ("OPENROUTER_TTS_MODEL", "Modèle vocal OpenRouter", RESTART),
        ("OPENROUTER_TTS_VOICE", "Voix OpenRouter", RESTART),
        ("TTS_SPEECH_SPEED", "Vitesse de parole", RESTART),
        ("TTS_STREAMING", "Parler phrase par phrase", LIVE),
        ("TTS_STREAM_MIN_CHARS", "Longueur minimale d'un morceau", LIVE),
        ("TTS_SILENCE_START_DURATION", "Silence avant parole (anti-coupure HDMI/DAC)", RESTART),
    ]),
    ("6. Restitution & Environnement Audio", [
        ("MEDIA_PAUSE_ENABLED", "Mettre les médias en pause (MPRIS)", RESTART),
        ("DUCKING_ENABLED", "Atténuation sonore des autres applis (Ducking)", RESTART),
        ("DUCKING_VOLUME_PERCENT", "Volume atténué (%)", RESTART),
        ("FEEDBACK_RESPONSE_END_TYPE", "Signal en fin de réponse", RESTART),
        ("FEEDBACK_RESPONSE_END_SOUND", "Son en fin de réponse", RESTART),
        ("FEEDBACK_RESPONSE_END_TEXT", "Phrase en fin de réponse", RESTART),
        ("FEEDBACK_TIMEOUT_TYPE", "Signal à la mise en veille", RESTART),
        ("FEEDBACK_TIMEOUT_SOUND", "Son à la mise en veille", RESTART),
        ("FEEDBACK_TIMEOUT_TEXT", "Phrase de mise en veille", RESTART),
        ("FEEDBACK_SOUND_VOLUME", "Volume des effets sonores", RESTART),
    ]),
    ("7. Mémoire, Rappels & Mesures", [
        ("MEMORY_ENABLED", "Mémoire à long terme (souvenirs par compte)", RESTART),
        ("MEMORY_EMBED_MODEL", "Modèle d'embeddings Ollama (vide : mots communs)", LIVE),
        ("MEMORY_ALWAYS_INCLUDE", "Souvenirs toujours tous donnés jusqu'à", LIVE),
        ("MEMORY_RECALL_LIMIT", "Souvenirs donnés au plus (au-delà)", LIVE),
        ("SCHEDULER_ENABLED", "Rappels et routines programmés", RESTART),
        ("SCHEDULER_LOCAL_ANNOUNCE", "Rappels dits sur l'ordinateur", LIVE),
        ("SCHEDULER_SOUND", "Son avant un rappel", LIVE),
        ("SCHEDULER_REMINDER_TEMPLATE", "Phrase d'un rappel", LIVE),
        ("SCHEDULER_DEFAULT_HOUR", "Heure d'un rappel donné sans heure", LIVE),
        ("METRICS_ENABLED", "Mesure de la latence de chaque tour", LIVE),
    ]),
]

# Champs affichés seulement si le réglage correspond : liste d'alternatives {variable: valeurs admises}.
# LLM_MODE est calculé par l'interface : "decision" si le modèle Ollama actif est un modèle de décision, sinon "language".
_DIRECT_STT = ["direct", "none", "bypass"]
_LANGUAGE_MODEL = [{"LLM_MODE": ["language"]}]
_DECISION_MODEL = [{"LLM_MODE": ["decision"]}]


def _stt_engine(name: str) -> list[dict]:
    """Moteur de transcription utilisé, directement ou en repli du mode direct."""
    return [{"STT_PROVIDER": [name]}, {"STT_PROVIDER": _DIRECT_STT, "STT_FALLBACK_PROVIDER": [name]}]


VISIBLE_WHEN: dict[str, list[dict]] = {
    # 1. Entrée Audio & Détection
    "WAKEWORD_THRESHOLD": [{"WAKEWORD_ENABLED": [True]}],
    "VAD_SPEECH_THRESHOLD": [{"VAD_ENGINE": ["silero"]}],
    "VOICE_THRESHOLD": [{"VAD_ENGINE": ["energy"]}],
    "BARGE_IN_VOICE_THRESHOLD": [{"BARGE_IN_MODE": ["voice"]}],
    "BARGE_IN_MIN_DURATION": [{"BARGE_IN_MODE": ["voice"]}],
    "REMOTE_VOICE_HOLD": [{"REMOTE_VOICE_SLEEP": [True]}],
    "FEEDBACK_WAKEWORD_SOUND": [{"FEEDBACK_WAKEWORD_TYPE": ["sound"]}],
    "FEEDBACK_WAKEWORD_TEXT": [{"FEEDBACK_WAKEWORD_TYPE": ["phrase"]}],
    "MEMORY_EMBED_MODEL": [{"MEMORY_ENABLED": [True]}],
    "MEMORY_ALWAYS_INCLUDE": [{"MEMORY_ENABLED": [True]}],
    "MEMORY_RECALL_LIMIT": [{"MEMORY_ENABLED": [True]}],
    "SCHEDULER_LOCAL_ANNOUNCE": [{"SCHEDULER_ENABLED": [True]}],
    "SCHEDULER_SOUND": [{"SCHEDULER_ENABLED": [True]}],
    "SCHEDULER_REMINDER_TEMPLATE": [{"SCHEDULER_ENABLED": [True]}],
    "SCHEDULER_DEFAULT_HOUR": [{"SCHEDULER_ENABLED": [True]}],

    # 2. STT
    "STT_FALLBACK_PROVIDER": [{"STT_PROVIDER": _DIRECT_STT}],
    "WHISPER_MODEL": _stt_engine("whisper"),
    "WHISPER_BEAM_SIZE": _stt_engine("whisper"),
    "WHISPER_VAD_FILTER": _stt_engine("whisper"),
    "OLLAMA_STT_MODEL": _stt_engine("ollama"),
    "OPENROUTER_STT_MODEL": _stt_engine("openrouter"),

    # 3. LLM
    "OLLAMA_MODEL": [{"LLM_PROVIDER": ["ollama"]}],
    "OPENROUTER_MODEL": [{"LLM_PROVIDER": ["openrouter"]}],
    "OPENROUTER_API_KEY": [
        {"LLM_PROVIDER": ["openrouter"]},
        {"STT_PROVIDER": ["openrouter"]},
        {"STT_PROVIDER": _DIRECT_STT, "STT_FALLBACK_PROVIDER": ["openrouter"]},
        {"TTS_PROVIDER": ["openrouter"]},
    ],
    "LLM_AUDIO_INPUT": [{"STT_PROVIDER": _DIRECT_STT, "LLM_MODE": ["language"]}],
    "LLM_DECISION_MODELS": _DECISION_MODEL,
    "LLM_DECISION_PROMPT": _DECISION_MODEL,
    "LLM_DECISION_MIN_CONFIDENCE": _DECISION_MODEL,
    "LLM_DECISION_MESSAGES": _DECISION_MODEL,
    "LLM_DECISION_DONE_TEMPLATE": _DECISION_MODEL,
    "LLM_DECISION_DONE_NO_ARGS_TEMPLATE": _DECISION_MODEL,
    "LLM_DECISION_REFUSED_TEMPLATE": _DECISION_MODEL,
    "LLM_DECISION_UNKNOWN_TEXT": _DECISION_MODEL,
    "LLM_DECISION_TIMEOUT": _DECISION_MODEL,
    "LLM_SYSTEM_PROMPT": _LANGUAGE_MODEL,
    "LLM_INJECT_DATETIME": _LANGUAGE_MODEL,
    "LLM_THINK": _LANGUAGE_MODEL,
    "LLM_TOOL_CALLING": _LANGUAGE_MODEL,
    "LLM_MAX_TOOL_ROUNDS": _LANGUAGE_MODEL,

    # 4. Actions
    "ACTIONS_OPEN_ALLOWED_APPS": [{"ACTIONS_ENABLED": [True]}],
    "ACTIONS_CONFIRM_DANGEROUS": [{"ACTIONS_ENABLED": [True]}],
    "ACTIONS_CONFIRM_TIMEOUT": [{"ACTIONS_ENABLED": [True], "ACTIONS_CONFIRM_DANGEROUS": [True]}],
    "ACTIONS_CONFIRM_PROMPT": [{"ACTIONS_ENABLED": [True], "ACTIONS_CONFIRM_DANGEROUS": [True]}],
    **{name: [{"AGENTS_ENABLED": [True]}] for name in (
        "AGENTS_DEFAULT_VOICE", "AGENTS_SWITCH_MESSAGE", "AGENTS_RETURN_MESSAGE", "AGENTS_LEAVE_ON_SLEEP",
        "AGENTS_TIMEOUT")},
    **{name: [{"IMAGES_ENABLED": [True]}] for name in ("IMAGES_MAX_BYTES", "IMAGES_NO_VISION_MESSAGE")},

    # 5. TTS
    "TTS_VOICE": [{"TTS_PROVIDER": ["piper"]}],
    "OLLAMA_TTS_MODEL": [{"TTS_PROVIDER": ["ollama"]}],
    "OLLAMA_TTS_VOICE": [{"TTS_PROVIDER": ["ollama"]}],
    "OPENROUTER_TTS_MODEL": [{"TTS_PROVIDER": ["openrouter"]}],
    "OPENROUTER_TTS_VOICE": [{"TTS_PROVIDER": ["openrouter"]}],
    "TTS_SPEECH_SPEED": [{"TTS_PROVIDER": ["piper", "openrouter"]}],  # Ollama : vitesse 1 seulement
    "TTS_STREAM_MIN_CHARS": [{"TTS_STREAMING": [True]}],

    # 6. Restitution & Environnement
    "DUCKING_ENABLED": [{"MEDIA_PAUSE_ENABLED": [False]}],
    "DUCKING_VOLUME_PERCENT": [{"MEDIA_PAUSE_ENABLED": [False], "DUCKING_ENABLED": [True]}],
    "FEEDBACK_RESPONSE_END_SOUND": [{"FEEDBACK_RESPONSE_END_TYPE": ["sound"]}],
    "FEEDBACK_RESPONSE_END_TEXT": [{"FEEDBACK_RESPONSE_END_TYPE": ["phrase"]}],
    "FEEDBACK_TIMEOUT_SOUND": [{"FEEDBACK_TIMEOUT_TYPE": ["sound"]}],
    "FEEDBACK_TIMEOUT_TEXT": [{"FEEDBACK_TIMEOUT_TYPE": ["phrase"]}],
}

EDITABLE: dict[str, tuple[str, bool]] = {name: (label, live) for _, fields in EDITABLE_GROUPS for name, label, live in fields}
# Textes longs : zone de saisie multiligne
_MULTILINE = {"LLM_SYSTEM_PROMPT", "LLM_DECISION_PROMPT", "CONVERSATION_END_PHRASES", "ACTIONS_OPEN_ALLOWED_APPS"}
_ENV_EXAMPLE = BASE_DIR / ".env.example"


def _help_texts(path: Path = _ENV_EXAMPLE) -> dict[str, str]:
    """Commentaire qui précède chaque variable dans .env.example (les titres de section sont ignorés)."""
    helps, buffer = {}, []
    if not path.exists():
        return helps
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            buffer = []
        elif stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if set(text) <= {"-", "="}:
                buffer = []
            elif text:
                buffer.append(text)
        elif "=" in stripped:
            helps.setdefault(stripped.split("=", 1)[0].strip(), " ".join(buffer))
            buffer = []
    return helps


def _provider_names(kind: str) -> list[str]:
    try:
        if kind == "LLM":
            from llm.providers import LLM_PROVIDERS as registry
        elif kind == "STT":
            from audio.stt import STT_PROVIDERS as registry
        else:
            from audio.tts import TTS_PROVIDERS as registry
        return registry.names()
    except Exception:
        return []


def _field_spec(name: str) -> dict:
    """Type de saisie d'un champ, d'après son annotation dans `Settings`."""
    info = Settings.model_fields[name]
    annotation = info.annotation
    spec: dict[str, Any] = {}
    if typing.get_origin(annotation) is typing.Literal:
        spec = {"kind": "select", "options": list(typing.get_args(annotation))}
    elif annotation is bool:
        spec = {"kind": "bool"}
    elif typing.get_origin(annotation) is list:
        spec = {"kind": "list", "multiline": name in _MULTILINE}
    elif typing.get_origin(annotation) is dict:
        spec = {"kind": "json"}
    elif annotation in (int, float):
        spec = {"kind": "number", "step": 1 if annotation is int else "any"}
        for constraint in info.metadata:
            if isinstance(constraint, (annotated_types.Ge, annotated_types.Gt)):
                spec["min"] = getattr(constraint, "ge", getattr(constraint, "gt", None))
            elif isinstance(constraint, (annotated_types.Le, annotated_types.Lt)):
                spec["max"] = getattr(constraint, "le", getattr(constraint, "lt", None))
    else:
        spec = {"kind": "text", "multiline": name in _MULTILINE}

    # Choix connus pour certains champs texte
    if name == "OPENROUTER_API_KEY":
        spec = {"kind": "password", "placeholder": "sk-or-v1-..."}
    elif name in ("LLM_PROVIDER", "STT_PROVIDER", "TTS_PROVIDER"):
        spec = {"kind": "select", "options": _provider_names(name.split("_")[0])}
    elif name == "STT_FALLBACK_PROVIDER":
        spec = {"kind": "select", "options": [n for n in _provider_names("STT") if n != "direct"]}
    elif name == "TTS_VOICE":
        voices = sorted(p.stem for p in (BASE_DIR / "voices").glob("*.onnx"))
        spec = {"kind": "select", "options": voices} if voices else spec
    elif name in ("OLLAMA_MODEL", "OPENROUTER_MODEL"):
        spec = {"kind": "model"}  # liste fournie à part par le fournisseur (message "list_models")
    elif name == "LLM_DECISION_MESSAGES":
        try:
            from actions.registry import get_all_commands
            spec["defaults"] = {a.tool_name: a.done_message for a in get_all_commands()}
        except Exception:
            pass
    return spec


_SECRET_FIELDS = frozenset({"OPENROUTER_API_KEY"})


def describe(settings: Settings) -> list[dict]:
    """Groupes de champs modifiables avec leur valeur actuelle, prêts à afficher dans un formulaire."""
    helps = _help_texts()
    values = settings.model_dump()
    groups = []
    for title, fields in EDITABLE_GROUPS:
        rendered = []
        for name, label, live in fields:
            is_secret = name in _SECRET_FIELDS
            entry = {
                "name": name,
                "label": label,
                "live": live,
                "help": helps.get(name, ""),
                "value": "" if is_secret else values[name],
                "when": VISIBLE_WHEN.get(name),
                **_field_spec(name),
            }
            if is_secret:
                entry["configured"] = bool(values[name])
            rendered.append(entry)
        groups.append({"title": title, "fields": rendered})
    return groups


def validate_changes(settings: Settings, changes: dict) -> tuple[Settings, list[str]]:
    """Retourne la nouvelle configuration et la liste des champs réellement modifiés. Lève ValueError si invalide."""
    unknown = sorted(set(changes) - set(EDITABLE))
    if unknown:
        raise ValueError(f"Paramètre non modifiable depuis l'interface : {', '.join(unknown)}")
    current = settings.model_dump()
    changed = [name for name, value in changes.items() if value != current[name]]
    if not changed:
        return settings, []
    try:
        # exclude_unset : un champ jamais défini garde son statut (ex: TTS_VOICE, résolu différemment s'il est explicite)
        new = Settings.model_validate({**settings.model_dump(exclude_unset=True), **{n: changes[n] for n in changed}})
    except ValidationError as e:
        details = "; ".join(f"{EDITABLE.get(str(err['loc'][0]), ('?',))[0]} : {err['msg']}" for err in e.errors())
        raise ValueError(f"Valeur invalide — {details}") from None
    current_new = new.model_dump()
    return new, [name for name in changed if current_new[name] != current[name]]


def to_env_value(value: Any) -> str:
    """Valeur au format .env (booléens en minuscules, listes séparées par des virgules, guillemets si nécessaire)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (list, tuple)):
        text = ",".join(str(v) for v in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    if re.search(r"[\s#'\"\\]", text):
        text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def save_to_env(settings: Settings, names: list[str], env_file: Path = ENV_FILE):
    """Écrit les champs dans le fichier .env en conservant les commentaires et l'ordre (ajout en fin de fichier sinon)."""
    created = not env_file.exists()
    lines = env_file.read_text(encoding="utf-8").splitlines() if not created else []
    values = settings.model_dump()
    for name in names:
        entry = f"{name}={to_env_value(values[name])}"
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
        index = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
        if index is None:
            lines.append(entry)
        else:
            lines[index] = entry
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if created:
        try:
            env_file.chmod(0o600)
        except OSError:
            pass


def save_changes(settings: Settings, names: list[str], env_file: Path = ENV_FILE):
    """Enregistre les champs modifiés. Ceux que définit le profil actif vont dans sa surcharge locale :
    écrits dans .env, ils seraient masqués par le profil au redémarrage."""
    from_profile = profile_values() if env_file == ENV_FILE else {}
    in_profile = [name for name in names if name in from_profile]
    if in_profile:
        save_to_env(settings, in_profile, local_overrides_path())
    others = [name for name in names if name not in from_profile]
    if others:
        save_to_env(settings, others, env_file)


def set_fields(settings: Settings, updates: dict[str, Any], env_file: Optional[Path] = None) -> tuple[Settings, list[str]]:
    """Valide et enregistre n'importe quel champ de `Settings` (utilisé par la CLI `smarthome config`)."""
    target = ENV_FILE if env_file is None else env_file
    known = set(Settings.model_fields)
    unknown = sorted(set(updates) - known)
    if unknown:
        raise ValueError(f"Paramètre inconnu : {', '.join(unknown)}")
    current = settings.model_dump()
    changed_candidates = [name for name, value in updates.items() if value != current[name]]
    if not changed_candidates:
        return settings, []
    try:
        new = Settings.model_validate({**settings.model_dump(exclude_unset=True), **{n: updates[n] for n in changed_candidates}})
    except ValidationError as e:
        details = "; ".join(f"{err['loc'][0]} : {err['msg']}" for err in e.errors())
        raise ValueError(f"Valeur invalide — {details}") from None
    current_new = new.model_dump()
    changed = [name for name in changed_candidates if current_new[name] != current[name]]
    if changed:
        save_changes(new, changed, target)
    return new, changed


def unset_field(name: str, env_file: Optional[Path] = None) -> bool:
    """Supprime une clé du fichier de configuration (et de la surcharge locale du profil) pour revenir au défaut."""
    target = ENV_FILE if env_file is None else env_file
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
    removed = False
    paths = [target]
    if target == ENV_FILE:
        paths.append(local_overrides_path())
    for path in paths:
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not pattern.match(line)]
        if len(kept) != len(lines):
            path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
            removed = True
    return removed


# Cœur qui applique les changements demandés par l'assistant lui-même (actions/modules/assistant_settings.py).
# Conservé ici et non dans le module d'action, que le registre d'actions peut recharger.
_owner = None


def set_owner(core):
    """Installé par AssistantCore : ses update_settings() et bus d'événements servent aux outils de l'assistant."""
    global _owner
    _owner = core


def get_owner():
    return _owner


def overridden_by_environment(names: list[str]) -> list[str]:
    """Champs masqués par une variable d'environnement (vide : les réglages utilisateur supplantent la machine)."""
    return []


if __name__ == "__main__":
    from core.config import get_settings
    print(f"🧪 [DEBUG] Paramètres modifiables depuis l'interface web (fichier : {ENV_FILE})")
    for group in describe(get_settings()):
        print(f"\n  {group['title']}")
        for f in group["fields"]:
            when = "immédiat" if f["live"] else "au redémarrage"
            shown = ("***" if f.get("configured") else "") if f["name"] in _SECRET_FIELDS else f["value"]
            print(f"    • {f['name']:<30} {f['kind']:<7} {when:<15} = {shown!r}")
