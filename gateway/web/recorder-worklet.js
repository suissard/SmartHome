// Processeur audio : regroupe les trames du micro (128 échantillons) en paquets d'environ 40 ms
// avant de les transmettre au thread principal, pour limiter le nombre de messages.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.length = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      if (this.length + channel.length > this.buffer.length) this.flush();
      this.buffer.set(channel, this.length);
      this.length += channel.length;
    }
    return true;
  }

  flush() {
    if (this.length) this.port.postMessage(this.buffer.slice(0, this.length));
    this.length = 0;
  }
}

registerProcessor("pcm-capture", PcmCapture);
