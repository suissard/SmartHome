"""
Pipeline vocal en streaming : les phrases sont synthétisées dans un thread pendant que les précédentes
sont jouées dans un autre. `interrupt()` vide la file et coupe la lecture en cours (barge-in).

Le « sink » reçoit l'audio de chaque phrase : lecture sur les haut-parleurs par défaut, ou envoi
à un client distant (la passerelle fournit son propre sink).
"""

import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

AudioSink = Callable[[np.ndarray, int], None]
_POLL_SECONDS = 0.02


class SpeechPipeline:
    def __init__(self, tts, sink: Optional[AudioSink] = None, output_device=None):
        self.tts = tts
        self.output_device = output_device
        self.sink = sink or self._play_local
        self._texts: queue.Queue = queue.Queue()
        self._audio: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        # Chaque interruption ouvre une nouvelle « génération » : les éléments plus anciens sont ignorés
        self._generation = 0
        self._pending = 0
        self._idle = threading.Condition()
        threading.Thread(target=self._synthesize_loop, name="speech-synth", daemon=True).start()
        threading.Thread(target=self._play_loop, name="speech-play", daemon=True).start()

    # ---- API ----
    def say(self, text: str):
        if not (text or "").strip():
            return
        with self._idle:
            self._pending += 1
        self._texts.put((self._generation, text))

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Attend la fin de tout ce qui a été demandé. Retourne False si le délai expire."""
        with self._idle:
            return self._idle.wait_for(lambda: self._pending == 0, timeout)

    def say_and_wait(self, text: str):
        self.say(text)
        self.wait()

    @property
    def busy(self) -> bool:
        return self._pending > 0

    def interrupt(self):
        """Abandonne les phrases en attente et coupe celle en cours de lecture."""
        self._generation += 1
        self._stop.set()

    def close(self):
        """Arrête les threads une fois la file traitée (pipeline créé pour une seule demande)."""
        self._texts.put(None)

    # ---- Threads ----
    def _done(self):
        with self._idle:
            self._pending = max(0, self._pending - 1)
            self._idle.notify_all()

    def _synthesize_loop(self):
        while True:
            item = self._texts.get()
            if item is None:
                self._audio.put(None)
                return
            generation, text = item
            if generation != self._generation:
                self._done()
                continue
            try:
                samples, sample_rate = self.tts.synthesize(text)
            except Exception as e:
                print(f"⚠️ [SPEECH] Synthèse impossible : {e}")
                samples, sample_rate = np.zeros(0, dtype=np.int16), 0
            self._audio.put((generation, samples, sample_rate))

    def _play_loop(self):
        while True:
            item = self._audio.get()
            if item is None:
                return
            generation, samples, sample_rate = item
            try:
                if generation == self._generation and len(samples):
                    self._stop.clear()
                    self.sink(samples, sample_rate)
            except Exception as e:
                print(f"⚠️ [SPEECH] Lecture impossible : {e}")
            finally:
                self._done()

    def _play_local(self, samples: np.ndarray, sample_rate: int):
        import sounddevice as sd
        sd.play(samples, samplerate=sample_rate, device=self.output_device)
        # Lecture surveillée plutôt que sd.wait() : une interruption doit couper le son immédiatement
        while sd.get_stream().active:
            if self._stop.is_set():
                sd.stop()
                return
            time.sleep(_POLL_SECONDS)


if __name__ == "__main__":
    from audio.tts import TextToSpeech
    print("🧪 [DEBUG] Pipeline vocal : trois phrases enchaînées, la synthèse de la suivante pendant la lecture")
    pipeline = SpeechPipeline(TextToSpeech())
    t0 = time.perf_counter()
    for sentence in ("Première phrase, prononcée dès qu'elle est prête.",
                     "La deuxième a été synthétisée pendant la lecture de la première.",
                     "Et voici la troisième."):
        pipeline.say(sentence)
    pipeline.wait()
    print(f"✅ Terminé en {time.perf_counter() - t0:.1f} s")
