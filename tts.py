import time
import numpy as np
import sounddevice as sd
try:
    from piper.voice import PiperVoice, SynthesisConfig
except ImportError:
    from piper import PiperVoice, SynthesisConfig

MODEL_PATH = "voice.onnx"
CONFIG_PATH = "voice.onnx.json"

OUTPUT_DEVICE = None
SPEECH_SPEED = 1.15

class TextToSpeech:
    def __init__(self, model_path=MODEL_PATH, config_path=CONFIG_PATH):
        print("Chargement de Piper... ⏳")
        self.voice = PiperVoice.load(model_path, config_path=config_path)
        self.sample_rate = self.voice.config.sample_rate
        self.syn_config = SynthesisConfig(length_scale=SPEECH_SPEED)
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

        # 3. Fondu de sortie (fade-out de 50ms) pour supprimer tout claquement
        fade_len = int(self.sample_rate * 0.05)
        if len(raw_audio) > fade_len:
            fade_curve = np.linspace(1.0, 0.0, fade_len)
            raw_audio[-fade_len:] *= fade_curve

        raw_audio = raw_audio.astype(np.int16)

        # 4. Tampons de silence (100ms au début, 400ms à la fin)
        silence_start = np.zeros(int(self.sample_rate * 0.10), dtype=np.int16)
        silence_end = np.zeros(int(self.sample_rate * 0.40), dtype=np.int16)
        full_audio = np.concatenate([silence_start, raw_audio, silence_end])

        # 5. Lecture
        sd.play(full_audio, samplerate=self.sample_rate, device=OUTPUT_DEVICE)
        sd.wait()
        time.sleep(0.05)

if __name__ == "__main__":
    print("🧪 [DEBUG] Mode test Synthèse vocale...")
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
