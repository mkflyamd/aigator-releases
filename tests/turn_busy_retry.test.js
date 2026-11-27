const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const m = source.match(/async function _postChatRetryingBusyTurn\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(m, '_postChatRetryingBusyTurn not found in app.js');

function respond(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    clone() {
      return this;
    },
    async json() {
      return body;
    },
  };
}

function load(responses) {
  const calls = [];
  const sandbox = {
    fetch: async (url, init) => {
      calls.push({ url, body: init.body });
      return responses.shift();
    },
    setTimeout: (fn) => {
      fn();
      return 0;
    },
    JSON,
    Promise,
  };
  const fn = vm.runInNewContext(`${m[0]}\n_postChatRetryingBusyTurn;`, sandbox);
  return { fn, calls };
}

const busy = () => respond(409, { error: 'turn_in_progress' });

(async () => {
  {
    const { fn, calls } = load([busy(), busy(), respond(200, { task_id: 't' })]);
    const res = await fn({ message: 'hi' }, () => false);
    assert.strictEqual(res.status, 200);
    assert.strictEqual(calls.length, 3);
    assert.strictEqual(calls[0].body, calls[2].body, 'the same body is re-sent');
  }
  {
    const { fn, calls } = load(Array.from({ length: 20 }, busy));
    const res = await fn({}, () => false);
    assert.strictEqual(res.status, 409, 'gives up and returns the 409 so the error shows');
    assert.strictEqual(calls.length, 7);
  }
  {
    const { fn, calls } = load([respond(409, { error: 'something_else' })]);
    assert.strictEqual((await fn({}, () => false)).status, 409);
    assert.strictEqual(calls.length, 1, 'only turn_in_progress is retried');
  }
  {
    const { fn, calls } = load([respond(500, {})]);
    assert.strictEqual((await fn({}, () => false)).status, 500);
    assert.strictEqual(calls.length, 1);
  }
  {
    const { fn, calls } = load([busy(), busy()]);
    assert.strictEqual((await fn({}, () => true)).status, 409);
    assert.strictEqual(calls.length, 1, 'a Stop ends the retrying');
  }
  assert(
    /_postChatRetryingBusyTurn\(_postBody,/.test(source),
    'doSend must post through the busy-turn retry',
  );
  console.log('turn_busy_retry: all assertions passed');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
