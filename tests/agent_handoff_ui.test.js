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

// targets, grouping, and warnings
{
  const targets = [
    { agent: 'claude', label: 'Claude Code', gateway_routed: true, installed: true },
    { agent: 'crush', label: 'Crush', gateway_routed: true, installed: true },
    { agent: 'cursor', label: 'Cursor', gateway_routed: false, installed: true },
    { agent: 'codex', label: 'Codex', gateway_routed: false, installed: false },
  ];
  const ids = (sections) => sections.map((s) => [s.key, s.items.map((t) => t.agent)]);
  assert.deepStrictEqual(ids(h.groupTargets(targets, 'claude', '')), [
    ['routed', ['crush', 'claude']],
    ['own', ['cursor']],
    ['missing', ['codex']],
  ]);
  assert.deepStrictEqual(ids(h.groupTargets(targets, 'claude', ' CU')), [['own', ['cursor']]]);
  assert.deepStrictEqual(h.groupTargets(targets, 'claude', 'zzz'), []);
  assert.strictEqual(h.defaultTarget(targets, 'claude').agent, 'crush');
  assert.strictEqual(h.defaultTarget(targets.slice(0, 1), 'claude').agent, 'claude');
  assert.strictEqual(h.defaultTarget([targets[3]], 'claude'), null);
  assert.strictEqual(h.oneLine('  fix the\n\n  bug\tnow '), 'fix the bug now');
  assert.strictEqual(h.oneLine(null), '');
  assert.strictEqual(h.oneLine('x'.repeat(500)).length, 300);
  assert.strictEqual(h.targetWarning(targets[1]), '');
  const warn = h.targetWarning(targets[2]);
  assert(warn.startsWith('Runs on its own configuration, outside the AI Gator gateway.'));
  assert(/own provider/.test(warn), 'says where the carried-over session goes');
  assert(/best-effort/.test(h.REDACTION_NOTE) && /may remain/.test(h.REDACTION_NOTE));
  assert(!/guarantee|safe|removed/i.test(h.REDACTION_NOTE), 'does not overclaim');
}

// trapTarget: Tab and Shift+Tab wrap inside the dialog; stray focus comes back in
{
  const [a, b, c] = ['a', 'b', 'c'];
  const list = [a, b, c];
  assert.strictEqual(h.trapTarget(list, c, false), a, 'Tab on last wraps to first');
  assert.strictEqual(h.trapTarget(list, a, true), c, 'Shift+Tab on first wraps to last');
  assert.strictEqual(h.trapTarget(list, b, false), null, 'middle is left to the browser');
  assert.strictEqual(h.trapTarget(list, b, true), null);
  assert.strictEqual(h.trapTarget(list, 'outside', false), a, 'outside focus returns to first');
  assert.strictEqual(h.trapTarget(list, 'outside', true), c);
  assert.strictEqual(h.trapTarget([], a, false), null);
}

// prepare body: a live terminal sends pty_session_id, a stored session sends session_id
{
  const state = { projectId: 'demo', repoPath: 'C:\\work\\app' };
  assert.deepStrictEqual(h.prepareBody({ sess: { agent: 'claude', ptySessionId: 'p1' } }, state), {
    agent: 'claude',
    project_id: 'demo',
    repo_path: 'C:\\work\\app',
    pty_session_id: 'p1',
  });
  assert.deepStrictEqual(
    h.prepareBody({ sess: { agent: 'codex' }, stored: { agent: 'codex', id: 'abc-1' } }, state),
    { agent: 'codex', project_id: 'demo', repo_path: 'C:\\work\\app', session_id: 'abc-1' },
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
