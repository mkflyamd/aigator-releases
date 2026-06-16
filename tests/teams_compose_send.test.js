const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'third-pane.js'),
  'utf8',
);

function makeElement() {
  const el = {
    className: '',
    innerHTML: '',
    style: { setProperty() {} },
    classList: { add() {}, remove() {}, contains() { return false; } },
    appendChild() {},
    addEventListener() {},
    removeEventListener() {},
    remove() {},
    querySelector() { return el; },
    querySelectorAll() { return []; },
  };
  return el;
}

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  document: {
    addEventListener() {},
    removeEventListener() {},
    getElementById() { return makeElement(); },
    body: makeElement(),
    documentElement: makeElement(),
    createElement: makeElement,
  },
  window: { addEventListener() {}, innerWidth: 1200 },
  localStorage: { getItem() { return null; }, setItem() {} },
  location: { search: '' },
  URLSearchParams,
  AbortController,
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

assert.strictEqual(
  typeof sandbox._teamsComposePickChatIdForSend,
  'function',
  'chat id picker helper should exist',
);
assert.strictEqual(
  sandbox._teamsComposePickChatIdForSend('known-chat-id', ['a@example.com']),
  'known-chat-id',
  'known chat id should be used before falling back to client-side resolution',
);
assert.strictEqual(
  sandbox._teamsComposePeopleSearchQuery('@vikram'),
  'vikram',
  'compose people search should ignore @ prefixes',
);
assert.strictEqual(
  sandbox._teamsComposePeopleSearchQuery(' Akash.Verma '),
  'Akash Verma',
  'compose people search should handle dotted display names',
);

assert.strictEqual(
  typeof sandbox._teamsFetchWithTimeout,
  'function',
  'timeout fetch helper should exist',
);

(async () => {
  const originalFetch = sandbox.fetch;
  sandbox.fetch = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });

  await assert.rejects(
    sandbox._teamsFetchWithTimeout('/slow-send', {}, 1),
    /Timed out waiting for Teams send confirmation/,
    'timed out sends should reject with an unknown-status message',
  );

  sandbox.fetch = originalFetch;
})().catch(err => {
  console.error(err);
  process.exit(1);
});
