import io
import sys
import time
import wave
from collections import deque
import numpy as np
import pyaudio
from faster_whisper import WhisperModel
from config import (
    AUDIO_CHUNK,
    AUDIO_RATE,
    AUDIO_INPUT_DEVICE_INDEX,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_LANGUAGE,
    WHISPER_BEAM_SIZE,
    VOICE_THRESHOLD,
    SILENCE_DURATION,
    MAX_SPEECH_DURATION,
    FOLLOW_UP_TIMEOUT,
)

CHUNK = AUDIO_CHUNK
RATE = AUDIO_RATE
FORMAT = pyaudio.paInt16

class VoiceTranscriber:
    def __init__(
        self,
        model_name=WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
        voice_threshold=VOICE_THRESHOLD,
        silence_duration=SILENCE_DURATION
    ):
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.voice_threshold = voice_threshold
        self.silence_duration = silence_duration
        self.language = WHISPER_LANGUAGE
        self.beam_size = WHISPER_BEAM_SIZE

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
        timeout_silence=FOLLOW_UP_TIMEOUT,
        max_speech_duration=MAX_SPEECH_DURATION
    ):
        self._flush_stream(stream)
        start_wait = time.time()
        pre_buffer = deque(maxlen=4)
        bar_length = 20

        while True:
            elapsed = time.time() - start_wait
            remaining = timeout_silence - elapsed

            # Fin du délai d'attente
            if remaining <= 0:
                sys.stdout.write("\r" + " " * 60 + "\r")
                sys.stdout.flush()
                return "", 0.0, 0.0

            # Barre de chargement du timer en direct
            filled = int((elapsed / timeout_silence) * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)
            sys.stdout.write(f"\r⏳ Veille active : [{bar}] {remaining:4.1f}s ")
            sys.stdout.flush()

            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16)
            vol = np.abs(chunk).mean()
            pre_buffer.append(data)

            # Voix détectée -> Enregistrement
            if vol > self.voice_threshold:
                sys.stdout.write("\r" + " " * 60 + "\r🎤 [Enregistrement...] ")
                sys.stdout.flush()

                frames = list(pre_buffer)
                silence_start = None
                speech_start = time.time()

                while (time.time() - speech_start) < max_speech_duration:
                    s_data = stream.read(CHUNK, exception_on_overflow=False)
                    s_chunk = np.frombuffer(s_data, dtype=np.int16)
                    s_vol = np.abs(s_chunk).mean()
                    frames.append(s_data)

                    if s_vol > self.voice_threshold:
                        silence_start = None
                    else:
                        if silence_start is None:
                            silence_start = time.perf_counter()
                        elif time.perf_counter() - silence_start > self.silence_duration:
                            break

                # Analyse seulement si l'enregistrement a capté assez de matière
                if len(frames) > 5:
                    sys.stdout.write("\r" + " " * 60 + "\r⚙️ [Analyse en cours...] ")
                    sys.stdout.flush()

                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(RATE)
                        wf.writeframes(b"".join(frames))
                    wav_buffer.seek(0)

                    t0 = time.perf_counter()
                    segments, _ = self.model.transcribe(
                        wav_buffer,
                        language=self.language,
                        beam_size=self.beam_size,
                        condition_on_previous_text=False
                    )
                    text = " ".join([seg.text for seg in segments]).strip()
                    inf_t = time.perf_counter() - t0
                    aud_d = (len(frames) * CHUNK) / RATE

                    sys.stdout.write("\r" + " " * 60 + "\r")
                    sys.stdout.flush()

                    if text:
                        return text, inf_t, aud_d

                # Bruit parasite ignoré : réinitialisation rapide
                self._flush_stream(stream)
                pre_buffer.clear()

if __name__ == "__main__":
    print(f"🧪 [DEBUG] Mode test Transcription (Modèle={WHISPER_MODEL}, Timer {FOLLOW_UP_TIMEOUT}s)...")
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
            text, inf_t, aud_t = transcriber.record_and_transcribe(stream, timeout_silence=FOLLOW_UP_TIMEOUT)
            if text:
                print(f"👉 Texte : « {text} »\n")
            else:
                print("😴 Fin du décompte.\n")
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

