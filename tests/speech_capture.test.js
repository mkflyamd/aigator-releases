// Dictation capture: utterance segmentation over 16 kHz mono PCM16.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'speech-capture.js'),
  'utf8',
);
const sandbox = { window: {}, navigator: {}, console };
vm.runInNewContext(source, sandbox);
const { createSegmenter, floatToInt16, FRAME, SAMPLE_RATE, MAX_UTTERANCE_SAMPLES, MIN_SPEECH_FRAMES } =
  sandbox.window.GatorSpeechCapture;

const SPEECH = 4000;

function signal(ms, amp) {
  const n = Math.round((SAMPLE_RATE * ms) / 1000);
  const a = new Int16Array(n);
  for (let i = 0; i < n; i++) a[i] = i % 2 ? amp : -amp;
  return a;
}

function run(chunks, blockSize) {
  const out = [];
  const seg = createSegmenter((pcm) => out.push(pcm));
  for (const c of chunks) {
    for (let i = 0; i < c.length; i += blockSize) seg.push(c.subarray(i, i + blockSize));
  }
  return { out, seg };
}

test('silence produces no utterance', () => {
  const { out, seg } = run([signal(3000, 0)], 128);
  seg.flush();
  assert.strictEqual(out.length, 0);
});

test('speech followed by a pause produces one utterance', () => {
  const { out } = run([signal(500, 0), signal(1000, SPEECH), signal(1500, 0)], 128);
  assert.strictEqual(out.length, 1);
  const ms = (out[0].length / SAMPLE_RATE) * 1000;
  assert.ok(ms >= 1000 && ms <= 1000 + 300 + 800, `utterance length ${ms} ms`);
});

test('utterance includes pre-roll before the first loud frame', () => {
  const { out } = run([signal(1000, 0), signal(600, SPEECH), signal(1500, 0)], 160);
  const first = out[0];
  assert.strictEqual(first[0], 0, 'starts inside the pre-roll silence');
  assert.ok(first.length > signal(600, 0).length + (SAMPLE_RATE * 0.25));
});

test('a short blip is dropped', () => {
  const blip = signal((MIN_SPEECH_FRAMES - 4) * 20, SPEECH);
  const { out } = run([signal(500, 0), blip, signal(1500, 0)], 128);
  assert.strictEqual(out.length, 0);
});

test('two phrases separated by a long pause produce two utterances', () => {
  const { out } = run(
    [signal(800, SPEECH), signal(1200, 0), signal(800, SPEECH), signal(1200, 0)],
    128,
  );
  assert.strictEqual(out.length, 2);
});

test('a short pause inside a phrase does not split it', () => {
  const { out } = run([signal(800, SPEECH), signal(300, 0), signal(800, SPEECH), signal(1500, 0)], 128);
  assert.strictEqual(out.length, 1);
});

test('continuous speech is force-cut at the maximum length', () => {
  const { out, seg } = run([signal(25000, SPEECH)], 4096);
  assert.ok(out.length >= 1);
  assert.strictEqual(out[0].length, MAX_UTTERANCE_SAMPLES);
  seg.flush();
  for (const u of out) assert.ok(u.length <= MAX_UTTERANCE_SAMPLES);
});

test('flush emits a pending utterance', () => {
  const { out, seg } = run([signal(1000, SPEECH)], 128);
  assert.strictEqual(out.length, 0);
  seg.flush();
  assert.strictEqual(out.length, 1);
});

test('reset discards a pending utterance', () => {
  const { out, seg } = run([signal(1000, SPEECH)], 128);
  seg.reset();
  seg.flush();
  assert.strictEqual(out.length, 0);
});

test('block size does not change the result', () => {
  const chunks = [signal(500, 0), signal(900, SPEECH), signal(1500, 0)];
  const a = run(chunks, 128).out;
  const b = run(chunks, 1000).out;
  assert.strictEqual(a.length, b.length);
  assert.strictEqual(a[0].length, b[0].length);
});

test('floatToInt16 scales and clamps', () => {
  const out = floatToInt16(new Float32Array([0, 0.5, -0.5, 1, -1, 2, -2]));
  assert.deepStrictEqual(Array.from(out), [0, 16383, -16384, 32767, -32768, 32767, -32768]);
});
