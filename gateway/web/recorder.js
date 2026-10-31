// Capture micro dans le navigateur : AudioWorklet -> détection de fin de phrase -> WAV PCM 16 bits mono.
// Les seuils viennent de la passerelle (VOICE_THRESHOLD, SILENCE_DURATION, MAX_SPEECH_DURATION du .env).

export class Recorder {
  constructor({ targetRate, voiceThreshold, silenceDuration, maxDuration, autoStop, onLevel, onAutoStop }) {
    Object.assign(this, { targetRate, voiceThreshold, silenceDuration, maxDuration, autoStop, onLevel, onAutoStop });
    this.chunks = [];
    this.hadSpeech = false;
    this.lastVoiceAt = 0;
    this.startedAt = 0;
    this.stopped = false;
  }

  async start(audioCtx) {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("getUserMedia indisponible");
    this.ctx = audioCtx;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await this.ctx.audioWorklet.addModule("recorder-worklet.js");
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm-capture");
    this.node.port.onmessage = (e) => this.onChunk(e.data);
    // Un gain nul vers la sortie garantit que le graphe est traité sans renvoyer le micro dans le haut-parleur
    this.sink = this.ctx.createGain();
    this.sink.gain.value = 0;
    this.source.connect(this.node).connect(this.sink).connect(this.ctx.destination);
    this.startedAt = performance.now();
  }

  onChunk(samples) {
    if (this.stopped) return;
    this.chunks.push(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += Math.abs(samples[i]);
    const level = sum / samples.length;
    this.onLevel?.(level);

    const now = performance.now();
    if (level > this.voiceThreshold) {
      this.hadSpeech = true;
      this.lastVoiceAt = now;
    }
    const silenceOver = this.hadSpeech && now - this.lastVoiceAt > this.silenceDuration * 1000;
    const tooLong = now - this.startedAt > this.maxDuration * 1000;
    if ((this.autoStop && silenceOver) || tooLong) this.onAutoStop?.();
  }

  stop() {
    this.stopped = true;
    this.source?.disconnect();
    this.node?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());

    const merged = concat(this.chunks);
    const resampled = downsample(merged, this.ctx.sampleRate, this.targetRate);
    return { wav: encodeWav(resampled, this.targetRate), hadSpeech: this.hadSpeech && merged.length > 0 };
  }
}

function concat(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

// Moyenne par paquets : rééchantillonnage simple avec un léger filtrage anti-repliement
export function downsample(samples, inRate, outRate) {
  if (outRate >= inRate) return samples;
  const ratio = inRate / outRate;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);          // taille du bloc fmt
  view.setUint16(20, 1, true);           // PCM
  view.setUint16(22, 1, true);           // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buffer);
}

export function toBase64(bytes) {
  let binary = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) binary += String.fromCharCode(...bytes.subarray(i, i + step));
  return btoa(binary);
}
