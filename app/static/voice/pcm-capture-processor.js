/**
 * AudioWorklet processor: emits Float32 PCM frames + RMS for energy-VAD fallback.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || !input[0].length) {
      return true;
    }

    const channel = input[0];
    const pcm = new Float32Array(channel.length);
    let sumSquares = 0;

    for (let i = 0; i < channel.length; i += 1) {
      const sample = channel[i];
      pcm[i] = sample;
      sumSquares += sample * sample;
    }

    const rms = Math.sqrt(sumSquares / channel.length);
    this.port.postMessage({ pcm, rms });
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
