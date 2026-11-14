const assert = require('assert');
const h = require('../web/static/agent-handoff.js');
const ESC = String.fromCharCode(27);

// bracketed paste: wrapped, no trailing newline, embedded escapes cannot end the paste early
{
  const out = h.bracketedPaste('line1\r\nline2');
  assert.strictEqual(out, ESC + '[200~line1\nline2' + ESC + '[201~');
  const hostile = h.bracketedPaste('a' + ESC + '[201~' + 'rm -rf');
  assert.strictEqual(hostile.split(ESC + '[201~').length, 2, 'only the final end marker survives');
  assert(!/[\r\n]$/.test(out));
}

// bracketed paste: ESC, C0 controls (except newline and tab), DEL and C1 are all stripped
{
  const C1_CSI = String.fromCharCode(0x9b);
  const hostile =
    'a' + String.fromCharCode(0, 1, 7, 8, 11, 12, 14, 26, 27, 31, 127, 0x80, 0x9b, 0x9f) + 'b';
  assert.strictEqual(h.bracketedPaste(hostile), ESC + '[200~ab' + ESC + '[201~');
  assert.strictEqual(
    h.bracketedPaste('x\ty\nz' + C1_CSI + '201~'),
    ESC + '[200~x\ty\nz201~' + ESC + '[201~',
    'newline and tab survive, a one-character CSI does not',
  );
  assert.strictEqual(h.bracketedPaste('x\r\ny\rz'), ESC + '[200~x\ny\nz' + ESC + '[201~');
}

// bracketed-paste mode tracking: 2004h on, 2004l off, sequences split across chunks
{
  const on = ESC + '[?2004h';
  const off = ESC + '[?2004l';
  let s = h.trackBracketedPaste(null, 'banner');
  assert.strictEqual(s.enabled, false);
  s = h.trackBracketedPaste(s, 'x' + on + 'y');
  assert.strictEqual(s.enabled, true);
  s = h.trackBracketedPaste(s, 'plain output');
  assert.strictEqual(s.enabled, true, 'stays on until it is turned off');
  s = h.trackBracketedPaste(s, off);
  assert.strictEqual(s.enabled, false);
  s = h.trackBracketedPaste(s, on + 'more' + off + on);
  assert.strictEqual(s.enabled, true, 'the last toggle in a chunk wins');
  // split at every possible boundary
  for (let i = 1; i < on.length; i += 1) {
    let t = h.trackBracketedPaste(null, 'prompt' + on.slice(0, i));
    assert.strictEqual(t.enabled, false);
    t = h.trackBracketedPaste(t, on.slice(i));
    assert.strictEqual(t.enabled, true, 'split at ' + i);
    let u = h.trackBracketedPaste(t, off.slice(0, i));
    u = h.trackBracketedPaste(u, off.slice(i));
    assert.strictEqual(u.enabled, false, 'off split at ' + i);
  }
  assert(h.trackBracketedPaste(null, 'x'.repeat(5000)).tail.length <= 8, 'tail stays small');
}

// start-in-flight accessor: reads the terminal module without touching its internals
{
  delete globalThis._genAgentStartInFlight;
  assert.strictEqual(h.startInFlight('tab'), false, 'no terminal module means not busy');
  globalThis._genAgentStartInFlight = (tabId) => tabId === 'busy';
  assert.strictEqual(h.startInFlight('busy'), true);
  assert.strictEqual(h.startInFlight('idle'), false);
  delete globalThis._genAgentStartInFlight;
}

// readiness: output seen, quiet for 800 ms, painted rows; OpenCode also needs a TUI frame
{
  const base = {
    agent: 'claude',
    bracketedPaste: true,
    outputChars: 500,
    lastOutputAt: 1000,
    paintedRows: 5,
    frameReady: false,
  };
  assert.strictEqual(h.isInputReady(base, 1799), false);
  assert.strictEqual(h.isInputReady(base, 1800), true);
  assert.strictEqual(
    h.isInputReady({ ...base, bracketedPaste: false }, 5000),
    false,
    'a target that has not enabled bracketed paste would submit the prompt on its first newline',
  );
  assert.strictEqual(h.isInputReady({ ...base, bracketedPaste: undefined }, 5000), false);
  assert.strictEqual(h.isInputReady({ ...base, outputChars: 0 }, 5000), false);
  assert.strictEqual(h.isInputReady({ ...base, paintedRows: 1 }, 5000), false);
  assert.strictEqual(h.isInputReady({ ...base, agent: 'opencode-bare' }, 5000), false);
  assert.strictEqual(
    h.isInputReady({ ...base, agent: 'opencode-bare', frameReady: true }, 5000),
    true,
  );
}

// targets and warnings
{
  const targets = [
    { agent: 'claude', label: 'Claude Code', gateway_routed: false },
    { agent: 'crush', label: 'Crush', gateway_routed: true },
  ];
  assert.deepStrictEqual(
    h.visibleTargets(targets, 'claude', true).map((t) => t.agent),
    ['crush'],
  );
  assert.deepStrictEqual(
    h.visibleTargets(targets, 'claude', false).map((t) => t.agent),
    ['claude', 'crush'],
  );
  assert.strictEqual(h.targetWarning(targets[1]), '');
  assert.strictEqual(
    h.targetWarning(targets[0]),
    'Runs on its own configuration, outside the AI Gator gateway.',
  );
}

// draftPrompt: waits for readiness, pastes without Enter; times out without pasting
(async () => {
  let t = 0;
  const opts = { now: () => t, sleep: async (ms) => (t += ms), timeoutMs: 5000 };
  const sent = [];
  const sess = { ws: { readyState: 1, send: (m) => sent.push(JSON.parse(m)) } };

  let probes = 0;
  const readyAfter3 = () => (probes += 1) >= 3;
  assert.strictEqual(await h.draftPrompt(sess, 'hello', readyAfter3, opts), 'delivered');
  assert.strictEqual(sent.length, 1);
  assert.strictEqual(sent[0].type, 'input');
  assert(sent[0].data.endsWith(ESC + '[201~') && !/[\r\n]$/.test(sent[0].data));

  t = 0;
  sent.length = 0;
  assert.strictEqual(await h.draftPrompt(sess, 'hello', () => false, opts), 'unconfirmed');
  assert.strictEqual(sent.length, 0, 'never pastes when readiness is not observed');

  assert.strictEqual(
    await h.draftPrompt({ ws: { readyState: 3 } }, 'x', () => true, opts),
    'failed',
  );
  // error detail: only a non-empty string detail is shown; FastAPI validation arrays fall back
  assert.strictEqual(h.errorDetail({ detail: 'Nope' }, 'fb'), 'Nope');
  assert.strictEqual(h.errorDetail({ detail: [{ loc: ['body'], msg: 'bad' }] }, 'fb'), 'fb');
  assert.strictEqual(h.errorDetail({ detail: '' }, 'fb'), 'fb');
  assert.strictEqual(h.errorDetail({}, 'fb'), 'fb');
  assert.strictEqual(h.errorDetail(null, 'fb'), 'fb');
  console.log('agent_handoff_ui ok');
})();
