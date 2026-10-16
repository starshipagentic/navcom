/* Bounded PCM capture. No input is passed to the output speaker. */
class NavcomCapture extends AudioWorkletProcessor {
  constructor() { super(); this.remaining = sampleRate * 20; }
  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length || this.remaining <= 0) return this.remaining > 0;
    const count = Math.min(channels[0].length, this.remaining);
    const mono = new Float32Array(count);
    for (const channel of channels) for (let i = 0; i < count; i++) mono[i] += channel[i] / channels.length;
    this.port.postMessage(mono, [mono.buffer]);
    this.remaining -= count;
    if (this.remaining <= 0) this.port.postMessage('done');
    return this.remaining > 0;
  }
}
registerProcessor('navcom-capture', NavcomCapture);
