"""
Configuration typée et validée de SmartHome.

Ordre de priorité des valeurs : variables d'environnement > fichier .env > valeurs par défaut.
Le fichier lu peut être changé via SMARTHOME_ENV_FILE (ex: profils `.env.local`, `.env.cloud`).

Le nouveau code reçoit l'objet `Settings` (via `get_settings()`) ; les constantes de module
(LLM_PROVIDER, AUDIO_RATE, ...) restent exportées pour compatibilité.
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from dotenv import dotenv_values
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator

# Encodage UTF-8 pour la console Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Racine du projet SmartHome
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

ENV_FILE = Path(os.environ.get("SMARTHOME_ENV_FILE") or BASE_DIR / ".env")
if not ENV_FILE.is_absolute():
    ENV_FILE = BASE_DIR / ENV_FILE


def _parse_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "oui", "on")
    return value


def _parse_list(value):
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return value


EnvBool = Annotated[bool, BeforeValidator(_parse_bool)]
CsvList = Annotated[list[str], BeforeValidator(_parse_list)]
FeedbackType = Literal["phrase", "sound", "none"]


class Settings(BaseModel):
    """Ensemble des paramètres de l'application. Les noms de champs sont ceux des variables .env."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    # 🌐 Fournisseurs (les noms valides sont ceux des registres de fournisseurs)
    LLM_PROVIDER: str = "ollama"
    STT_PROVIDER: str = "whisper"
    TTS_PROVIDER: str = "piper"

    # ☁️ OpenRouter / Cloud
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct"
    OPENROUTER_STT_MODEL: str = "openai/whisper-large-v3"
    OPENROUTER_TTS_MODEL: str = "openai/tts-1"
    OPENROUTER_TTS_VOICE: str = "nova"

    # 🎙️ Audio global
    AUDIO_RATE: int = Field(16000, gt=0)
    AUDIO_CHUNK: int = Field(1280, gt=0)
    AUDIO_CHANNELS: int = Field(1, ge=1)
    AUDIO_INPUT_DEVICE_INDEX: Optional[int] = None
    AUDIO_OUTPUT_DEVICE_INDEX: Optional[int] = None

    # ⚡ Wake word (openWakeWord)
    WAKEWORD_MODEL_PATH: str = "wakewords/Salut_Jarvisse_20260601_005854.onnx"
    WAKEWORD_THRESHOLD: float = Field(0.5, ge=0.0, le=1.0)

    # 🗣️ Enregistrement & STT (faster-whisper)
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    WHISPER_LANGUAGE: str = "fr"
    WHISPER_BEAM_SIZE: int = Field(3, ge=1)
    VOICE_THRESHOLD: float = Field(700.0, ge=0.0)
    SILENCE_DURATION: float = Field(0.8, gt=0.0)
    MAX_SPEECH_DURATION: float = Field(12.0, gt=0.0)
    FOLLOW_UP_TIMEOUT: float = Field(
        30.0, gt=0.0, validation_alias=AliasChoices("FOLLOW_UP_TIMEOUT", "ACTIVE_STANDBY_TIMEOUT")
    )

    # 🧠 LLM
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_HOST: str = "http://localhost:11434"
    LLM_SYSTEM_PROMPT: str = (
        "Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe "
        "(1 à 2 phrases max). N'utilise pas de markdown ou d'emoji."
    )
    LLM_STREAM: EnvBool = True
    LLM_THINK: EnvBool = False
    LLM_HISTORY_MESSAGES: int = Field(5, ge=0)
    # Mode d'appel d'outils : "native" (function calling), "tags" ([VOLUME 40] dans le texte), "auto" (native puis repli tags)
    LLM_TOOL_CALLING: Literal["auto", "native", "tags"] = "auto"
    # Nombre maximal d'allers-retours outil -> LLM pour une même demande
    LLM_MAX_TOOL_ROUNDS: int = Field(4, ge=1)

    # 🔊 TTS (Piper)
    TTS_VOICE: str = "fr_FR-siwis-medium"
    TTS_MODEL_PATH: str = ""
    TTS_CONFIG_PATH: str = ""
    TTS_SPEECH_SPEED: float = Field(1.15, gt=0.0)
    TTS_FADE_OUT_DURATION: float = Field(0.05, ge=0.0)
    TTS_SILENCE_START_DURATION: float = Field(0.10, ge=0.0)
    TTS_SILENCE_END_DURATION: float = Field(0.40, ge=0.0)

    # 🔔 Retours sonores & vocaux
    FEEDBACK_WAKEWORD_TYPE: FeedbackType = "phrase"
    FEEDBACK_WAKEWORD_TEXT: str = "Que puis je pour toi ?"
    FEEDBACK_WAKEWORD_SOUND: str = "wake"
    FEEDBACK_RESPONSE_END_TYPE: FeedbackType = "sound"
    FEEDBACK_RESPONSE_END_SOUND: str = "ding"
    FEEDBACK_RESPONSE_END_TEXT: str = ""
    FEEDBACK_TIMEOUT_TYPE: FeedbackType = "phrase"
    FEEDBACK_TIMEOUT_TEXT: str = "Bisous a plus tard"
    FEEDBACK_TIMEOUT_SOUND: str = "sleep"
    FEEDBACK_SOUND_VOLUME: float = Field(0.5, ge=0.0, le=1.0)

    # ⚡ Actions système
    ACTIONS_ENABLED: EnvBool = True
    ACTIONS_DYNAMIC_PROMPT: EnvBool = True
    # Applications que [OPEN] est autorisé à lancer directement (en plus des catégories : navigateur, musique, terminal...)
    ACTIONS_OPEN_ALLOWED_APPS: CsvList = _parse_list(
        "firefox,google-chrome,chromium,brave-browser,microsoft-edge,spotify,vlc,elisa,rhythmbox,"
        "code,vscodium,kate,gedit,dolphin,nautilus,thunar,kcalc,gnome-calculator,discord,steam,obs,gimp,libreoffice"
    )

    # Confirmation vocale des actions dangereuses (extinction, redémarrage, outils MCP destructeurs)
    ACTIONS_CONFIRM_DANGEROUS: EnvBool = True
    ACTIONS_CONFIRM_TIMEOUT: float = Field(6.0, gt=0.0)
    ACTIONS_CONFIRM_WORDS: CsvList = _parse_list("oui,ouais,confirme,confirmé,vas-y,vas y,ok,d'accord,go,yes")
    # Un mot d'annulation l'emporte toujours sur un mot de confirmation ("oui... non attends")
    ACTIONS_CANCEL_WORDS: CsvList = _parse_list("non,annule,annuler,stop,attends,pas")
    # Question posée avant une action dangereuse ({action} = description de l'action)
    ACTIONS_CONFIRM_PROMPT: str = "Tu confirmes : {action} ?"
    # Durée maximale d'exécution d'une action locale appelée comme outil (secondes)
    ACTIONS_TIMEOUT: float = Field(10.0, gt=0.0)

    # 🔉 Ducking
    DUCKING_ENABLED: EnvBool = True
    DUCKING_VOLUME_PERCENT: int = Field(20, ge=0, le=100)
    DUCKING_RESTORE_ON_EXIT: EnvBool = True

    # 🔌 Serveur MCP & Hub client
    MCP_TRANSPORT: Literal["stdio", "sse", "streamable-http"] = "stdio"
    MCP_HOST: str = "127.0.0.1"
    MCP_PORT: int = Field(8000, ge=1, le=65535)
    # Jeton Bearer exigé par les transports réseau (sse / streamable-http). Obligatoire hors loopback.
    MCP_AUTH_TOKEN: str = ""
    # Seul dossier dans lequel l'outil stt_transcribe_file peut lire des fichiers audio
    MCP_AUDIO_DIR: str = str(BASE_DIR / "recordings")
    MCP_CLIENT_ENABLED: EnvBool = True
    MCP_SERVERS_CONFIG_PATH: str = "mcp_servers.json"

    # 🌍 Passerelle (clients distants : WebSocket /ws et HTTP /api/ask)
    # Démarre la passerelle dans main.py, à côté de l'écoute micro (sinon : python -m gateway pour un serveur sans micro)
    GATEWAY_ENABLED: EnvBool = False
    GATEWAY_HOST: str = "127.0.0.1"
    GATEWAY_PORT: int = Field(8765, ge=1, le=65535)
    # Jeton exigé par les clients ; obligatoire hors loopback (LAN, Tailscale)
    GATEWAY_AUTH_TOKEN: str = ""
    # Délai laissé à un client distant pour confirmer une action dangereuse (secondes)
    GATEWAY_CONFIRM_TIMEOUT: float = Field(20.0, gt=0.0)
    # Durée d'inactivité après laquelle une session distante (et son historique) est oubliée (secondes)
    GATEWAY_SESSION_TIMEOUT: float = Field(3600.0, gt=0.0)
    # Taille maximale d'un message WebSocket (audio base64 compris), en octets
    GATEWAY_MAX_MESSAGE_BYTES: int = Field(10 * 1024 * 1024, gt=0)

    @field_validator(
        "LLM_PROVIDER", "TTS_PROVIDER", "MCP_TRANSPORT", "LLM_TOOL_CALLING",
        "FEEDBACK_WAKEWORD_TYPE", "FEEDBACK_RESPONSE_END_TYPE", "FEEDBACK_TIMEOUT_TYPE",
        mode="before",
    )
    @classmethod
    def _lowercase(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("STT_PROVIDER", mode="before")
    @classmethod
    def _normalize_stt(cls, value):
        value = value.strip().lower() if isinstance(value, str) else value
        # "none" / "bypass" sont d'anciens synonymes du mode audio direct
        return "direct" if value in ("none", "bypass") else value


# Noms de variables reconnus (champs + alias), pour ne lire que ce qui concerne SmartHome
_KNOWN_KEYS = set(Settings.model_fields) | {"ACTIVE_STANDBY_TIMEOUT"}


def load_settings(env_file: Path = ENV_FILE) -> Settings:
    """Charge et valide la configuration. Une valeur vide est considérée comme absente."""
    raw: dict[str, str] = {}
    sources = [dotenv_values(env_file) if env_file.exists() else {}, os.environ]
    for source in sources:
        for key, value in source.items():
            if key in _KNOWN_KEYS and value is not None and value.strip():
                raw[key] = value.strip()

    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        lines = [f"❌ [CONFIG] Configuration invalide ({env_file}) :"]
        for err in e.errors():
            key = ".".join(str(part) for part in err["loc"])
            lines.append(f"  • {key} = {err.get('input')!r} → {err['msg']}")
        raise SystemExit("\n".join(lines)) from None


def resolve_piper_voice(s: Settings) -> tuple[str, str]:
    """Résout le chemin du modèle et du fichier de configuration Piper."""
    voices_dir = BASE_DIR / "voices"

    def config_for(model: Path) -> Path:
        return Path(f"{model}.json")

    # 1. TTS_VOICE (nom court ou complet), seulement s'il est explicitement défini
    voice_name = s.TTS_VOICE if "TTS_VOICE" in s.model_fields_set else ""
    if voice_name:
        for cand in (voices_dir / voice_name, voices_dir / f"{voice_name}.onnx",
                     BASE_DIR / voice_name, BASE_DIR / f"{voice_name}.onnx"):
            if cand.is_file():
                return str(cand), str(config_for(cand))
        # Recherche partielle dans voices/ (ex: "upmc", "tom", "siwis")
        if voices_dir.exists():
            for f in sorted(voices_dir.glob("*.onnx")):
                if voice_name.lower() in f.stem.lower():
                    return str(f), str(config_for(f))

    # 2. Chemin de modèle explicite
    if s.TTS_MODEL_PATH:
        p = Path(s.TTS_MODEL_PATH)
        p = p if p.is_absolute() else BASE_DIR / p
        if p.exists():
            return str(p), s.TTS_CONFIG_PATH or str(config_for(p))

    # 3. Voix par défaut dans voices/
    for d in (voices_dir / "fr_FR-siwis-medium.onnx", voices_dir / "fr_FR-upmc-medium.onnx",
              voices_dir / "fr_FR-tom-medium.onnx", BASE_DIR / "voice.onnx"):
        if d.exists():
            return str(d), str(config_for(d))

    fallback_model = voices_dir / "fr_FR-siwis-medium.onnx"
    return str(fallback_model), str(config_for(fallback_model))


settings: Settings = load_settings()


def get_settings() -> Settings:
    """Retourne la configuration chargée au démarrage (à injecter dans les composants)."""
    return settings


# ==========================================
# Constantes de module (compatibilité)
# ==========================================
LLM_PROVIDER = settings.LLM_PROVIDER
STT_PROVIDER = settings.STT_PROVIDER
TTS_PROVIDER = settings.TTS_PROVIDER

OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_BASE_URL = settings.OPENROUTER_BASE_URL
OPENROUTER_MODEL = settings.OPENROUTER_MODEL
OPENROUTER_STT_MODEL = settings.OPENROUTER_STT_MODEL
OPENROUTER_TTS_MODEL = settings.OPENROUTER_TTS_MODEL
OPENROUTER_TTS_VOICE = settings.OPENROUTER_TTS_VOICE

AUDIO_RATE = RATE = settings.AUDIO_RATE
AUDIO_CHUNK = CHUNK = settings.AUDIO_CHUNK
AUDIO_CHANNELS = CHANNELS = settings.AUDIO_CHANNELS
AUDIO_INPUT_DEVICE_INDEX = settings.AUDIO_INPUT_DEVICE_INDEX
AUDIO_OUTPUT_DEVICE_INDEX = settings.AUDIO_OUTPUT_DEVICE_INDEX

WAKEWORD_MODEL_PATH = settings.WAKEWORD_MODEL_PATH
WAKEWORD_THRESHOLD = settings.WAKEWORD_THRESHOLD

WHISPER_MODEL = settings.WHISPER_MODEL
WHISPER_DEVICE = settings.WHISPER_DEVICE
WHISPER_COMPUTE_TYPE = settings.WHISPER_COMPUTE_TYPE
WHISPER_LANGUAGE = settings.WHISPER_LANGUAGE
WHISPER_BEAM_SIZE = settings.WHISPER_BEAM_SIZE
VOICE_THRESHOLD = settings.VOICE_THRESHOLD
SILENCE_DURATION = settings.SILENCE_DURATION
MAX_SPEECH_DURATION = settings.MAX_SPEECH_DURATION
FOLLOW_UP_TIMEOUT = ACTIVE_STANDBY_TIMEOUT = settings.FOLLOW_UP_TIMEOUT

OLLAMA_MODEL = settings.OLLAMA_MODEL
OLLAMA_HOST = settings.OLLAMA_HOST
LLM_SYSTEM_PROMPT = settings.LLM_SYSTEM_PROMPT
LLM_STREAM = settings.LLM_STREAM
LLM_THINK = settings.LLM_THINK
LLM_HISTORY_MESSAGES = settings.LLM_HISTORY_MESSAGES
LLM_TOOL_CALLING = settings.LLM_TOOL_CALLING
LLM_MAX_TOOL_ROUNDS = settings.LLM_MAX_TOOL_ROUNDS

TTS_VOICE = settings.TTS_VOICE
TTS_MODEL_PATH, TTS_CONFIG_PATH = resolve_piper_voice(settings)
TTS_SPEECH_SPEED = settings.TTS_SPEECH_SPEED
TTS_FADE_OUT_DURATION = settings.TTS_FADE_OUT_DURATION
TTS_SILENCE_START_DURATION = settings.TTS_SILENCE_START_DURATION
TTS_SILENCE_END_DURATION = settings.TTS_SILENCE_END_DURATION
TTS_OUTPUT_DEVICE = settings.AUDIO_OUTPUT_DEVICE_INDEX

FEEDBACK_WAKEWORD_TYPE = settings.FEEDBACK_WAKEWORD_TYPE
FEEDBACK_WAKEWORD_TEXT = settings.FEEDBACK_WAKEWORD_TEXT
FEEDBACK_WAKEWORD_SOUND = settings.FEEDBACK_WAKEWORD_SOUND
FEEDBACK_RESPONSE_END_TYPE = settings.FEEDBACK_RESPONSE_END_TYPE
FEEDBACK_RESPONSE_END_SOUND = settings.FEEDBACK_RESPONSE_END_SOUND
FEEDBACK_RESPONSE_END_TEXT = settings.FEEDBACK_RESPONSE_END_TEXT
FEEDBACK_TIMEOUT_TYPE = settings.FEEDBACK_TIMEOUT_TYPE
FEEDBACK_TIMEOUT_TEXT = settings.FEEDBACK_TIMEOUT_TEXT
FEEDBACK_TIMEOUT_SOUND = settings.FEEDBACK_TIMEOUT_SOUND
FEEDBACK_SOUND_VOLUME = settings.FEEDBACK_SOUND_VOLUME

ACTIONS_ENABLED = settings.ACTIONS_ENABLED
ACTIONS_DYNAMIC_PROMPT = settings.ACTIONS_DYNAMIC_PROMPT
ACTIONS_OPEN_ALLOWED_APPS = settings.ACTIONS_OPEN_ALLOWED_APPS
ACTIONS_CONFIRM_DANGEROUS = settings.ACTIONS_CONFIRM_DANGEROUS
ACTIONS_CONFIRM_TIMEOUT = settings.ACTIONS_CONFIRM_TIMEOUT
ACTIONS_CONFIRM_WORDS = settings.ACTIONS_CONFIRM_WORDS
ACTIONS_CANCEL_WORDS = settings.ACTIONS_CANCEL_WORDS
ACTIONS_CONFIRM_PROMPT = settings.ACTIONS_CONFIRM_PROMPT
ACTIONS_TIMEOUT = settings.ACTIONS_TIMEOUT

DUCKING_ENABLED = settings.DUCKING_ENABLED
DUCKING_VOLUME_PERCENT = settings.DUCKING_VOLUME_PERCENT
DUCKING_RESTORE_ON_EXIT = settings.DUCKING_RESTORE_ON_EXIT

MCP_TRANSPORT = settings.MCP_TRANSPORT
MCP_HOST = settings.MCP_HOST
MCP_PORT = settings.MCP_PORT
MCP_AUTH_TOKEN = settings.MCP_AUTH_TOKEN
MCP_AUDIO_DIR = settings.MCP_AUDIO_DIR
MCP_CLIENT_ENABLED = settings.MCP_CLIENT_ENABLED
MCP_SERVERS_CONFIG_PATH = settings.MCP_SERVERS_CONFIG_PATH

GATEWAY_ENABLED = settings.GATEWAY_ENABLED
GATEWAY_HOST = settings.GATEWAY_HOST
GATEWAY_PORT = settings.GATEWAY_PORT
GATEWAY_AUTH_TOKEN = settings.GATEWAY_AUTH_TOKEN
GATEWAY_CONFIRM_TIMEOUT = settings.GATEWAY_CONFIRM_TIMEOUT
GATEWAY_SESSION_TIMEOUT = settings.GATEWAY_SESSION_TIMEOUT
GATEWAY_MAX_MESSAGE_BYTES = settings.GATEWAY_MAX_MESSAGE_BYTES


if __name__ == "__main__":
    print(f"📋 [CONFIG] Configuration chargée depuis {ENV_FILE} (variables d'environnement prioritaires) :")
    for name, value in settings.model_dump().items():
        if value and any(secret in name for secret in ("KEY", "TOKEN")):
            value = "Configuré (masqué)"
        print(f"  • {name:<28}: {value}")
    print(f"  • {'TTS_MODEL_PATH (résolu)':<28}: {TTS_MODEL_PATH}")
    print(f"  • {'TTS_CONFIG_PATH (résolu)':<28}: {TTS_CONFIG_PATH}")
