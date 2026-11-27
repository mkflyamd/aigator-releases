const assert = require('assert');
const fs = require('fs');
const path = require('path');
const test = require('node:test');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const start = source.indexOf('function addGoogleAccountRow');
const end = source.indexOf('async function _refreshGoogleWsCredentials');
assert(start !== -1 && end > start, 'Google account row helpers not found in app.js');
const helpers = source.slice(start, end);

class El {
  constructor(tag) {
    this.tag = tag;
    this.className = '';
    this.value = '';
    this.textContent = '';
    this.children = [];
    this.parent = null;
    this.attrs = {};
    this.listeners = {};
  }
  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }
  replaceChildren() {
    this.children = [];
  }
  remove() {
    this.parent.children = this.parent.children.filter((c) => c !== this);
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  click() {
    this.listeners.click();
  }
  querySelectorAll(tag) {
    const out = [];
    for (const c of this.children) {
      if (c.tag === tag) out.push(c);
      out.push(...c.querySelectorAll(tag));
    }
    return out;
  }
}

function load() {
  const list = new El('div');
  const context = {
    document: {
      querySelector: (sel) => (sel === '#google-ws-accounts .site-list' ? list : null),
      createElement: (tag) => new El(tag),
    },
  };
  vm.createContext(context);
  vm.runInContext(
    helpers + '; this.api = { addGoogleAccountRow, setGoogleAccounts, googleAccountValues };',
    context,
  );
  return { api: context.api, list };
}

const tags = (row) => row.children.filter((c) => c.tag === 'span').map((c) => c.textContent);
const removeButtons = (row) => row.children.filter((c) => c.tag === 'button');

test('first row is the default account without a remove button', () => {
  const { api, list } = load();
  api.addGoogleAccountRow('me@example.test');
  assert.deepStrictEqual(tags(list.children[0]), ['Default']);
  assert.strictEqual(removeButtons(list.children[0]).length, 0);
});

test('later rows can be removed', () => {
  const { api, list } = load();
  api.addGoogleAccountRow('me@example.test');
  api.addGoogleAccountRow('work@example.test');
  assert.strictEqual(removeButtons(list.children[1]).length, 1);
  removeButtons(list.children[1])[0].click();
  assert.strictEqual(list.children.length, 1);
});

test('googleAccountValues trims and drops empty rows', () => {
  const { api } = load();
  api.addGoogleAccountRow('  me@example.test  ');
  api.addGoogleAccountRow('');
  api.addGoogleAccountRow('work@example.test');
  assert.deepStrictEqual(Array.from(api.googleAccountValues()), [
    'me@example.test',
    'work@example.test',
  ]);
});

test('setGoogleAccounts with no accounts leaves one empty default row', () => {
  const { api, list } = load();
  api.setGoogleAccounts([]);
  assert.strictEqual(list.children.length, 1);
  assert.deepStrictEqual(tags(list.children[0]), ['Default']);
  assert.deepStrictEqual(Array.from(api.googleAccountValues()), []);
});

test('setGoogleAccounts shows signed-in status per account', () => {
  const { api, list } = load();
  api.setGoogleAccounts([
    { email: 'me@example.test', signed_in: true },
    { email: 'work@example.test', signed_in: false },
  ]);
  assert.deepStrictEqual(tags(list.children[0]), ['Signed in', 'Default']);
  assert.deepStrictEqual(tags(list.children[1]), ['Not signed in']);
});
