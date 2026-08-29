import sys
from pathlib import Path
import numpy as np
import sounddevice as sd

# Inclusion de la racine du projet
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import AUDIO_OUTPUT_DEVICE_INDEX, AUDIO_INPUT_DEVICE_INDEX


if __name__ == "__main__":
    print("1. Liste des périphériques audio détectés :")
    print(sd.query_devices())

    print(f"\n👉 Sortie par défaut du système : index {sd.default.device[1]}")
    print(f"👉 Sortie configurée (.env)     : index {AUDIO_OUTPUT_DEVICE_INDEX}")
    print(f"👉 Entrée configurée (.env)     : index {AUDIO_INPUT_DEVICE_INDEX}")

    # Test d'un son simple (bip de 1 seconde à 440 Hz)
    print("\n2. Test de lecture d'un bip sonore de 1s...")
    fs = 44100
    t = np.linspace(0, 1, fs, False)
    tone = np.sin(2 * np.pi * 440 * t) * 0.3
    sd.play(tone, samplerate=fs, device=AUDIO_OUTPUT_DEVICE_INDEX)
    sd.wait()
    print("Fin du test !")


