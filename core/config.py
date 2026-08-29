import os
import sys
from pathlib import Path
from dotenv import load_dotenv

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

ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE, override=True)
else:
    load_dotenv(override=True)



def _get_str(key: str, default: str) -> str:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("true", "1", "yes", "oui", "on")


def _get_optional_int(key: str, default=None):
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


# ==========================================
# 🌐 FOURNISSEURS DE SERVICES (Providers)
# ==========================================
LLM_PROVIDER: str = _get_str("LLM_PROVIDER", "ollama").lower()
STT_PROVIDER: str = _get_str("STT_PROVIDER", "whisper").lower()
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "piper").lower()

# ==========================================
# ☁️ OPENROUTER / CLOUD
# ==========================================
OPENROUTER_API_KEY: str = _get_str("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = _get_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL: str = _get_str("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_STT_MODEL: str = _get_str("OPENROUTER_STT_MODEL", "openai/whisper-large-v3")
OPENROUTER_TTS_MODEL: str = _get_str("OPENROUTER_TTS_MODEL", "openai/tts-1")
OPENROUTER_TTS_VOICE: str = _get_str("OPENROUTER_TTS_VOICE", "nova")

# ==========================================
# 🎙️ AUDIO GLOBAL
# ==========================================
AUDIO_RATE: int = _get_int("AUDIO_RATE", 16000)
AUDIO_CHUNK: int = _get_int("AUDIO_CHUNK", 1280)
AUDIO_CHANNELS: int = _get_int("AUDIO_CHANNELS", 1)
AUDIO_INPUT_DEVICE_INDEX = _get_optional_int("AUDIO_INPUT_DEVICE_INDEX", None)
AUDIO_OUTPUT_DEVICE_INDEX = _get_optional_int("AUDIO_OUTPUT_DEVICE_INDEX", None)

# Alias pour compatibilité
RATE = AUDIO_RATE
CHUNK = AUDIO_CHUNK
CHANNELS = AUDIO_CHANNELS

# ==========================================
# ⚡ WAKE WORD (openWakeWord)
# ==========================================
WAKEWORD_MODEL_PATH: str = _get_str("WAKEWORD_MODEL_PATH", "wakewords/Salut_Jarvisse_20260601_005854.onnx")
WAKEWORD_THRESHOLD: float = _get_float("WAKEWORD_THRESHOLD", 0.5)

# ==========================================
# 🗣️ TRANSCRIPTION / STT (faster-whisper)
# ==========================================
WHISPER_MODEL: str = _get_str("WHISPER_MODEL", "base")
WHISPER_DEVICE: str = _get_str("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE: str = _get_str("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_LANGUAGE: str = _get_str("WHISPER_LANGUAGE", "fr")
WHISPER_BEAM_SIZE: int = _get_int("WHISPER_BEAM_SIZE", 3)
VOICE_THRESHOLD: float = _get_float("VOICE_THRESHOLD", 700.0)
SILENCE_DURATION: float = _get_float("SILENCE_DURATION", 0.8)
MAX_SPEECH_DURATION: float = _get_float("MAX_SPEECH_DURATION", 12.0)
FOLLOW_UP_TIMEOUT: float = _get_float("FOLLOW_UP_TIMEOUT", _get_float("ACTIVE_STANDBY_TIMEOUT", 30.0))
ACTIVE_STANDBY_TIMEOUT: float = FOLLOW_UP_TIMEOUT

# ==========================================
# 🧠 LLM / RAISONNEMENT (Ollama & OpenRouter)
# ==========================================
OLLAMA_MODEL: str = _get_str("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST: str = _get_str("OLLAMA_HOST", "http://localhost:11434")
LLM_SYSTEM_PROMPT: str = _get_str(
    "LLM_SYSTEM_PROMPT",
    "Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe (1 à 2 phrases max). N'utilise pas de markdown ou d'emoji."
)
LLM_STREAM: bool = _get_bool("LLM_STREAM", True)
LLM_THINK: bool = _get_bool("LLM_THINK", False)
LLM_HISTORY_MESSAGES: int = _get_int("LLM_HISTORY_MESSAGES", 5)


# ==========================================
# 🔊 SYNTHÈSE VOCALE / TTS (Piper TTS)
# ==========================================
def _resolve_piper_voice() -> tuple[str, str]:
    """Résout le chemin du modèle et du fichier de configuration Piper."""
    voice_name = _get_str("TTS_VOICE", "")
    model_path = _get_str("TTS_MODEL_PATH", "")
    config_path = _get_str("TTS_CONFIG_PATH", "")

    voices_dir = BASE_DIR / "voices"

    # 1. Si TTS_VOICE est spécifié (nom court ou complet)
    if voice_name:
        candidates = [
            voices_dir / voice_name,
            voices_dir / f"{voice_name}.onnx",
            BASE_DIR / voice_name,
            BASE_DIR / f"{voice_name}.onnx",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                cfg = cand.with_suffix(cand.suffix + ".json")
                if not cfg.exists() and Path(f"{cand}.json").exists():
                    cfg = Path(f"{cand}.json")
                return str(cand), str(cfg)

        # Recherche partielle dans voices/ (ex: "upmc", "tom", "siwis")
        if voices_dir.exists():
            for f in sorted(voices_dir.glob("*.onnx")):
                if voice_name.lower() in f.stem.lower():
                    cfg = f.with_suffix(f.suffix + ".json")
                    if not cfg.exists() and Path(f"{f}.json").exists():
                        cfg = Path(f"{f}.json")
                    return str(f), str(cfg)

    # 2. Si un chemin de modèle explicite existant est fourni
    if model_path:
        p = Path(model_path) if Path(model_path).is_absolute() else BASE_DIR / model_path
        if p.exists():
            cfg = Path(config_path) if config_path else p.with_suffix(p.suffix + ".json" if not str(p).endswith(".onnx.json") else "")
            if not cfg.exists() and Path(f"{p}.json").exists():
                cfg = Path(f"{p}.json")
            return str(p), str(cfg)

    # 3. Voix par défaut dans voices/
    defaults = [
        voices_dir / "fr_FR-siwis-medium.onnx",
        voices_dir / "fr_FR-upmc-medium.onnx",
        voices_dir / "fr_FR-tom-medium.onnx",
        BASE_DIR / "voice.onnx",
    ]
    for d in defaults:
        if d.exists():
            cfg = Path(f"{d}.json") if Path(f"{d}.json").exists() else d.with_suffix(d.suffix + ".json")
            return str(d), str(cfg)

    fallback_model = str(voices_dir / "fr_FR-siwis-medium.onnx")
    return fallback_model, f"{fallback_model}.json"


TTS_VOICE: str = _get_str("TTS_VOICE", "fr_FR-siwis-medium")
TTS_MODEL_PATH, TTS_CONFIG_PATH = _resolve_piper_voice()
TTS_SPEECH_SPEED: float = _get_float("TTS_SPEECH_SPEED", 1.15)
TTS_FADE_OUT_DURATION: float = _get_float("TTS_FADE_OUT_DURATION", 0.05)
TTS_SILENCE_START_DURATION: float = _get_float("TTS_SILENCE_START_DURATION", 0.10)
TTS_SILENCE_END_DURATION: float = _get_float("TTS_SILENCE_END_DURATION", 0.40)
TTS_OUTPUT_DEVICE = AUDIO_OUTPUT_DEVICE_INDEX

# ==========================================
# 🔔 SIGNAUX SONORES & RETOURS VOCAUX (Feedback)
# ==========================================
# Détection mot-clé
FEEDBACK_WAKEWORD_TYPE: str = _get_str("FEEDBACK_WAKEWORD_TYPE", "phrase")
FEEDBACK_WAKEWORD_TEXT: str = _get_str("FEEDBACK_WAKEWORD_TEXT", "Que puis je pour toi ?")
FEEDBACK_WAKEWORD_SOUND: str = _get_str("FEEDBACK_WAKEWORD_SOUND", "wake")

# Fin de réponse IA (passage de parole)
FEEDBACK_RESPONSE_END_TYPE: str = _get_str("FEEDBACK_RESPONSE_END_TYPE", "sound")
FEEDBACK_RESPONSE_END_SOUND: str = _get_str("FEEDBACK_RESPONSE_END_SOUND", "ding")
FEEDBACK_RESPONSE_END_TEXT: str = _get_str("FEEDBACK_RESPONSE_END_TEXT", "")

# Fin d'écoute active (timeout / mise en veille)
FEEDBACK_TIMEOUT_TYPE: str = _get_str("FEEDBACK_TIMEOUT_TYPE", "phrase")
FEEDBACK_TIMEOUT_TEXT: str = _get_str("FEEDBACK_TIMEOUT_TEXT", "Bisous a plus tard")
FEEDBACK_TIMEOUT_SOUND: str = _get_str("FEEDBACK_TIMEOUT_SOUND", "sleep")

# Volume global des signaux sonores (0.0 à 1.0)
FEEDBACK_SOUND_VOLUME: float = _get_float("FEEDBACK_SOUND_VOLUME", 0.5)

# ==========================================
# ⚡ ACTIONS & COMMANDES SYSTÈME (Bash / Scripts)
# ==========================================
ACTIONS_ENABLED: bool = _get_bool("ACTIONS_ENABLED", True)
ACTIONS_DYNAMIC_PROMPT: bool = _get_bool("ACTIONS_DYNAMIC_PROMPT", True)

# ==========================================
# 🔉 DUCKING / ATTÉNUATION SONORE SYSTÈME
# ==========================================
DUCKING_ENABLED: bool = _get_bool("DUCKING_ENABLED", True)
DUCKING_VOLUME_PERCENT: int = _get_int("DUCKING_VOLUME_PERCENT", 20)
DUCKING_RESTORE_ON_EXIT: bool = _get_bool("DUCKING_RESTORE_ON_EXIT", True)

if __name__ == "__main__":
    print("📋 [CONFIG] Configuration chargée :")
    print(f"  • ACTIONS ACTIVÉES        : {ACTIONS_ENABLED}")
    print(f"  • PROMPT DYNAMIQUE        : {ACTIONS_DYNAMIC_PROMPT}")
    print(f"  • FOURNISSEUR LLM         : {LLM_PROVIDER}")
    print(f"  • FOURNISSEUR STT         : {STT_PROVIDER}")
    print(f"  • FOURNISSEUR TTS         : {TTS_PROVIDER}")
    print(f"  • OPENROUTER_API_KEY      : {'Configurée (' + OPENROUTER_API_KEY[:8] + '...)' if OPENROUTER_API_KEY else 'Non configurée'}")
    print(f"  • OPENROUTER_BASE_URL     : {OPENROUTER_BASE_URL}")
    print(f"  • OPENROUTER_MODEL        : {OPENROUTER_MODEL}")
    print(f"  • OPENROUTER_STT_MODEL    : {OPENROUTER_STT_MODEL}")
    print(f"  • OPENROUTER_TTS_MODEL    : {OPENROUTER_TTS_MODEL} (Voix: {OPENROUTER_TTS_VOICE})")
    print(f"  • AUDIO_RATE              : {AUDIO_RATE}")
    print(f"  • AUDIO_CHUNK             : {AUDIO_CHUNK}")
    print(f"  • AUDIO_CHANNELS          : {AUDIO_CHANNELS}")
    print(f"  • AUDIO_INPUT_DEVICE      : {AUDIO_INPUT_DEVICE_INDEX}")
    print(f"  • AUDIO_OUTPUT_DEVICE     : {AUDIO_OUTPUT_DEVICE_INDEX}")
    print(f"  • WAKEWORD_MODEL_PATH     : {WAKEWORD_MODEL_PATH}")
    print(f"  • WAKEWORD_THRESHOLD      : {WAKEWORD_THRESHOLD}")
    print(f"  • WHISPER_MODEL           : {WHISPER_MODEL}")
    print(f"  • WHISPER_DEVICE          : {WHISPER_DEVICE}")
    print(f"  • WHISPER_COMPUTE_TYPE    : {WHISPER_COMPUTE_TYPE}")
    print(f"  • WHISPER_LANGUAGE        : {WHISPER_LANGUAGE}")
    print(f"  • VOICE_THRESHOLD         : {VOICE_THRESHOLD}")
    print(f"  • SILENCE_DURATION        : {SILENCE_DURATION}s")
    print(f"  • MAX_SPEECH_DURATION     : {MAX_SPEECH_DURATION}s")
    print(f"  • FOLLOW_UP_TIMEOUT       : {FOLLOW_UP_TIMEOUT}s")
    print(f"  • OLLAMA_MODEL            : {OLLAMA_MODEL}")
    print(f"  • OLLAMA_HOST             : {OLLAMA_HOST}")
    print(f"  • LLM_STREAM              : {LLM_STREAM}")
    print(f"  • LLM_THINK               : {LLM_THINK}")
    print(f"  • LLM_HISTORY_MESSAGES    : {LLM_HISTORY_MESSAGES}")
    print(f"  • TTS_VOICE               : {TTS_VOICE}")
    print(f"  • TTS_MODEL_PATH          : {TTS_MODEL_PATH}")
    print(f"  • TTS_CONFIG_PATH         : {TTS_CONFIG_PATH}")
    print(f"  • TTS_SPEECH_SPEED        : {TTS_SPEECH_SPEED}")
    print(f"  • FEEDBACK_WAKEWORD       : {FEEDBACK_WAKEWORD_TYPE} ('{FEEDBACK_WAKEWORD_TEXT}' / '{FEEDBACK_WAKEWORD_SOUND}')")
    print(f"  • FEEDBACK_RESPONSE_END   : {FEEDBACK_RESPONSE_END_TYPE} ('{FEEDBACK_RESPONSE_END_SOUND}' / '{FEEDBACK_RESPONSE_END_TEXT}')")
    print(f"  • FEEDBACK_TIMEOUT        : {FEEDBACK_TIMEOUT_TYPE} ('{FEEDBACK_TIMEOUT_TEXT}' / '{FEEDBACK_TIMEOUT_SOUND}')")
    print(f"  • FEEDBACK_SOUND_VOLUME   : {FEEDBACK_SOUND_VOLUME}")
    print(f"  • DUCKING_ENABLED         : {DUCKING_ENABLED}")
    print(f"  • DUCKING_VOLUME_PERCENT  : {DUCKING_VOLUME_PERCENT}%")
    print(f"  • DUCKING_RESTORE_ON_EXIT : {DUCKING_RESTORE_ON_EXIT}")


