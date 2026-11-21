// A slow backend must not stack background polls, or the hung requests use up the browser's
// per-host connections and the chat stream cannot connect. The real _pollOnce is cut out of app.js.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start > 0, `${name} found`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`${name} not closed`);
}

const pollOnce = vm.runInNewContext(`(${functionSource('_pollOnce')})`);

(async () => {
  let calls = 0;
  let release;
  const poll = pollOnce(
    () =>
      new Promise((resolve) => {
        calls++;
        release = resolve;
      }),
  );

  const first = poll();
  await poll();
  await poll();
  assert.strictEqual(calls, 1, 'a poll that is still running is not started again');

  release();
  await first;
  const next = poll();
  assert.strictEqual(calls, 2, 'a finished poll can run again');
  release();
  await next;

  let failing = 0;
  const throwing = pollOnce(async () => {
    failing++;
    throw new Error('boom');
  });
  await throwing().catch(() => {});
  await throwing().catch(() => {});
  assert.strictEqual(failing, 2, 'a poll that threw does not block later polls');

  for (const url of ['/api/teams/chats?delta=true', '/api/email/inbox?top=10&delta=true']) {
    const at = source.indexOf(`fetch('${url}'`);
    assert(at > 0, `${url} poll found`);
    assert(
      source.slice(at, at + 160).includes('AbortSignal.timeout('),
      `${url} poll has a client timeout`,
    );
    const before = source.lastIndexOf('setInterval(', at);
    assert(source.slice(before, at).includes('_pollOnce('), `${url} poll is wrapped in _pollOnce`);
  }

  console.log('background poll no-pileup: ok');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
