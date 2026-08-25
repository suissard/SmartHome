import time
import numpy as np
import sounddevice as sd
from config import (
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
    from piper import PiperVoice, SynthesisConfig

MODEL_PATH = TTS_MODEL_PATH
CONFIG_PATH = TTS_CONFIG_PATH
OUTPUT_DEVICE = AUDIO_OUTPUT_DEVICE_INDEX
SPEECH_SPEED = TTS_SPEECH_SPEED

class TextToSpeech:
    def __init__(
        self,
        model_path=TTS_MODEL_PATH,
        config_path=TTS_CONFIG_PATH,
        speech_speed=TTS_SPEECH_SPEED,
        output_device=AUDIO_OUTPUT_DEVICE_INDEX
    ):
        print("Chargement de Piper... ⏳")
        self.voice = PiperVoice.load(model_path, config_path=config_path)
        self.sample_rate = self.voice.config.sample_rate
        self.speech_speed = speech_speed
        self.output_device = output_device
        self.syn_config = SynthesisConfig(length_scale=self.speech_speed)
        print(f"Voix prête ({self.sample_rate} Hz) ✅")

    def speak(self, text):
        clean_text = text.strip()
        if not clean_text:
            return

        # 1. Force une ponctuation pour que la voix termine avec une intonation naturelle
        if not clean_text.endswith((".", "!", "?", "...")):
            clean_text += "."

        # 2. Synthèse
        audio_chunks = [
            chunk.audio_int16_array
            for chunk in self.voice.synthesize(clean_text, syn_config=self.syn_config)
            if chunk.audio_int16_array is not None and len(chunk.audio_int16_array) > 0
        ]

        if not audio_chunks:
            print("⚠️ Aucun audio généré.")
            return

        raw_audio = np.concatenate(audio_chunks).astype(np.float32)

        # 3. Fondu de sortie (fade-out anti-claquements)
        fade_len = int(self.sample_rate * TTS_FADE_OUT_DURATION)
        if len(raw_audio) > fade_len:
            fade_curve = np.linspace(1.0, 0.0, fade_len)
            raw_audio[-fade_len:] *= fade_curve

        raw_audio = raw_audio.astype(np.int16)

        # 4. Tampons de silence au début et à la fin
        silence_start = np.zeros(int(self.sample_rate * TTS_SILENCE_START_DURATION), dtype=np.int16)
        silence_end = np.zeros(int(self.sample_rate * TTS_SILENCE_END_DURATION), dtype=np.int16)
        full_audio = np.concatenate([silence_start, raw_audio, silence_end])

        # 5. Lecture
        sd.play(full_audio, samplerate=self.sample_rate, device=self.output_device)
        sd.wait()
        time.sleep(0.05)

if __name__ == "__main__":
    print(f"🧪 [DEBUG] Mode test Synthèse vocale (Modèle: {TTS_MODEL_PATH}, Vitesse: {TTS_SPEECH_SPEED})...")
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

