/* GatorSpeechCapture — microphone capture and utterance segmentation for
 * dictation. Produces 16 kHz mono PCM16 utterances; knows nothing about the
 * DOM or the network. */
(function () {
  'use strict';

  var SAMPLE_RATE = 16000;
  var FRAME = 320; // 20 ms
  var RMS_THRESHOLD = 350; // Int16 scale
  var START_FRAMES = 3; // consecutive loud frames that begin an utterance
  var PRE_ROLL_FRAMES = 15; // 300 ms of audio kept before the first loud frame
  var HANGOVER_FRAMES = 35; // 700 ms of silence ends an utterance
  var MIN_SPEECH_FRAMES = 13; // ~260 ms of loud frames, shorter is dropped
  var MAX_UTTERANCE_SAMPLES = 20 * SAMPLE_RATE;
  var MAX_UTTERANCE_FRAMES = MAX_UTTERANCE_SAMPLES / FRAME;

  function floatToInt16(f32) {
    var out = new Int16Array(f32.length);
    for (var i = 0; i < f32.length; i++) {
      var s = Math.max(-1, Math.min(1, f32[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function rms(frame) {
    var sum = 0;
    for (var i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    return Math.sqrt(sum / frame.length);
  }

  function concat(frames) {
    var out = new Int16Array(frames.length * FRAME);
    for (var i = 0; i < frames.length; i++) out.set(frames[i], i * FRAME);
    return out;
  }

  function createSegmenter(onUtterance) {
    var pending = new Int16Array(0); // samples not yet forming a full frame
    var ring = []; // idle: recent frames (pre-roll plus the loud run)
    var loudRun = 0;
    var speaking = false;
    var frames = []; // current utterance
    var speechFrames = 0;
    var silentRun = 0;

    function emit() {
      if (speechFrames >= MIN_SPEECH_FRAMES) onUtterance(concat(frames));
      frames = [];
      speechFrames = 0;
      silentRun = 0;
      speaking = false;
      ring = [];
      loudRun = 0;
    }

    function onFrame(frame) {
      var loud = rms(frame) >= RMS_THRESHOLD;
      if (!speaking) {
        ring.push(frame);
        if (ring.length > PRE_ROLL_FRAMES + START_FRAMES) ring.shift();
        loudRun = loud ? loudRun + 1 : 0;
        if (loudRun >= START_FRAMES) {
          speaking = true;
          frames = ring.slice();
          speechFrames = loudRun;
          silentRun = 0;
          ring = [];
        }
        return;
      }
      frames.push(frame);
      if (loud) {
        speechFrames++;
        silentRun = 0;
      } else {
        silentRun++;
      }
      if (silentRun >= HANGOVER_FRAMES || frames.length >= MAX_UTTERANCE_FRAMES) emit();
    }

    function push(samples) {
      var buf = samples;
      if (pending.length) {
        buf = new Int16Array(pending.length + samples.length);
        buf.set(pending, 0);
        buf.set(samples, pending.length);
      }
      var i = 0;
      for (; i + FRAME <= buf.length; i += FRAME) onFrame(buf.slice(i, i + FRAME));
      pending = buf.slice(i);
    }

    function flush() {
      if (speaking) emit();
      pending = new Int16Array(0);
      ring = [];
      loudRun = 0;
    }

    function reset() {
      pending = new Int16Array(0);
      ring = [];
      loudRun = 0;
      speaking = false;
      frames = [];
      speechFrames = 0;
      silentRun = 0;
    }

    return { push: push, flush: flush, reset: reset };
  }

  function isSupported() {
    return !!(
      typeof navigator !== 'undefined' &&
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia &&
      typeof window.AudioContext === 'function' &&
      typeof window.AudioWorklet === 'function'
    );
  }

  // Opens the microphone and calls onUtterance(Int16Array) per spoken phrase.
  // Resolves to { stop(flush) } once audio is flowing; rejects if the mic or
  // audio pipeline cannot be opened.
  function start(onUtterance) {
    var stream = null;
    var ctx = null;
    var node = null;
    var segmenter = createSegmenter(onUtterance);

    function teardown() {
      try {
        if (node) node.disconnect();
      } catch (e) {
        /* ignore */
      }
      if (stream) {
        stream.getTracks().forEach(function (t) {
          t.stop();
        });
      }
      if (ctx) ctx.close().catch(function () {});
    }

    return navigator.mediaDevices
      .getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      .then(function (s) {
        stream = s;
        ctx = new window.AudioContext({ sampleRate: SAMPLE_RATE });
        if (ctx.sampleRate !== SAMPLE_RATE) {
          throw new Error('Audio engine cannot run at 16 kHz');
        }
        return ctx.audioWorklet.addModule('/static/speech-worklet.js');
      })
      .then(function () {
        node = new window.AudioWorkletNode(ctx, 'gator-pcm-tap', { numberOfOutputs: 0 });
        node.port.onmessage = function (e) {
          segmenter.push(floatToInt16(e.data));
        };
        ctx.createMediaStreamSource(stream).connect(node);
        return {
          stop: function (flush) {
            if (flush) segmenter.flush();
            else segmenter.reset();
            teardown();
          },
        };
      })
      .catch(function (err) {
        teardown();
        throw err;
      });
  }

  window.GatorSpeechCapture = {
    isSupported: isSupported,
    start: start,
    createSegmenter: createSegmenter,
    floatToInt16: floatToInt16,
    SAMPLE_RATE: SAMPLE_RATE,
    FRAME: FRAME,
    MIN_SPEECH_FRAMES: MIN_SPEECH_FRAMES,
    MAX_UTTERANCE_SAMPLES: MAX_UTTERANCE_SAMPLES,
  };
})();
