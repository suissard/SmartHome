import numpy as np
import sounddevice as sd

print("1. Liste des périphériques de sortie détectés :")
print(sd.query_devices())

print(f"\n👉 Sortie par défaut sélectionnée : index {sd.default.device[1]}")

# Test d'un son simple (bip de 1 seconde à 440 Hz)
print("\n2. Test de lecture d'un bip sonore de 1s...")
fs = 44100
t = np.linspace(0, 1, fs, False)
tone = np.sin(2 * np.pi * 440 * t) * 0.3
sd.play(tone, samplerate=fs)
sd.wait()
print("Fin du test !")
