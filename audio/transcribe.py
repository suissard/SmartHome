import io
import sys
import time
import wave
from pathlib import Path
from collections import deque
import numpy as np
import pyaudio

# Inclusion de la racine du projet pour import autonome
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from core.config import (
    Settings,
    get_settings,
    AUDIO_CHUNK,
    AUDIO_RATE,
    AUDIO_INPUT_DEVICE_INDEX,
    FOLLOW_UP_TIMEOUT,
)
from audio.stt import STT_PROVIDERS, STTProvider, create_stt
from audio.vad import SpeechDetector

CHUNK = AUDIO_CHUNK
RATE = AUDIO_RATE
FORMAT = pyaudio.paInt16



class VoiceTranscriber:
    """Enregistrement micro avec détection d'activité vocale (VAD), puis transcription par le fournisseur STT."""

    def __init__(self, settings: Settings | None = None, stt: STTProvider | None = None, vad: SpeechDetector | None = None):
        s = settings or get_settings()
        self.settings = s
        self.voice_threshold = s.VOICE_THRESHOLD
        self.silence_duration = s.SILENCE_DURATION
        self.follow_up_timeout = s.FOLLOW_UP_TIMEOUT
        self.max_speech_duration = s.MAX_SPEECH_DURATION
        self.min_speech_duration = s.VAD_MIN_SPEECH_DURATION
        self.stt = stt or create_stt(s)
        # Distingue la parole du bruit ambiant : le bruit ne déclenche plus d'enregistrement et n'empêche plus la fin de phrase
        self.vad = vad or SpeechDetector(s)

    def _flush_stream(self, stream):
        """Purge les paquets résiduels dans le micro"""
        try:
            avail = stream.get_read_available()
            if avail > 0:
                stream.read(avail, exception_on_overflow=False)
        except Exception:
            pass

    def record_and_transcribe(
        self,
        stream,
        timeout_silence=None,
        max_speech_duration=None,
        bar_length=20
    ):
        if timeout_silence is None:
            timeout_silence = self.follow_up_timeout
        if max_speech_duration is None:
            max_speech_duration = self.max_speech_duration

        timeout_silence = max(0.1, float(timeout_silence))
        self._flush_stream(stream)
        start_wait = time.time()
        pre_buffer = deque(maxlen=4)
        self.vad.reset()

        while True:
            elapsed = time.time() - start_wait
            remaining = max(0.0, timeout_silence - elapsed)

            # Fin du délai d'attente
            if remaining <= 0 or elapsed >= timeout_silence:
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                return "", 0.0, 0.0

            # Barre d'écoulement dynamique (décompte proportionnel au timeout configuré)
            ratio = max(0.0, min(1.0, remaining / timeout_silence))
            filled = int(round(ratio * bar_length))
            filled = max(0, min(bar_length, filled))
            bar = "█" * filled + "░" * (bar_length - filled)
            sys.stdout.write(f"\r⏳ Veille active : [{bar}] {remaining:4.1f}s / {timeout_silence:.1f}s ")
            sys.stdout.flush()

            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            pre_buffer.append(data)

            # Voix détectée -> Enregistrement
            if self.vad.is_speech_start(chunk):
                sys.stdout.write("\r" + " " * 80 + "\r🎤 [Enregistrement...] ")
                sys.stdout.flush()

                frames = list(pre_buffer)
                speech_chunks = 1
                silent_chunks = 0
                # Durées mesurées en temps audio (trames lues), indépendamment de la vitesse de lecture du flux
                chunk_seconds = CHUNK / RATE
                max_chunks = int(max_speech_duration / chunk_seconds)

                for _ in range(max_chunks):
                    s_data = stream.read(CHUNK, exception_on_overflow=False)
                    s_chunk = np.frombuffer(s_data, dtype=np.int16)
                    frames.append(s_data)

                    if self.vad.is_speech_continuing(s_chunk):
                        speech_chunks += 1
                        silent_chunks = 0
                    else:
                        silent_chunks += 1
                        if silent_chunks * chunk_seconds > self.silence_duration:
                            break

                # Analyse seulement si l'enregistrement contient assez de parole (un bruit bref n'est pas transcrit)
                if speech_chunks * CHUNK / RATE >= self.min_speech_duration:
                    sys.stdout.write("\r" + " " * 80 + "\r⚙️ [Analyse en cours...] ")
                    sys.stdout.flush()

                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(RATE)
                        wf.writeframes(b"".join(frames))
                    wav_buffer.seek(0)

                    t0 = time.perf_counter()
                    aud_d = (len(frames) * CHUNK) / RATE

                    # Si mode Direct Audio : renvoie directement les octets WAV sans transcription
                    if self.stt.passthrough:
                        sys.stdout.write("\r" + " " * 80 + "\r")
                        sys.stdout.flush()
                        return wav_buffer.getvalue(), time.perf_counter() - t0, aud_d

                    text = ""
                    try:
                        text = self.stt.transcribe(wav_buffer.getvalue())
                    except Exception as e:
                        print(f"\n⚠️ Erreur de transcription : {e}")

                    inf_t = time.perf_counter() - t0

                    sys.stdout.write("\r" + " " * 80 + "\r")
                    sys.stdout.flush()

                    if text:
                        return text, inf_t, aud_d

                # Bruit parasite ignoré : réinitialisation rapide
                sys.stdout.write("\r" + " " * 80 + "\r")
                self._flush_stream(stream)
                pre_buffer.clear()
                self.vad.reset()


# Alias de compatibilité
Transcriber = VoiceTranscriber


if __name__ == "__main__":
    s = get_settings()
    print(f"🧪 [DEBUG] Mode test Transcription ({STT_PROVIDERS.get(s.STT_PROVIDER).describe(s)}, Timer: {FOLLOW_UP_TIMEOUT}s)...")
    transcriber = VoiceTranscriber()
    p = pyaudio.PyAudio()
    stream = p.open(
        format=FORMAT,
        channels=1,
        rate=RATE,
        input=True,
        input_device_index=AUDIO_INPUT_DEVICE_INDEX,
        frames_per_buffer=CHUNK
    )

    try:
        while True:
            result, inf_t, aud_t = transcriber.record_and_transcribe(stream, timeout_silence=FOLLOW_UP_TIMEOUT)
            if isinstance(result, bytes) and result:
                print(f"👉 Audio brut capté : {len(result)} octets (durée {aud_t:.2f}s)\n")
            elif result:
                print(f"👉 Texte : « {result} » ({inf_t:.2f}s)\n")
            else:
                print("😴 Fin du décompte.\n")
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

