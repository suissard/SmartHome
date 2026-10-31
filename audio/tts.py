"""
Synthèse vocale : fournisseurs `TTSProvider` (Piper local, OpenRouter) + `TextToSpeech`.
Le fournisseur produit l'audio brut ; `TextToSpeech` applique le post-traitement (ponctuation, fade-out,
silences) et la lecture. `synthesize()` permet d'obtenir l'audio sans le jouer (ex: envoi à un client distant).
"""

import io
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import Settings, get_settings, TTS_MODEL_PATH, TTS_CONFIG_PATH
from core.providers import ProviderRegistry, require_openrouter_key


class TTSProvider:
    """Interface d'un fournisseur de synthèse vocale."""

    provider_name: str = ""

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def describe(cls, settings: Settings) -> str:
        """Résumé lisible de la configuration, sans instancier le fournisseur."""
        raise NotImplementedError

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Retourne (échantillons int16, fréquence d'échantillonnage). Tableau vide si rien n'est produit."""
        raise NotImplementedError


TTS_PROVIDERS: ProviderRegistry[TTSProvider] = ProviderRegistry("TTS")


@TTS_PROVIDERS.register("piper")
class PiperTTS(TTSProvider):
    """Synthèse neuronale locale via Piper (ONNX)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        try:
            from piper.voice import PiperVoice, SynthesisConfig
        except ImportError:
            try:
                from piper import PiperVoice, SynthesisConfig
            except ImportError as e:
                raise ImportError("Le module piper-tts n'est pas disponible.") from e

        print("Chargement de Piper... ⏳")
        self.voice = PiperVoice.load(TTS_MODEL_PATH, config_path=TTS_CONFIG_PATH)
        self.syn_config = SynthesisConfig(length_scale=settings.TTS_SPEECH_SPEED)
        print(f"Voix prête ({self.voice.config.sample_rate} Hz) ✅")

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"Piper ({Path(TTS_MODEL_PATH).stem.replace('.onnx', '')})"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        chunks = [
            chunk.audio_int16_array
            for chunk in self.voice.synthesize(text, syn_config=self.syn_config)
            if chunk.audio_int16_array is not None and len(chunk.audio_int16_array) > 0
        ]
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        return audio, self.voice.config.sample_rate


@TTS_PROVIDERS.register("openrouter")
class OpenRouterTTS(TTSProvider):
    """Synthèse cloud via /audio/speech (API compatible OpenAI)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        from openai import OpenAI
        self.client = OpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY or "missing-key")
        print(f"TTS OpenRouter prêt ({settings.OPENROUTER_TTS_MODEL}, Voix: {settings.OPENROUTER_TTS_VOICE}) ✅")

    @classmethod
    def describe(cls, settings: Settings) -> str:
        return f"OpenRouter ({settings.OPENROUTER_TTS_MODEL}, Voix: {settings.OPENROUTER_TTS_VOICE})"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        import soundfile as sf

        require_openrouter_key(self.settings)
        response = self.client.audio.speech.create(
            model=self.settings.OPENROUTER_TTS_MODEL,
            voice=self.settings.OPENROUTER_TTS_VOICE,
            input=text,
            response_format="mp3",
        )
        audio_bytes = response.content if hasattr(response, "content") else response.read()
        audio, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="int16")
        return audio, sample_rate


class TextToSpeech:
    """Façade TTS : fournisseur configuré + post-traitement anti-pops + lecture sur la sortie audio."""

    def __init__(self, settings: Optional[Settings] = None, provider: Optional[TTSProvider] = None):
        s = settings or get_settings()
        self.settings = s
        self.output_device = s.AUDIO_OUTPUT_DEVICE_INDEX
        self.engine = provider or TTS_PROVIDERS.create(s.TTS_PROVIDER, s)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthétise le texte et applique le post-traitement. Retourne (int16, fréquence) ; vide si aucun texte."""
        clean_text = (text or "").strip()
        if not clean_text:
            return np.zeros(0, dtype=np.int16), 0

        # 1. Force une ponctuation pour que la voix termine avec une intonation naturelle
        if not clean_text.endswith((".", "!", "?", "...")):
            clean_text += "."

        # 2. Synthèse selon le fournisseur
        raw_audio, sample_rate = self.engine.synthesize(clean_text)
        if len(raw_audio) == 0:
            return np.zeros(0, dtype=np.int16), sample_rate
        audio = raw_audio.astype(np.float32)

        # 3. Fondu de sortie (fade-out anti-claquements)
        fade_len = int(sample_rate * self.settings.TTS_FADE_OUT_DURATION)
        if 0 < fade_len < len(audio):
            fade_curve = np.linspace(1.0, 0.0, fade_len)
            if audio.ndim > 1:
                fade_curve = fade_curve[:, np.newaxis]
            audio[-fade_len:] *= fade_curve

        # 4. Tampons de silence au début et à la fin
        pad_shape = audio.shape[1:]
        silence_start = np.zeros((int(sample_rate * self.settings.TTS_SILENCE_START_DURATION), *pad_shape), dtype=np.float32)
        silence_end = np.zeros((int(sample_rate * self.settings.TTS_SILENCE_END_DURATION), *pad_shape), dtype=np.float32)

        return np.concatenate([silence_start, audio, silence_end]).astype(np.int16), sample_rate

    def speak(self, text: str):
        """Synthétise puis joue le texte de manière synchrone."""
        try:
            audio, sample_rate = self.synthesize(text)
        except Exception as e:
            print(f"⚠️ Erreur de synthèse vocale ({self.settings.TTS_PROVIDER}) : {e}")
            return
        if len(audio) == 0:
            if (text or "").strip():
                print("⚠️ Aucun audio généré.")
            return

        # 5. Lecture
        sd.play(audio, samplerate=sample_rate, device=self.output_device)
        sd.wait()
        time.sleep(0.05)


if __name__ == "__main__":
    s = get_settings()
    print(f"🧪 [DEBUG] Mode test Synthèse vocale ({TTS_PROVIDERS.get(s.TTS_PROVIDER).describe(s)}, Vitesse: {s.TTS_SPEECH_SPEED})...")
    tts = TextToSpeech()

    while True:
        try:
            texte_test = input("\nTexte à prononcer > ")
            if texte_test.lower() in ["exit", "quit"]:
                break
            print("🔊 Lecture en cours...")
            tts.speak(texte_test)
            print("✅ Lecture terminée.")
        except KeyboardInterrupt:
            print("\nArrêt.")
            break
