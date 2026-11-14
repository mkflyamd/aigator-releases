const assert = require('assert');
const fs = require('fs');
const path = require('path');

const d = require('../web/static/agent-limit-detect.js');
const FIX = path.join(__dirname, '..', 'web', 'tests', 'fixtures', 'limit_messages');
const ESC = String.fromCharCode(27);

for (const agent of ['claude', 'codex', 'opencode-bare', 'crush']) {
  const lines = fs
    .readFileSync(path.join(FIX, agent + '.txt'), 'utf8')
    .split('\n')
    .filter(Boolean);
  assert(lines.length >= 2, agent + ' fixture is empty');
  for (const line of lines) assert(d.detect(agent, line), agent + ' must match: ' + line);
}

const ordinary = [
  'Reading src/limits.js',
  'Added rate limiting middleware to the API',
  'All 12 tests passed',
  'Updated the budget planning doc',
  'npm run build',
];
for (const agent of ['claude', 'codex', 'opencode-bare', 'crush', 'terminal']) {
  for (const line of ordinary) assert(!d.detect(agent, line), agent + ' false positive: ' + line);
}
assert(!d.detect('terminal', 'Claude usage limit reached'), 'bare terminal is never offered');
assert(!d.detect('codex', 'Claude usage limit reached.'), 'patterns are per agent');

assert.strictEqual(d.stripAnsi(ESC + '[31mred' + ESC + '[0m\r\nok'), 'red\nok');
assert(d.detect('claude', ESC + '[31mClaude usage limit reached' + ESC + '[0m'));

// feed: one offer per event, matches across chunks, resets after the agent works again
{
  const sess = { agent: 'claude' };
  let offers = 0;
  const onLimit = () => (offers += 1);
  assert.strictEqual(d.feed(sess, 'Claude usage ', onLimit, 1000), false);
  assert.strictEqual(d.feed(sess, 'limit reached\n', onLimit, 1001), true);
  assert.strictEqual(d.feed(sess, 'more text', onLimit, 1002), false);
  assert.strictEqual(offers, 1);
  d.feed(sess, 'x'.repeat(5000), onLimit, 2000); // working again, tail no longer matches
  assert.strictEqual(sess._limitOffered, false);
  assert.strictEqual(d.feed(sess, 'Claude usage limit reached', onLimit, 3000), true);
  assert.strictEqual(offers, 2);
}

// feed: not offered within 60 s of a handoff into this pane
{
  const sess = { agent: 'crush', _handedOffAt: 10000 };
  let offers = 0;
  d.feed(sess, '429 Too Many Requests', () => (offers += 1), 10000 + 59000);
  assert.strictEqual(offers, 0);
  const later = { agent: 'crush', _handedOffAt: 10000 };
  d.feed(later, '429 Too Many Requests', () => (offers += 1), 10000 + 61000);
  assert.strictEqual(offers, 1);
}
console.log('agent_limit_detect ok');
