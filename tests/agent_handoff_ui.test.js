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

// readiness: output seen, quiet for 800 ms, painted rows; OpenCode also needs a TUI frame
{
  const base = {
    agent: 'claude',
    outputChars: 500,
    lastOutputAt: 1000,
    paintedRows: 5,
    frameReady: false,
  };
  assert.strictEqual(h.isInputReady(base, 1799), false);
  assert.strictEqual(h.isInputReady(base, 1800), true);
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
