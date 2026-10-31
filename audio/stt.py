"""
Fournisseurs STT : interface commune `STTProvider` + implémentations Whisper local, OpenRouter et mode direct.
Un fournisseur transcrit un fichier WAV en mémoire ; l'enregistrement micro / VAD reste dans audio/transcribe.py.
"""

import io
import sys
import threading
from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings
from core.providers import ProviderRegistry, require_openrouter_key
from core.sentences import matches_phrase, normalize_utterance


class STTProvider:
    """Interface d'un fournisseur de transcription."""

    provider_name: str = ""
    # True si le fournisseur ne transcrit pas : l'audio brut est transmis tel quel au LLM multimodal
    passthrough: bool = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.language = settings.WHISPER_LANGUAGE or None

    @classmethod
    def describe(cls, settings: Settings) -> str:
        """Résumé lisible de la configuration, sans instancier le fournisseur."""
        raise NotImplementedError

    def transcribe(self, wav_bytes: bytes) -> str:
        """Retourne le texte reconnu dans l'enregistrement WAV (chaîne vide si rien). Lève en cas d'erreur."""
        raise NotImplementedError

    def _discard_hallucination(self, text: str) -> str:
        """Whisper « entend » des phrases toutes faites dans le bruit (« Sous-titres réalisés par... ») : on les ignore."""
        if text and (not normalize_utterance(text) or matches_phrase(text, self.settings.STT_IGNORED_PHRASES)):
            print(f"\n🔇 [STT] Transcription ignorée (bruit) : « {text} »")
            return ""
        return text


STT_PROVIDERS: ProviderRegistry[STTProvider] = ProviderRegistry("STT")


@STT_PROVIDERS.register("whisper")
class WhisperSTT(STTProvider):
    """Transcription locale via faster-whisper (CPU int8 par défaut)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        print(f"Chargement Whisper local ({settings.WHISPER_MODEL} sur {settings.WHISPER_DEVICE})... ⏳")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(settings.WHISPER_MODEL, device=settings.WHISPER_DEVICE, compute_type=settings.WHISPER_COMPUTE_TYPE)
        self.beam_size = settings.WHISPER_BEAM_SIZE
        # Modèle partagé entre le micro local et les clients distants : une transcription à la fois
        self._lock = threading.Lock()
        print("Whisper local prêt ✅")

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"Whisper ({settings.WHISPER_MODEL})"

    def transcribe(self, wav_bytes: bytes) -> str:
        with self._lock:
            segments, _ = self.model.transcribe(
                io.BytesIO(wav_bytes),
                language=self.language,
                beam_size=self.beam_size,
                condition_on_previous_text=False,
                # Silero VAD intégré à faster-whisper : retire les passages sans parole avant le décodage
                vad_filter=self.settings.WHISPER_VAD_FILTER,
            )
            # Les segments sont générés paresseusement : la transcription a lieu pendant ce parcours
            text = " ".join(seg.text for seg in segments).strip()
        return self._discard_hallucination(text)


@STT_PROVIDERS.register("openrouter")
class OpenRouterSTT(STTProvider):
    """Transcription cloud via /audio/transcriptions (API compatible OpenAI)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        from openai import OpenAI
        self.client = OpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY or "missing-key")
        print(f"STT OpenRouter prêt ({settings.OPENROUTER_STT_MODEL}) ✅")

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"OpenRouter ({settings.OPENROUTER_STT_MODEL})"

    def transcribe(self, wav_bytes: bytes) -> str:
        require_openrouter_key(self.settings)
        transcription = self.client.audio.transcriptions.create(
            model=self.settings.OPENROUTER_STT_MODEL,
            file=("audio.wav", wav_bytes, "audio/wav"),
            language=self.language,
        )
        return self._discard_hallucination((getattr(transcription, "text", "") or "").strip())


@STT_PROVIDERS.register("direct", "none", "bypass")
class DirectSTT(STTProvider):
    """Bypass STT : l'enregistrement est envoyé directement au LLM multimodal."""

    passthrough = True

    def __init__(self, settings: Settings):
        super().__init__(settings)
        print("Mode Direct Audio actif (Bypass STT ⏩ Multimodal LLM) ✅")

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return "Direct Audio (Bypass STT ⏩ Multimodal LLM)"

    def transcribe(self, wav_bytes: bytes) -> str:
        raise RuntimeError("Le mode STT direct ne transcrit pas : l'audio est transmis au LLM.")


def create_stt(settings: Settings) -> STTProvider:
    """Crée le fournisseur STT configuré, avec repli sur Whisper si le LLM ne sait pas recevoir d'audio."""
    from llm.providers import LLM_PROVIDERS

    name = settings.STT_PROVIDER
    if STT_PROVIDERS.get(name).passthrough and not LLM_PROVIDERS.get(settings.LLM_PROVIDER).supports_audio:
        print(f"⚠️ STT_PROVIDER=direct incompatible avec LLM_PROVIDER={settings.LLM_PROVIDER} (pas d'entrée audio) : repli sur Whisper local.")
        name = "whisper"
    return STT_PROVIDERS.create(name, settings)


if __name__ == "__main__":
    from core.config import get_settings
    s = get_settings()
    print(f"🧪 [DEBUG] Fournisseurs STT disponibles : {', '.join(STT_PROVIDERS.names())}")
    if len(sys.argv) < 2:
        print("Usage : python audio/stt.py <fichier.wav>")
        sys.exit(0)
    stt = create_stt(s)
    print(f"👉 « {stt.transcribe(Path(sys.argv[1]).read_bytes())} »")
