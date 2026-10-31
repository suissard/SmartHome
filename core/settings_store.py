"""
Paramètres modifiables à chaud depuis l'interface web : description (type, choix, aide), validation et écriture dans `.env`.

Seuls les champs listés dans `EDITABLE_GROUPS` sont exposés : jamais les secrets (clés, jetons) ni l'exposition réseau
(hôtes, ports), qui restent réservés au fichier `.env`. Chaque champ indique s'il s'applique immédiatement (lu par
AssistantCore à chaque demande) ou seulement au prochain démarrage (lu une fois par main.py, le micro, la voix...).
L'aide affichée est le commentaire qui précède la variable dans `.env.example`.
"""

import os
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

LIVE, RESTART = True, False

# (titre, [(variable, libellé, appliqué immédiatement ?)])
EDITABLE_GROUPS: list[tuple[str, list[tuple[str, str, bool]]]] = [
    ("Modèle de langage", [
        ("LLM_PROVIDER", "Fournisseur", LIVE),
        ("OLLAMA_MODEL", "Modèle Ollama", LIVE),
        ("LLM_DECISION_MODELS", "Modèles de décision", LIVE),
        ("OPENROUTER_MODEL", "Modèle OpenRouter", LIVE),
        ("LLM_SYSTEM_PROMPT", "Prompt système", LIVE),
        ("LLM_THINK", "Réflexion (thinking)", LIVE),
        ("LLM_HISTORY_MESSAGES", "Messages gardés en mémoire", LIVE),
        ("LLM_TOOL_CALLING", "Appel d'outils", LIVE),
        ("LLM_MAX_TOOL_ROUNDS", "Allers-retours d'outils max.", LIVE),
    ]),
    ("Modèle de décision", [
        ("LLM_DECISION_PROMPT", "Question de choix de la commande", LIVE),
        ("LLM_DECISION_MIN_CONFIDENCE", "Confiance minimale", LIVE),
        ("LLM_DECISION_DONE_TEMPLATE", "Réponse : commande exécutée", LIVE),
        ("LLM_DECISION_REFUSED_TEMPLATE", "Réponse : commande non exécutée", LIVE),
        ("LLM_DECISION_UNKNOWN_TEXT", "Réponse : rien compris", LIVE),
        ("LLM_DECISION_TIMEOUT", "Délai maximal (s)", LIVE),
    ]),
    ("Conversation", [
        ("CONVERSATION_END_PHRASES", "Phrases de fin de conversation", LIVE),
        ("CONVERSATION_END_FILLERS", "Mots ignorés autour", LIVE),
        ("FOLLOW_UP_TIMEOUT", "Écoute après une réponse (s)", RESTART),
    ]),
    ("Voix", [
        ("TTS_PROVIDER", "Fournisseur", RESTART),
        ("TTS_VOICE", "Voix Piper", RESTART),
        ("TTS_SPEECH_SPEED", "Vitesse", RESTART),
        ("TTS_STREAMING", "Parler phrase par phrase", LIVE),
        ("TTS_STREAM_MIN_CHARS", "Longueur minimale d'un morceau", LIVE),
    ]),
    ("Écoute", [
        ("STT_PROVIDER", "Transcription", RESTART),
        ("WHISPER_MODEL", "Modèle Whisper", RESTART),
        ("WHISPER_BEAM_SIZE", "Beam size Whisper", RESTART),
        ("VOICE_THRESHOLD", "Seuil de voix", RESTART),
        ("SILENCE_DURATION", "Silence de fin de phrase (s)", RESTART),
        ("MAX_SPEECH_DURATION", "Durée maximale de parole (s)", RESTART),
        ("VAD_ENGINE", "Détection de la parole", RESTART),
        ("VAD_SPEECH_THRESHOLD", "Probabilité de voix", RESTART),
        ("WAKEWORD_THRESHOLD", "Seuil du mot-clé", RESTART),
        ("BARGE_IN_MODE", "Interruption (barge-in)", RESTART),
    ]),
    ("Retours sonores", [
        ("FEEDBACK_WAKEWORD_TYPE", "Au mot-clé", RESTART),
        ("FEEDBACK_WAKEWORD_TEXT", "Phrase au mot-clé", RESTART),
        ("FEEDBACK_RESPONSE_END_TYPE", "En fin de réponse", RESTART),
        ("FEEDBACK_TIMEOUT_TYPE", "À la mise en veille", RESTART),
        ("FEEDBACK_TIMEOUT_TEXT", "Phrase de mise en veille", RESTART),
        ("FEEDBACK_SOUND_VOLUME", "Volume des sons", RESTART),
        ("DUCKING_ENABLED", "Baisser les autres sons", RESTART),
        ("DUCKING_VOLUME_PERCENT", "Volume des autres sons (%)", RESTART),
    ]),
    ("Actions", [
        ("ACTIONS_ENABLED", "Actions système", LIVE),
        ("ACTIONS_CONFIRM_DANGEROUS", "Confirmer les actions dangereuses", LIVE),
        ("ACTIONS_CONFIRM_TIMEOUT", "Délai de confirmation vocale (s)", RESTART),
        ("ACTIONS_OPEN_ALLOWED_APPS", "Applications autorisées", RESTART),
    ]),
]

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
    if name in ("LLM_PROVIDER", "STT_PROVIDER", "TTS_PROVIDER"):
        spec = {"kind": "select", "options": _provider_names(name.split("_")[0])}
    elif name == "TTS_VOICE":
        voices = sorted(p.stem for p in (BASE_DIR / "voices").glob("*.onnx"))
        spec = {"kind": "select", "options": voices} if voices else spec
    elif name == "OLLAMA_MODEL":
        spec = {"kind": "model"}  # liste fournie à part par le fournisseur (message "list_models")
    return spec


def describe(settings: Settings) -> list[dict]:
    """Groupes de champs modifiables avec leur valeur actuelle, prêts à afficher dans un formulaire."""
    helps = _help_texts()
    values = settings.model_dump()
    groups = []
    for title, fields in EDITABLE_GROUPS:
        groups.append({"title": title, "fields": [
            {"name": name, "label": label, "live": live, "help": helps.get(name, ""), "value": values[name], **_field_spec(name)}
            for name, label, live in fields
        ]})
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
    else:
        text = str(value)
    if re.search(r"[\s#'\"\\]", text):
        text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def save_to_env(settings: Settings, names: list[str], env_file: Path = ENV_FILE):
    """Écrit les champs dans le fichier .env en conservant les commentaires et l'ordre (ajout en fin de fichier sinon)."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    values = settings.model_dump()
    for name in names:
        entry = f"{name}={to_env_value(values[name])}"
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
        index = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
        if index is None:
            lines.append(entry)
        else:
            lines[index] = entry
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def overridden_by_environment(names: list[str]) -> list[str]:
    """Champs masqués par une variable d'environnement : elle restera prioritaire sur .env au prochain démarrage."""
    return [name for name in names if (os.environ.get(name) or "").strip()]


if __name__ == "__main__":
    from core.config import get_settings
    print(f"🧪 [DEBUG] Paramètres modifiables depuis l'interface web (fichier : {ENV_FILE})")
    for group in describe(get_settings()):
        print(f"\n  {group['title']}")
        for f in group["fields"]:
            when = "immédiat" if f["live"] else "au redémarrage"
            print(f"    • {f['name']:<30} {f['kind']:<7} {when:<15} = {f['value']!r}")
