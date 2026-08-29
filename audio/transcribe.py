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
    STT_PROVIDER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_STT_MODEL,
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
        provider=STT_PROVIDER,
        model_name=WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
        voice_threshold=VOICE_THRESHOLD,
        silence_duration=SILENCE_DURATION,
        follow_up_timeout=FOLLOW_UP_TIMEOUT,
        max_speech_duration=MAX_SPEECH_DURATION
    ):
        self.provider = provider.lower()
        self.voice_threshold = voice_threshold
        self.silence_duration = silence_duration
        self.follow_up_timeout = follow_up_timeout
        self.max_speech_duration = max_speech_duration
        self.language = WHISPER_LANGUAGE
        self.beam_size = WHISPER_BEAM_SIZE

        if self.provider in ("none", "direct", "bypass"):
            print("Mode Direct Audio actif (Bypass STT ⏩ Multimodal LLM) ✅")
            self.client = None
            self.model = None
        elif self.provider == "openrouter":
            print(f"Chargement STT OpenRouter (Modèle: {OPENROUTER_STT_MODEL})... ⏳")
            from openai import OpenAI
            self.client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=OPENROUTER_API_KEY or "missing-key"
            )
            self.model = None
            print("STT OpenRouter prêt ✅")
        else:
            print(f"Chargement Whisper local ({model_name} sur {device})... ⏳")
            from faster_whisper import WhisperModel
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
            self.client = None
            print("Whisper local prêt ✅")

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
            vol = np.abs(chunk).mean()
            pre_buffer.append(data)

            # Voix détectée -> Enregistrement
            if vol > self.voice_threshold:
                sys.stdout.write("\r" + " " * 80 + "\r🎤 [Enregistrement...] ")
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
                    if self.provider in ("none", "direct", "bypass"):
                        sys.stdout.write("\r" + " " * 80 + "\r")
                        sys.stdout.flush()
                        return wav_buffer.getvalue(), time.perf_counter() - t0, aud_d

                    text = ""
                    try:
                        if self.provider == "openrouter":
                            if not OPENROUTER_API_KEY:
                                print("\n⚠️ Clé API OpenRouter manquante pour la transcription STT.")
                            else:
                                audio_tuple = ("audio.wav", wav_buffer.getvalue(), "audio/wav")
                                transcription = self.client.audio.transcriptions.create(
                                    model=OPENROUTER_STT_MODEL,
                                    file=audio_tuple,
                                    language=self.language if self.language else None
                                )
                                text = transcription.text.strip() if hasattr(transcription, "text") else ""
                        else:
                            segments, _ = self.model.transcribe(
                                wav_buffer,
                                language=self.language,
                                beam_size=self.beam_size,
                                condition_on_previous_text=False
                            )
                            text = " ".join([seg.text for seg in segments]).strip()
                    except Exception as e:
                        print(f"\n⚠️ Erreur de transcription : {e}")

                    inf_t = time.perf_counter() - t0

                    sys.stdout.write("\r" + " " * 80 + "\r")
                    sys.stdout.flush()

                    if text:
                        return text, inf_t, aud_d

                # Bruit parasite ignoré : réinitialisation rapide
                self._flush_stream(stream)
                pre_buffer.clear()


# Alias de compatibilité
Transcriber = VoiceTranscriber


if __name__ == "__main__":

    if STT_PROVIDER in ("none", "direct", "bypass"):
        active_stt = "Bypass (Direct Audio)"
    elif STT_PROVIDER == "openrouter":
        active_stt = OPENROUTER_STT_MODEL
    else:
        active_stt = WHISPER_MODEL

    print(f"🧪 [DEBUG] Mode test Transcription (Fournisseur: {STT_PROVIDER.upper()}, Modèle: {active_stt}, Timer: {FOLLOW_UP_TIMEOUT}s)...")
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

