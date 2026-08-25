import os
from pathlib import Path
from dotenv import load_dotenv

# Chargement du fichier .env
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()


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
FOLLOW_UP_TIMEOUT: float = _get_float("FOLLOW_UP_TIMEOUT", 30.0)

# ==========================================
# 🧠 LLM / RAISONNEMENT (Ollama)
# ==========================================
OLLAMA_MODEL: str = _get_str("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST: str = _get_str("OLLAMA_HOST", "http://localhost:11434")
LLM_SYSTEM_PROMPT: str = _get_str(
    "LLM_SYSTEM_PROMPT",
    "Tu es un assistant vocal domotique. Réponds en français de manière claire, concise et directe (1 à 2 phrases max). N'utilise pas de markdown complexe."
)
LLM_STREAM: bool = _get_bool("LLM_STREAM", True)
LLM_THINK: bool = _get_bool("LLM_THINK", False)


# ==========================================
# 🔊 SYNTHÈSE VOCALE / TTS (Piper TTS)
# ==========================================
TTS_MODEL_PATH: str = _get_str("TTS_MODEL_PATH", "voice.onnx")
TTS_CONFIG_PATH: str = _get_str("TTS_CONFIG_PATH", "voice.onnx.json")
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
# 🔉 DUCKING / ATTÉNUATION SONORE SYSTÈME
# ==========================================
DUCKING_ENABLED: bool = _get_bool("DUCKING_ENABLED", True)
DUCKING_VOLUME_PERCENT: int = _get_int("DUCKING_VOLUME_PERCENT", 20)
DUCKING_RESTORE_ON_EXIT: bool = _get_bool("DUCKING_RESTORE_ON_EXIT", True)

if __name__ == "__main__":
    print("📋 [CONFIG] Configuration chargée :")
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


