// Hovering or focusing a link in a chat reply adds a "Copy link" button after it; clicking
// the button writes the link URL to the clipboard and shows "Copied!" for a moment.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');

const block = source.match(
  /function _showChatLinkCopy\([\s\S]*?messages\.addEventListener\('click'[\s\S]*?\n\}\);/,
);
assert(block, 'chat link copy handlers not found in app.js');

function makeButton() {
  const btn = {
    className: '',
    dataset: {},
    attrs: {},
    textContent: '',
    classList: { contains: (c) => btn.className.split(/\s+/).includes(c) },
    setAttribute(name, value) {
      btn.attrs[name] = value;
    },
  };
  return btn;
}

function makeLink(href) {
  const link = {
    href,
    nextElementSibling: null,
    after(node) {
      link.nextElementSibling = node;
    },
  };
  return link;
}

function setup(writeText) {
  const listeners = {};
  const timers = [];
  const written = [];
  const context = {
    messages: {
      addEventListener(type, fn) {
        (listeners[type] ||= []).push(fn);
      },
    },
    document: { createElement: () => makeButton() },
    navigator: {
      clipboard: {
        writeText: (text) => {
          written.push(text);
          return writeText(text);
        },
      },
    },
    setTimeout: (fn, ms) => timers.push({ fn, ms }),
  };
  vm.runInNewContext(block[0], context);
  const fire = (type, target) => listeners[type].forEach((fn) => fn({ target }));
  return { fire, timers, written };
}

const hoverTarget = (link) => ({ closest: (sel) => (sel === '.prose a[href]' ? link : null) });

test('hovering a chat link adds exactly one copy button after it', () => {
  const { fire } = setup(() => Promise.resolve());
  const link = makeLink('https://example.com/a');
  fire('mouseover', hoverTarget(link));
  const btn = link.nextElementSibling;
  assert(btn, 'a button must follow the link');
  assert.strictEqual(btn.className, 'chat-link-copy');
  assert.strictEqual(btn.dataset.href, 'https://example.com/a');
  assert.strictEqual(btn.textContent, 'Copy link');
  assert.strictEqual(btn.attrs['aria-label'], 'Copy link');

  fire('mouseover', hoverTarget(link));
  fire('focusin', hoverTarget(link));
  assert.strictEqual(link.nextElementSibling, btn, 'a second hover must not add another button');
});

test('hovering something that is not a chat link adds nothing', () => {
  const { fire } = setup(() => Promise.resolve());
  assert.doesNotThrow(() => fire('mouseover', { closest: () => null }));
});

function clickTarget(btn) {
  return {
    closest: (sel) => {
      if (sel === '.chat-link-copy') return btn;
      throw new Error('the file-path branch must not run for a copy click: ' + sel);
    },
  };
}

test('clicking the copy button writes the link URL and shows Copied! for 1.5 s', async () => {
  const { fire, timers, written } = setup(() => Promise.resolve());
  const link = makeLink('https://example.com/a?b=1');
  fire('mouseover', hoverTarget(link));
  const btn = link.nextElementSibling;

  fire('click', clickTarget(btn));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepStrictEqual(written, ['https://example.com/a?b=1']);
  assert.strictEqual(btn.textContent, 'Copied!');
  assert.strictEqual(timers.length, 1);
  assert.strictEqual(timers[0].ms, 1500);

  timers[0].fn();
  assert.strictEqual(btn.textContent, 'Copy link');
});

test('a rejected clipboard write leaves the button reading Copy link', async () => {
  const { fire, timers } = setup(() => Promise.reject(new Error('denied')));
  const link = makeLink('https://example.com/a');
  fire('mouseover', hoverTarget(link));
  const btn = link.nextElementSibling;

  fire('click', clickTarget(btn));
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(btn.textContent, 'Copy link');
  assert.strictEqual(timers.length, 0);
});

function rule(selector) {
  const m = css.match(new RegExp('(^|\\n)' + selector.replace(/[.]/g, '\\.') + '\\s*\\{([^}]*)\\}'));
  assert(m, selector + ' rule exists');
  return m[2];
}

test('the copy button stays clickable while the pointer crosses from the link onto it', () => {
  assert(
    !/pointer-events:\s*none/.test(rule('.chat-link-copy')),
    'pointer-events: none makes the button unreachable once the pointer leaves the link',
  );
  const reveal = css.match(/\n([^{}]*\.chat-link-copy:hover[^{}]*)\{[^}]*opacity:\s*1/);
  assert(reveal, 'the button must stay visible while it is hovered');
});
