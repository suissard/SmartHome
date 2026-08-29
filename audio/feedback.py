import os
import sys
import time
from pathlib import Path
import numpy as np
import sounddevice as sd

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import (
    AUDIO_OUTPUT_DEVICE_INDEX,
    FEEDBACK_WAKEWORD_TYPE,
    FEEDBACK_WAKEWORD_TEXT,
    FEEDBACK_WAKEWORD_SOUND,
    FEEDBACK_RESPONSE_END_TYPE,
    FEEDBACK_RESPONSE_END_SOUND,
    FEEDBACK_RESPONSE_END_TEXT,
    FEEDBACK_TIMEOUT_TYPE,
    FEEDBACK_TIMEOUT_TEXT,
    FEEDBACK_TIMEOUT_SOUND,
    FEEDBACK_SOUND_VOLUME,
)


SAMPLE_RATE = 44100


def _apply_envelope(audio: np.ndarray, attack_ms: float = 8.0, decay_type: str = "exp") -> np.ndarray:
    """Applique une enveloppe pour éviter tout claquement numérique (anti-pop)."""
    n = len(audio)
    if n == 0:
        return audio
    
    attack_len = min(int((attack_ms / 1000.0) * SAMPLE_RATE), n // 4)
    envelope = np.ones(n, dtype=np.float32)

    # Attaque douce
    if attack_len > 0:
        envelope[:attack_len] = np.linspace(0.0, 1.0, attack_len)

    # Décroissance
    if decay_type == "exp":
        t = np.linspace(0.0, 1.0, n)
        decay = np.exp(-4.5 * t)
        envelope *= decay
    elif decay_type == "linear":
        release_len = min(int((20.0 / 1000.0) * SAMPLE_RATE), n // 4)
        if release_len > 0:
            envelope[-release_len:] = np.linspace(1.0, 0.0, release_len)

    return (audio * envelope).astype(np.float32)


def generate_procedural_sound(sound_name: str, volume: float = 0.5) -> np.ndarray:
    """
    Génère un signal audio harmonique synthétisé pour les retours sonores.
    Tous les sons sont calculés pour être doux et modernes (style smart speaker).
    """
    vol = max(0.0, min(1.0, volume))
    sound_name = sound_name.lower().strip()

    if sound_name in ("wake", "chime_up", "reveil"):
        # Accord ascendant fluide : C5 (523 Hz) -> E5 (659 Hz) -> G5 (784 Hz)
        notes = [523.25, 659.25, 783.99]
        durations = [0.07, 0.07, 0.14]
        chunks = []
        for freq, dur in zip(notes, durations):
            n_samples = int(SAMPLE_RATE * dur)
            t = np.linspace(0, dur, n_samples, False)
            wave = (np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * (freq * 2) * t)) * vol
            wave = _apply_envelope(wave, attack_ms=6.0, decay_type="exp")
            chunks.append(wave)
        return np.concatenate(chunks)

    elif sound_name in ("ding", "listen", "turn_end", "bip_court"):
        # Tintement doux / clochette (La5 - 880 Hz + harmonique 1760 Hz avec amortissement rapide)
        dur = 0.16
        n_samples = int(SAMPLE_RATE * dur)
        t = np.linspace(0, dur, n_samples, False)
        wave = (np.sin(2 * np.pi * 880.0 * t) + 0.3 * np.sin(2 * np.pi * 1760.0 * t)) * vol
        return _apply_envelope(wave, attack_ms=4.0, decay_type="exp")

    elif sound_name in ("sleep", "chime_down", "veille", "bye"):
        # Accord descendant chaleureux : E5 (659 Hz) -> C5 (523 Hz) -> G4 (392 Hz)
        notes = [659.25, 523.25, 392.0]
        durations = [0.08, 0.08, 0.18]
        chunks = []
        for freq, dur in zip(notes, durations):
            n_samples = int(SAMPLE_RATE * dur)
            t = np.linspace(0, dur, n_samples, False)
            wave = (np.sin(2 * np.pi * freq * t) + 0.2 * np.sin(2 * np.pi * (freq * 2) * t)) * vol
            wave = _apply_envelope(wave, attack_ms=6.0, decay_type="exp")
            chunks.append(wave)
        return np.concatenate(chunks)

    elif sound_name in ("beep", "bip"):
        # Bip standard pur (600 Hz, 100ms)
        dur = 0.10
        n_samples = int(SAMPLE_RATE * dur)
        t = np.linspace(0, dur, n_samples, False)
        wave = np.sin(2 * np.pi * 600.0 * t) * vol
        return _apply_envelope(wave, attack_ms=10.0, decay_type="linear")

    elif sound_name in ("pop", "click"):
        # Pop court
        dur = 0.04
        n_samples = int(SAMPLE_RATE * dur)
        t = np.linspace(0, dur, n_samples, False)
        wave = np.sin(2 * np.pi * 1000.0 * t) * vol
        return _apply_envelope(wave, attack_ms=2.0, decay_type="exp")

    else:
        # Repli par défaut : ding
        dur = 0.12
        n_samples = int(SAMPLE_RATE * dur)
        t = np.linspace(0, dur, n_samples, False)
        wave = np.sin(2 * np.pi * 880.0 * t) * vol
        return _apply_envelope(wave, attack_ms=4.0, decay_type="exp")


def load_wav_file(file_path: str, volume: float = 0.5) -> tuple[np.ndarray, int]:
    """Charge un fichier audio WAV et retourne (signal_float32, sample_rate)."""
    import wave
    with wave.open(file_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_data = wf.readframes(n_frames)

    if sampwidth == 2:
        audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 1:
        audio = (np.frombuffer(raw_data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    vol = max(0.0, min(1.0, volume))
    return (audio * vol).astype(np.float32), framerate


class FeedbackManager:
    """
    Gestionnaire centralisé des retours sonores et vocaux (TTS)
    pour les événements du cycle de vie de la conversation.
    """

    def __init__(self, tts=None, output_device=AUDIO_OUTPUT_DEVICE_INDEX, volume=FEEDBACK_SOUND_VOLUME):
        self.tts = tts
        self.output_device = output_device
        self.volume = volume

        # Configuration des 3 événements clés
        self.wakeword_type = FEEDBACK_WAKEWORD_TYPE.lower().strip()
        self.wakeword_text = FEEDBACK_WAKEWORD_TEXT
        self.wakeword_sound = FEEDBACK_WAKEWORD_SOUND

        self.response_end_type = FEEDBACK_RESPONSE_END_TYPE.lower().strip()
        self.response_end_sound = FEEDBACK_RESPONSE_END_SOUND
        self.response_end_text = FEEDBACK_RESPONSE_END_TEXT

        self.timeout_type = FEEDBACK_TIMEOUT_TYPE.lower().strip()
        self.timeout_text = FEEDBACK_TIMEOUT_TEXT
        self.timeout_sound = FEEDBACK_TIMEOUT_SOUND

    def play_sound(self, sound_target: str, volume: float = None):
        """Joue un son (soit procédural par nom, soit depuis un fichier WAV)."""
        vol = self.volume if volume is None else volume
        if not sound_target:
            return

        try:
            if os.path.isfile(sound_target):
                audio, sr = load_wav_file(sound_target, volume=vol)
            else:
                audio = generate_procedural_sound(sound_target, volume=vol)
                sr = SAMPLE_RATE

            sd.play(audio, samplerate=sr, device=self.output_device)
            sd.wait()
            time.sleep(0.02)
        except Exception as e:
            print(f"⚠️ [FEEDBACK] Erreur lecture son '{sound_target}': {e}")

    def on_wakeword_detected(self):
        """Déclenché immédiatement après la détection du mot-clé."""
        if self.wakeword_type == "phrase" and self.wakeword_text:
            if self.tts:
                self.tts.speak(self.wakeword_text)
            else:
                print(f"🔊 [TTS] « {self.wakeword_text} »")
        elif self.wakeword_type == "sound" and self.wakeword_sound:
            self.play_sound(self.wakeword_sound)

    def on_response_end(self):
        """Déclenché après la fin de la réponse de l'IA (signal prêt à écouter)."""
        if self.response_end_type == "sound" and self.response_end_sound:
            self.play_sound(self.response_end_sound)
        elif self.response_end_type == "phrase" and self.response_end_text:
            if self.tts:
                self.tts.speak(self.response_end_text)
            else:
                print(f"🔊 [TTS] « {self.response_end_text} »")

    def on_timeout(self):
        """Déclenché lors de l'expiration du délai d'écoute active (mise en veille)."""
        if self.timeout_type == "phrase" and self.timeout_text:
            if self.tts:
                self.tts.speak(self.timeout_text)
            else:
                print(f"🔊 [TTS] « {self.timeout_text} »")
        elif self.timeout_type == "sound" and self.timeout_sound:
            self.play_sound(self.timeout_sound)


if __name__ == "__main__":
    print("🧪 [DEBUG] Mode test des Feedbacks Sonores & Vocaux...")
    fb = FeedbackManager()

    print("\n1. Test des sons procéduraux intégrés :")
    for s_name in ["wake", "ding", "sleep", "beep", "pop"]:
        print(f"  • Son : '{s_name}'")
        fb.play_sound(s_name)
        time.sleep(0.3)

    print("\n2. Test des événements configurés (.env) :")
    print(f"  • Event 1 : Détection mot-clé ({fb.wakeword_type} -> '{fb.wakeword_text}' / '{fb.wakeword_sound}')")
    fb.on_wakeword_detected()

    time.sleep(0.5)
    print(f"  • Event 2 : Fin de réponse IA ({fb.response_end_type} -> '{fb.response_end_sound}' / '{fb.response_end_text}')")
    fb.on_response_end()

    time.sleep(0.5)
    print(f"  • Event 3 : Fin d'écoute active ({fb.timeout_type} -> '{fb.timeout_text}' / '{fb.timeout_sound}')")
    fb.on_timeout()

    print("\n✅ Test terminé.")
