/**
 * Continuous live voice: Silero VAD (human speech), utterance packaging (WAV),
 * and ChatGPT-style barge-in with TTS echo guards.
 *
 * Set vad.engine = "energy" only for the legacy AudioWorklet/Analyser fallback.
 */
(function (global) {
  "use strict";

  const TARGET_SAMPLE_RATE = 16000;
  const SILERO_BUNDLE_URL =
    "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/bundle.min.js";
  const SILERO_ASSET_BASE =
    "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/";
  const ORT_WASM_BASE =
    "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/";

  const DEFAULT_VAD = {
    engine: "silero",
    model: "v5",
    // Stronger positive threshold → ignore fan/keyboard/mixer noise.
    positiveSpeechThreshold: 0.72,
    negativeSpeechThreshold: 0.42,
    redemptionMs: 650,
    minSpeechMs: 420,
    preSpeechPadMs: 280,
    fallbackToEnergy: false,
    sileroScriptUrl: SILERO_BUNDLE_URL,
    // Energy fallback thresholds (unused when Silero works).
    speechRms: 0.025,
    speechStartMs: 180,
    bargeInRms: 0.035,
    silenceHangoverMs: 650,
    bargeInMinMs: 220,
    preRollMs: 280,
    // Frame-level barge-in while assistant is thinking/speaking.
    bargeInSpeechThreshold: 0.74,
    // Stricter during speaker playback — Silero hears TTS as speech.
    bargeInDuringTtsThreshold: 0.9,
    bargeInMinMsDuringTts: 450,
    bargeInGraceMs: 550,
    ttsEchoBaselineMs: 500,
    ttsEchoRmsMultiplier: 1.55,
    ttsEchoRmsDelta: 0.03,
    highConfidenceBypass: 0.94,
    postTtsHangoverMs: 1000,
  };

  const MIC_CONSTRAINTS = {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  };

  function resampleFloat32(input, inputRate, outputRate) {
    if (inputRate === outputRate) {
      return input;
    }

    const ratio = inputRate / outputRate;
    const outputLength = Math.max(1, Math.round(input.length / ratio));
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i += 1) {
      const sourceIndex = i * ratio;
      const left = Math.floor(sourceIndex);
      const right = Math.min(left + 1, input.length - 1);
      const frac = sourceIndex - left;
      output[i] = input[left] * (1 - frac) + input[right] * frac;
    }

    return output;
  }

  function mergeFloat32(chunks) {
    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(total);
    let offset = 0;

    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    return merged;
  }

  function encodeWav(samples, sampleRate) {
    const int16 = new Int16Array(samples.length);

    for (let i = 0; i < samples.length; i += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[i]));
      int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    }

    const buffer = new ArrayBuffer(44 + int16.length * 2);
    const view = new DataView(buffer);

    const writeString = (offset, value) => {
      for (let i = 0; i < value.length; i += 1) {
        view.setUint8(offset + i, value.charCodeAt(i));
      }
    };

    writeString(0, "RIFF");
    view.setUint32(4, 36 + int16.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, int16.length * 2, true);

    let offset = 44;
    for (let i = 0; i < int16.length; i += 1) {
      view.setInt16(offset, int16[i], true);
      offset += 2;
    }

    return new Blob([buffer], { type: "audio/wav" });
  }

  let sileroLoadPromise = null;

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing?.dataset.loaded === "true") {
        resolve();
        return;
      }

      if (existing) {
        existing.remove();
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = true;

      script.addEventListener(
        "load",
        () => {
          script.dataset.loaded = "true";
          resolve();
        },
        { once: true },
      );
      script.addEventListener(
        "error",
        () => reject(new Error(`Could not load ${src}`)),
        { once: true },
      );

      document.head.appendChild(script);
    });
  }

  async function ensureSileroVad(scriptUrl) {
    if (global.vad?.MicVAD) {
      return;
    }

    if (!sileroLoadPromise) {
      sileroLoadPromise = loadScript(scriptUrl).catch((error) => {
        sileroLoadPromise = null;
        throw error;
      });
    }

    await sileroLoadPromise;

    if (!global.vad?.MicVAD) {
      throw new Error("Silero VAD loaded, but MicVAD is unavailable.");
    }
  }

  class LiveVoiceSession {
    constructor(options = {}) {
      this.options = options;
      this.vad = { ...DEFAULT_VAD, ...(options.vad || {}) };
      this.processorUrl =
        options.processorUrl || "/static/voice/pcm-capture-processor.js";

      this._active = false;
      this._mode = "worklet";
      this._state = "idle";
      this._stream = null;
      this._audioContext = null;
      this._workletNode = null;
      this._sileroVad = null;
      this._sileroAcceptingSpeech = false;
      this._analyser = null;
      this._source = null;
      this._segmentRecorder = null;
      this._segmentChunks = [];
      this._frameMs = 0;
      this._preRollFrames = [];
      this._preRollMaxFrames = 8;
      this._speechFrames = [];
      this._inSpeech = false;
      this._speechCandidateMs = 0;
      this._speechMs = 0;
      this._silenceMs = 0;
      this._bargeInMs = 0;
      this._rafId = null;
      this._canBargeIn = false;
      this._bargeInGraceUntil = 0;
      this._ttsPlaybackActive = false;
      this._ttsEchoBaseline = 0;
      this._ttsEchoSamples = 0;
      this._ttsEchoWarmUntil = 0;
      this._frameBargeProgressMs = 0;
      // Discard speech that overlaps TTS / post-TTS reverb.
      this._rejectCurrentSpeech = false;
      this._ignoreUtterancesUntil = 0;
      this._speechStartedDuringTts = false;
      this._bargeInCaptureActive = false;
    }

    isActive() {
      return this._active;
    }

    getState() {
      return this._state;
    }

    setState(state, meta = {}) {
      this._setState(state, meta);
    }

    setCanBargeIn(enabled) {
      this._canBargeIn = Boolean(enabled);
      if (!enabled) {
        this._bargeInMs = 0;
        this._frameBargeProgressMs = 0;
      }
    }

    setBargeInGraceMs(ms) {
      this._bargeInGraceUntil = Date.now() + Math.max(0, ms);
    }

    resetBargeInBaseline() {
      this._bargeInMs = 0;
      this._frameBargeProgressMs = 0;
      this._ttsEchoBaseline = 0;
      this._ttsEchoSamples = 0;
    }

    /**
     * Sync with real TTS speaker output so echo guards activate only while
     * audio is actually playing (not merely queued).
     */
    setTtsPlaybackActive(active) {
      const next = Boolean(active);
      if (next === this._ttsPlaybackActive) {
        return;
      }

      this._ttsPlaybackActive = next;
      if (next) {
        this._ttsEchoBaseline = 0;
        this._ttsEchoSamples = 0;
        this._ttsEchoWarmUntil =
          Date.now() + (this.vad.ttsEchoBaselineMs || 500);
        this.setBargeInGraceMs(this.vad.bargeInGraceMs || 550);
        this._frameBargeProgressMs = 0;
        // Any speech open when TTS starts is almost certainly speaker bleed.
        if (!this._bargeInCaptureActive) {
          this._rejectCurrentSpeech = true;
          this._sileroAcceptingSpeech = false;
          this._speechStartedDuringTts = false;
        }
      } else if (this._bargeInCaptureActive || this._sileroAcceptingSpeech) {
        // Barge-in stopped TTS — keep capturing the user's ongoing utterance.
        this._ttsEchoWarmUntil = 0;
        this._frameBargeProgressMs = 0;
        this._rejectCurrentSpeech = false;
        this._speechStartedDuringTts = false;
        this._ignoreUtterancesUntil = 0;
        this._sileroAcceptingSpeech = true;
        if (this._state !== "user-speaking") {
          this._setState("user-speaking");
        }
      } else {
        this._ttsEchoWarmUntil = 0;
        this._frameBargeProgressMs = 0;
        // Room / speaker tail after TTS ends naturally.
        this._ignoreUtterancesUntil = Math.max(
          this._ignoreUtterancesUntil,
          Date.now() + (this.vad.postTtsHangoverMs || 1000),
        );
        this._rejectCurrentSpeech = true;
        this._sileroAcceptingSpeech = false;
        this._speechStartedDuringTts = false;
        if (this._state === "user-speaking") {
          this._setState("listening");
        }
      }
    }

    /**
     * Hard mute utterance packaging for a short window (e.g. after barge-in).
     */
    ignoreUtterancesFor(ms) {
      // Don't kill an in-flight barge-in capture.
      if (this._bargeInCaptureActive) {
        return;
      }

      this._ignoreUtterancesUntil = Math.max(
        this._ignoreUtterancesUntil,
        Date.now() + Math.max(0, ms || 0),
      );
      this._rejectCurrentSpeech = true;
      this._sileroAcceptingSpeech = false;
      this._speechStartedDuringTts = false;
      this._frameBargeProgressMs = 0;
    }

    _inUtteranceCooldown() {
      return Date.now() < this._ignoreUtterancesUntil;
    }

    isBargeInCaptureActive() {
      return Boolean(this._bargeInCaptureActive);
    }

    isTtsPlaybackActive() {
      return this._ttsPlaybackActive;
    }

    getCaptureMode() {
      return this._mode;
    }

    async start() {
      if (this._active) {
        return;
      }

      if (this.vad.engine === "energy") {
        await this._startEnergyVad();
        return;
      }

      try {
        await ensureSileroVad(this.vad.sileroScriptUrl || SILERO_BUNDLE_URL);
        await this._startSileroVad();
        return;
      } catch (error) {
        this._sileroVad = null;
        this._sileroAcceptingSpeech = false;

        if (this.vad.fallbackToEnergy) {
          console.warn("Silero VAD unavailable, using energy fallback", error);
          await this._startEnergyVad();
          return;
        }

        try {
          await this.stop();
        } catch (stopError) {
          console.warn("Could not clean up failed Silero VAD start", stopError);
        }

        throw new Error(
          "Silero VAD could not start. Check your network connection and microphone permission.",
        );
      }
    }

    async _startSileroVad() {
      this._mode = "silero";
      this._active = true;

      this._sileroVad = await global.vad.MicVAD.new({
        model: this.vad.model || "v5",
        positiveSpeechThreshold: this.vad.positiveSpeechThreshold,
        negativeSpeechThreshold: this.vad.negativeSpeechThreshold,
        redemptionMs: this.vad.redemptionMs,
        minSpeechMs: this.vad.minSpeechMs,
        preSpeechPadMs: this.vad.preSpeechPadMs,
        startOnLoad: false,
        baseAssetPath: this.vad.baseAssetPath || SILERO_ASSET_BASE,
        onnxWASMBasePath: this.vad.onnxWASMBasePath || ORT_WASM_BASE,
        getStream: async () => {
          return navigator.mediaDevices.getUserMedia({
            audio: MIC_CONSTRAINTS,
          });
        },
        onFrameProcessed: (probabilities, frame) => {
          this._handleSileroFrame(probabilities, frame);
        },
        onSpeechStart: () => {
          this._handleSileroSpeechStart();
        },
        onSpeechRealStart: () => {
          this._handleSileroSpeechRealStart();
        },
        onVADMisfire: () => {
          this._handleSileroMisfire();
        },
        onSpeechEnd: (audio) => {
          this._handleSileroSpeechEnd(audio);
        },
      });

      await this._sileroVad.start();
      this._setState("listening", { engine: "silero" });
    }

    async _startEnergyVad() {
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: MIC_CONSTRAINTS,
      });

      this._audioContext = new AudioContext();
      await this._audioContext.resume();
      this._source = this._audioContext.createMediaStreamSource(this._stream);
      this._frameMs = (128 / this._audioContext.sampleRate) * 1000;
      this._preRollMaxFrames = Math.max(
        1,
        Math.ceil(this.vad.preRollMs / this._frameMs),
      );
      const silentGain = this._audioContext.createGain();
      silentGain.gain.value = 0;

      try {
        await this._audioContext.audioWorklet.addModule(this.processorUrl);
        this._workletNode = new AudioWorkletNode(
          this._audioContext,
          "pcm-capture-processor",
        );
        this._workletNode.port.onmessage = (event) => {
          this._handleFrame(event.data);
        };
        this._source.connect(this._workletNode);
        this._workletNode.connect(silentGain);
        silentGain.connect(this._audioContext.destination);
        this._mode = "energy-worklet";
      } catch (error) {
        console.warn("AudioWorklet unavailable, using analyser fallback", error);
        this._mode = "energy-analyser";
        this._analyser = this._audioContext.createAnalyser();
        this._analyser.fftSize = 2048;
        this._source.connect(this._analyser);
        silentGain.connect(this._audioContext.destination);
        this._startAnalyserLoop();
      }

      this._active = true;
      this._setState("listening", { engine: this._mode });
    }

    async stop() {
      if (!this._active) {
        return;
      }

      this._active = false;
      this._cancelAnalyserLoop();
      this._ttsPlaybackActive = false;

      if (this._sileroVad) {
        await this._sileroVad.destroy();
        this._sileroVad = null;
        this._sileroAcceptingSpeech = false;
      }

      if (this._segmentRecorder && this._segmentRecorder.state !== "inactive") {
        await new Promise((resolve) => {
          this._segmentRecorder.onstop = resolve;
          this._segmentRecorder.stop();
        });
      }

      this._segmentRecorder = null;
      this._segmentChunks = [];

      if (this._workletNode) {
        this._workletNode.port.onmessage = null;
        this._workletNode.disconnect();
        this._workletNode = null;
      }

      if (this._analyser) {
        this._analyser.disconnect();
        this._analyser = null;
      }

      if (this._source) {
        this._source.disconnect();
        this._source = null;
      }

      if (this._audioContext) {
        await this._audioContext.close();
        this._audioContext = null;
      }

      if (this._stream) {
        this._stream.getTracks().forEach((track) => track.stop());
        this._stream = null;
      }

      this._resetSpeechBuffer();
      this._setState("idle");
    }

    _setState(state, meta = {}) {
      this._state = state;
      if (typeof this.options.onStateChange === "function") {
        this.options.onStateChange(state, meta);
      }
    }

    _emitLevel(rms) {
      if (typeof this.options.onLevel === "function") {
        this.options.onLevel(rms);
      }
    }

    _resetSpeechBuffer() {
      this._preRollFrames = [];
      this._speechFrames = [];
      this._inSpeech = false;
      this._speechCandidateMs = 0;
      this._speechMs = 0;
      this._silenceMs = 0;
      this._bargeInMs = 0;
      this._frameBargeProgressMs = 0;
      this._sileroAcceptingSpeech = false;
    }

    _rms(frame) {
      if (!frame || !frame.length) {
        return 0;
      }

      let sumSquares = 0;
      for (let index = 0; index < frame.length; index += 1) {
        sumSquares += frame[index] * frame[index];
      }
      return Math.sqrt(sumSquares / frame.length);
    }

    _fireBargeIn() {
      if (!this._canBargeIn) {
        return false;
      }

      const duringTts = this._ttsPlaybackActive || this._state === "speaking";
      this._canBargeIn = false;
      this._frameBargeProgressMs = 0;

      // Keep capturing this utterance so the interruption becomes the next query.
      this._bargeInCaptureActive = true;
      this._rejectCurrentSpeech = false;
      this._speechStartedDuringTts = false;
      this._ignoreUtterancesUntil = 0;
      this._sileroAcceptingSpeech = true;

      if (typeof this.options.onBargeIn === "function") {
        this.options.onBargeIn({
          duringTts,
        });
      }

      this._setState("user-speaking");
      return true;
    }

    _updateTtsEchoBaseline(rms) {
      if (!this._ttsPlaybackActive) {
        return;
      }

      if (Date.now() < this._ttsEchoWarmUntil) {
        this._ttsEchoSamples += 1;
        const alpha = this._ttsEchoSamples === 1 ? 1 : 0.15;
        this._ttsEchoBaseline =
          this._ttsEchoBaseline * (1 - alpha) + rms * alpha;
      }
    }

    _passesTtsEchoGate(probability, rms) {
      if (!this._ttsPlaybackActive) {
        return true;
      }

      if (Date.now() < this._bargeInGraceUntil) {
        return false;
      }

      if (Date.now() < this._ttsEchoWarmUntil && this._ttsEchoSamples < 6) {
        return false;
      }

      const floor = Math.max(this._ttsEchoBaseline, 0.012);
      const required = Math.max(
        floor * (this.vad.ttsEchoRmsMultiplier || 1.55),
        floor + (this.vad.ttsEchoRmsDelta || 0.03),
      );

      // Never allow Silero confidence alone during TTS — playback always looks
      // like speech. Require clear energy above the learned echo floor.
      if (rms < required) {
        return false;
      }

      return probability >= (this.vad.bargeInDuringTtsThreshold || 0.9);
    }

    _handleSileroFrame(probabilities, frame) {
      if (!this._active || this._mode !== "silero") {
        return;
      }

      const rms = this._rms(frame);
      this._emitLevel(rms);
      this._updateTtsEchoBaseline(rms);

      if (!this._canBargeIn) {
        return;
      }

      if (this._state !== "thinking" && this._state !== "speaking") {
        return;
      }

      const duringTts = this._ttsPlaybackActive || this._state === "speaking";
      const threshold = duringTts
        ? this.vad.bargeInDuringTtsThreshold
        : this.vad.bargeInSpeechThreshold;
      const neededMs = duringTts
        ? this.vad.bargeInMinMsDuringTts
        : this.vad.bargeInMinMs;
      const isSpeech = Number(probabilities?.isSpeech || 0);

      if (isSpeech < threshold || !this._passesTtsEchoGate(isSpeech, rms)) {
        this._frameBargeProgressMs = Math.max(
          0,
          this._frameBargeProgressMs - 20,
        );
        return;
      }

      // Silero frames are ~32ms at 16 kHz / 512 samples.
      this._frameBargeProgressMs += 32;

      if (this._frameBargeProgressMs >= neededMs) {
        this._fireBargeIn();
      }
    }

    _handleSileroSpeechStart() {
      if (!this._active || this._mode !== "silero") {
        return;
      }

      if (this._ttsPlaybackActive || this._state === "speaking") {
        // Event-based starts during TTS are almost always speaker echo.
        this._speechStartedDuringTts = true;
        this._sileroAcceptingSpeech = false;
        return;
      }

      if (this._inUtteranceCooldown()) {
        this._sileroAcceptingSpeech = false;
        return;
      }

      if (this._state === "thinking") {
        if (!this._canBargeIn) {
          this._sileroAcceptingSpeech = false;
          return;
        }

        this._fireBargeIn();
        return;
      }

      if (this._state === "listening" || this._state === "user-speaking") {
        this._rejectCurrentSpeech = false;
        this._speechStartedDuringTts = false;
        this._sileroAcceptingSpeech = true;
        this._setState("user-speaking");
        return;
      }

      this._sileroAcceptingSpeech = false;
    }

    _handleSileroSpeechRealStart() {
      if (!this._active || this._mode !== "silero") {
        return;
      }

      if (this._state === "thinking" || this._state === "speaking") {
        const neededMs = this._ttsPlaybackActive
          ? this.vad.bargeInMinMsDuringTts
          : this.vad.bargeInMinMs;
        // Only confirm barge-in via realStart if frame progress is already strong.
        if (
          this._canBargeIn &&
          this._frameBargeProgressMs >= neededMs * 0.8 &&
          !this._ttsPlaybackActive
        ) {
          this._fireBargeIn();
          return;
        }
        return;
      }

      if (this._sileroAcceptingSpeech) {
        this._setState("user-speaking");
      }
    }

    _handleSileroMisfire() {
      this._sileroAcceptingSpeech = false;
      this._frameBargeProgressMs = 0;

      if (this._active && this._state === "user-speaking") {
        this._setState("listening");
      }

      if (
        typeof this.options.onVADMisfire === "function" &&
        (this._ttsPlaybackActive ||
          this._state === "speaking" ||
          this._state === "thinking")
      ) {
        this.options.onVADMisfire();
      }
    }

    _handleSileroSpeechEnd(audio) {
      const acceptingSpeech = this._sileroAcceptingSpeech;
      const fromBargeIn = this._bargeInCaptureActive;
      const reject =
        !fromBargeIn &&
        (this._rejectCurrentSpeech ||
          this._speechStartedDuringTts ||
          this._ttsPlaybackActive ||
          this._inUtteranceCooldown());

      this._sileroAcceptingSpeech = false;
      this._rejectCurrentSpeech = false;
      this._speechStartedDuringTts = false;
      this._bargeInCaptureActive = false;

      if (!this._active || this._mode !== "silero") {
        return;
      }

      if (!acceptingSpeech || reject) {
        if (this._active && this._state === "user-speaking") {
          this._setState("listening");
        }
        return;
      }

      const durationMs = (audio.length / TARGET_SAMPLE_RATE) * 1000;
      const minMs = fromBargeIn
        ? Math.max(280, (this.vad.minSpeechMs || 420) * 0.7)
        : this.vad.minSpeechMs;

      if (durationMs < minMs) {
        this._handleSileroMisfire();
        return;
      }

      const blob = encodeWav(audio, TARGET_SAMPLE_RATE);

      if (typeof this.options.onUtterance === "function") {
        this.options.onUtterance(blob, {
          durationMs,
          format: "audio/wav",
          vad: "silero",
          fromBargeIn,
        });
      }

      if (this._active) {
        this._setState("thinking");
      }
    }

    _handleFrame({ pcm, rms }) {
      if (!this._active) {
        return;
      }

      this._emitLevel(rms);

      this._preRollFrames.push(pcm);
      if (this._preRollFrames.length > this._preRollMaxFrames) {
        this._preRollFrames.shift();
      }

      if (
        this._canBargeIn &&
        (this._state === "thinking" || this._state === "speaking")
      ) {
        const inGrace =
          this._state === "speaking" && Date.now() < this._bargeInGraceUntil;

        if (inGrace) {
          return;
        }

        if (rms >= this.vad.bargeInRms) {
          if (!this._inSpeech) {
            this._canBargeIn = false;
            if (typeof this.options.onBargeIn === "function") {
              this.options.onBargeIn({ duringTts: this._ttsPlaybackActive });
            }
            this._beginSpeechCapture();
            this._setState("user-speaking");
          }

          this._speechFrames.push(pcm);
          this._speechMs += this._frameMs;
          this._silenceMs = 0;
          return;
        }

        if (this._inSpeech) {
          this._speechFrames.push(pcm);
          this._silenceMs += this._frameMs;

          if (this._silenceMs >= this.vad.silenceHangoverMs) {
            this._finalizeUtterance();
          }
        }

        return;
      }

      if (this._state !== "listening" && this._state !== "user-speaking") {
        return;
      }

      if (rms >= this.vad.speechRms) {
        if (!this._inSpeech) {
          this._beginSpeechCapture();
          this._setState("user-speaking");
        }

        this._speechFrames.push(pcm);
        this._speechMs += this._frameMs;
        this._silenceMs = 0;
        return;
      }

      if (!this._inSpeech) {
        return;
      }

      this._speechFrames.push(pcm);
      this._silenceMs += this._frameMs;

      if (this._silenceMs >= this.vad.silenceHangoverMs) {
        this._finalizeUtterance();
      }
    }

    _beginSpeechCapture() {
      this._inSpeech = true;
      this._speechMs = 0;
      this._silenceMs = 0;
      this._speechFrames = [...this._preRollFrames];

      if (this._mode === "analyser" || this._mode === "energy-analyser") {
        this._startSegmentRecorder();
      }
    }

    _finalizeUtterance() {
      const durationMs = this._speechMs;

      if (
        (this._mode === "analyser" || this._mode === "energy-analyser") &&
        this._segmentRecorder
      ) {
        this._stopSegmentRecorder(durationMs);
        return;
      }

      const frames = this._speechFrames;
      this._resetSpeechBuffer();

      if (durationMs < this.vad.minSpeechMs || !frames.length) {
        if (this._active) {
          this._setState("listening");
        }
        return;
      }

      const merged = mergeFloat32(frames);
      const resampled = resampleFloat32(
        merged,
        this._audioContext.sampleRate,
        TARGET_SAMPLE_RATE,
      );
      const blob = encodeWav(resampled, TARGET_SAMPLE_RATE);

      if (typeof this.options.onUtterance === "function") {
        this.options.onUtterance(blob, { durationMs, format: "audio/wav" });
      }

      if (this._active) {
        this._setState("thinking");
      }
    }

    _startSegmentRecorder() {
      if (!this._stream || this._segmentRecorder) {
        return;
      }

      this._segmentChunks = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";

      this._segmentRecorder = new MediaRecorder(this._stream, { mimeType });
      this._segmentRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this._segmentChunks.push(event.data);
        }
      };
      this._segmentRecorder.start();
    }

    async _stopSegmentRecorder(durationMs) {
      const recorder = this._segmentRecorder;
      this._segmentRecorder = null;
      this._resetSpeechBuffer();

      if (!recorder || recorder.state === "inactive") {
        if (this._active) {
          this._setState("listening");
        }
        return;
      }

      await new Promise((resolve) => {
        recorder.onstop = resolve;
        recorder.stop();
      });

      if (durationMs < this.vad.minSpeechMs || !this._segmentChunks.length) {
        if (this._active) {
          this._setState("listening");
        }
        return;
      }

      const blob = new Blob(this._segmentChunks, {
        type: recorder.mimeType || "audio/webm",
      });
      this._segmentChunks = [];

      if (typeof this.options.onUtterance === "function") {
        this.options.onUtterance(blob, {
          durationMs,
          format: blob.type || "audio/webm",
        });
      }

      if (this._active) {
        this._setState("thinking");
      }
    }

    _startAnalyserLoop() {
      const timeDomain = new Uint8Array(this._analyser.fftSize);

      const tick = () => {
        if (
          !this._active ||
          (this._mode !== "analyser" && this._mode !== "energy-analyser")
        ) {
          return;
        }

        this._analyser.getByteTimeDomainData(timeDomain);
        let sumSquares = 0;

        for (let i = 0; i < timeDomain.length; i += 1) {
          const normalized = (timeDomain[i] - 128) / 128;
          sumSquares += normalized * normalized;
        }

        const rms = Math.sqrt(sumSquares / timeDomain.length);
        this._handleFrame({ pcm: new Float32Array(0), rms });
        this._rafId = requestAnimationFrame(tick);
      };

      this._rafId = requestAnimationFrame(tick);
    }

    _cancelAnalyserLoop() {
      if (this._rafId) {
        cancelAnimationFrame(this._rafId);
        this._rafId = null;
      }
    }
  }

  global.LiveVoiceSession = LiveVoiceSession;
})(window);
