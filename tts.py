import io
import time
import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from config import (
    TTS_PROVIDER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_TTS_MODEL,
    OPENROUTER_TTS_VOICE,
    TTS_MODEL_PATH,
    TTS_CONFIG_PATH,
    TTS_SPEECH_SPEED,
    TTS_FADE_OUT_DURATION,
    TTS_SILENCE_START_DURATION,
    TTS_SILENCE_END_DURATION,
    AUDIO_OUTPUT_DEVICE_INDEX,
)

try:
    from piper.voice import PiperVoice, SynthesisConfig
except ImportError:
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError:
        PiperVoice = None
        SynthesisConfig = None

MODEL_PATH = TTS_MODEL_PATH
CONFIG_PATH = TTS_CONFIG_PATH
OUTPUT_DEVICE = AUDIO_OUTPUT_DEVICE_INDEX
SPEECH_SPEED = TTS_SPEECH_SPEED


class TextToSpeech:
    def __init__(
        self,
        provider=TTS_PROVIDER,
        model_path=TTS_MODEL_PATH,
        config_path=TTS_CONFIG_PATH,
        speech_speed=TTS_SPEECH_SPEED,
        output_device=AUDIO_OUTPUT_DEVICE_INDEX
    ):
        self.provider = provider.lower()
        self.output_device = output_device
        self.speech_speed = speech_speed

        if self.provider == "openrouter":
            print(f"Initialisation TTS OpenRouter (Modèle: {OPENROUTER_TTS_MODEL}, Voix: {OPENROUTER_TTS_VOICE})... ⏳")
            from openai import OpenAI
            self.client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=OPENROUTER_API_KEY or "missing-key"
            )
            self.voice = None
            self.sample_rate = 24000
            print("TTS OpenRouter prêt ✅")
        else:
            print("Chargement de Piper... ⏳")
            if PiperVoice is None:
                raise ImportError("Le module piper-tts n'est pas disponible.")
            self.voice = PiperVoice.load(model_path, config_path=config_path)
            self.sample_rate = self.voice.config.sample_rate
            self.syn_config = SynthesisConfig(length_scale=self.speech_speed)
            self.client = None
            print(f"Voix prête ({self.sample_rate} Hz) ✅")

    def speak(self, text):
        clean_text = text.strip()
        if not clean_text:
            return

        # 1. Force une ponctuation pour que la voix termine avec une intonation naturelle
        if not clean_text.endswith((".", "!", "?", "...")):
            clean_text += "."

        raw_audio = None
        sample_rate = self.sample_rate

        # 2. Synthèse selon le fournisseur
        if self.provider == "openrouter":
            if not OPENROUTER_API_KEY:
                print("⚠️ Clé API OpenRouter manquante pour la synthèse vocale.")
                return

            try:
                response = self.client.audio.speech.create(
                    model=OPENROUTER_TTS_MODEL,
                    voice=OPENROUTER_TTS_VOICE,
                    input=clean_text,
                    response_format="wav",
                )
                wav_bytes = response.content if hasattr(response, "content") else response.read()
                sample_rate, audio_data = wavfile.read(io.BytesIO(wav_bytes))
                raw_audio = audio_data.astype(np.float32)
            except Exception as e:
                print(f"⚠️ Erreur de synthèse vocale OpenRouter : {e}")
                return
        else:
            audio_chunks = [
                chunk.audio_int16_array
                for chunk in self.voice.synthesize(clean_text, syn_config=self.syn_config)
                if chunk.audio_int16_array is not None and len(chunk.audio_int16_array) > 0
            ]

            if not audio_chunks:
                print("⚠️ Aucun audio généré.")
                return

            raw_audio = np.concatenate(audio_chunks).astype(np.float32)

        if raw_audio is None or len(raw_audio) == 0:
            return

        # 3. Fondu de sortie (fade-out anti-claquements)
        fade_len = int(sample_rate * TTS_FADE_OUT_DURATION)
        if len(raw_audio) > fade_len:
            fade_curve = np.linspace(1.0, 0.0, fade_len)
            if raw_audio.ndim > 1:
                fade_curve = fade_curve[:, np.newaxis]
            raw_audio[-fade_len:] *= fade_curve

        raw_audio = raw_audio.astype(np.int16)

        # 4. Tampons de silence au début et à la fin
        silence_start_len = int(sample_rate * TTS_SILENCE_START_DURATION)
        silence_end_len = int(sample_rate * TTS_SILENCE_END_DURATION)
        if raw_audio.ndim > 1:
            channels = raw_audio.shape[1]
            silence_start = np.zeros((silence_start_len, channels), dtype=np.int16)
            silence_end = np.zeros((silence_end_len, channels), dtype=np.int16)
        else:
            silence_start = np.zeros(silence_start_len, dtype=np.int16)
            silence_end = np.zeros(silence_end_len, dtype=np.int16)

        full_audio = np.concatenate([silence_start, raw_audio, silence_end])

        # 5. Lecture
        sd.play(full_audio, samplerate=sample_rate, device=self.output_device)
        sd.wait()
        time.sleep(0.05)


if __name__ == "__main__":
    active_tts = f"OpenRouter ({OPENROUTER_TTS_MODEL}, Voix: {OPENROUTER_TTS_VOICE})" if TTS_PROVIDER == "openrouter" else f"Piper ({TTS_MODEL_PATH}, Vitesse: {TTS_SPEECH_SPEED})"
    print(f"🧪 [DEBUG] Mode test Synthèse vocale (Fournisseur: {TTS_PROVIDER.upper()}, Modèle: {active_tts})...")
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

