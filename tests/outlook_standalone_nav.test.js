// The calendar compose deeplink has no OWA left rail: the shell adds Mail and
// Calendar links there, and removes them once the user is back in the full app.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
const m = source.match(/const _OUTLOOK_STANDALONE_NAV_SCRIPT = `([\s\S]*?)`;\r?\n/);
assert(m, 'standalone nav script found in shell/main.js');
assert(
  /_syncOutlookStandaloneNav\(outlookView\.webContents\)/.test(source),
  'script is wired to the Outlook view',
);

assert(
  /outlookView\.webContents\.on\('will-prevent-unload'[\s\S]*?Leave[\s\S]*?Stay[\s\S]*?e\.preventDefault\(\)/.test(
    source,
  ),
  'leaving a page with unsaved changes asks Leave/Stay instead of silently cancelling',
);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.style = {};
    this.listeners = {};
  }
  appendChild(c) {
    this.children.push(c);
    c.parent = this;
  }
  addEventListener(t, fn) {
    this.listeners[t] = fn;
  }
  remove() {
    this.removed = true;
    this.parent.children = this.parent.children.filter((c) => c !== this);
  }
}

const nav = [];
function run(pathname, body) {
  const document = {
    body,
    createElement: (t) => new FakeEl(t),
    getElementById: (id) => body.children.find((c) => c.id === id) || null,
  };
  vm.runInNewContext(m[1], { document, location: { pathname, assign: (u) => nav.push(u) } });
}

const body = new FakeEl('body');
run('/calendar/0/deeplink/compose', body);
assert.strictEqual(body.children.length, 1, 'bar added on the compose deeplink');
const bar = body.children[0];
assert.deepStrictEqual(
  bar.children.map((b) => b.textContent),
  ['Mail', 'Calendar'],
);

run('/calendar/0/deeplink/compose', body);
assert.strictEqual(body.children.length, 1, 'bar is not added twice');

bar.children[1].listeners.click();
bar.children[0].listeners.click();
assert.deepStrictEqual(nav, ['/calendar/', '/mail/'], 'buttons navigate within OWA');

run('/mail/', body);
assert.strictEqual(body.children.length, 0, 'bar removed outside the compose page');

const other = new FakeEl('body');
run('/mail/', other);
assert.strictEqual(other.children.length, 0, 'no bar on regular Outlook pages');

console.log('outlook_standalone_nav ok');
