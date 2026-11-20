// Hovering or focusing a link in a chat reply adds a "Copy link" button after it; clicking
// the button writes the link URL to the clipboard and shows "Copied!" for a moment. The button
// is a fixed-position overlay placed from the link's last line box, so showing or hiding it
// never moves the surrounding text.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');

const block = source.match(
  /let _activeChatLinkCopy[\s\S]*?messages\.addEventListener\('click'[\s\S]*?\n\}\);/,
);
assert(block, 'chat link copy handlers not found in app.js');

function makeButton() {
  const btn = {
    className: '',
    dataset: {},
    attrs: {},
    textContent: '',
    style: {},
    offsetWidth: 70,
    offsetHeight: 20,
    classList: { contains: (c) => btn.className.split(/\s+/).includes(c) },
    setAttribute(name, value) {
      btn.attrs[name] = value;
    },
    remove() {
      if (btn.owner && btn.owner.nextElementSibling === btn) btn.owner.nextElementSibling = null;
    },
  };
  return btn;
}

const ONE_LINE = [{ left: 100, right: 300, top: 200, bottom: 216 }];

function makeLink(href, rects = ONE_LINE) {
  const link = {
    href,
    nextElementSibling: null,
    getClientRects: () => rects,
    after(node) {
      node.owner = link;
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
      getBoundingClientRect: () => ({ left: 0, right: 800, top: 0, bottom: 600 }),
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
  const m = css.match(
    new RegExp('(^|\\n)' + selector.replace(/[.]/g, '\\.') + '\\s*\\{([^}]*)\\}'),
  );
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

test('the button is placed above the last line of a wrapped link, right-aligned to it', () => {
  const { fire } = setup(() => Promise.resolve());
  const link = makeLink('https://example.com/a', [
    { left: 100, right: 300, top: 200, bottom: 216 },
    { left: 20, right: 150, top: 220, bottom: 236 },
  ]);
  fire('mouseover', hoverTarget(link));
  // 20px tall button overlapping the link by 2px so the pointer never crosses a gap
  assert.strictEqual(link.nextElementSibling.style.top, '202px');
  assert.strictEqual(link.nextElementSibling.style.left, '80px');
});

test('the button stays inside the message list horizontally and flips below at the top edge', () => {
  const { fire } = setup(() => Promise.resolve());
  const nearLeft = makeLink('https://example.com/a', [
    { left: 0, right: 30, top: 100, bottom: 116 },
  ]);
  fire('mouseover', hoverTarget(nearLeft));
  assert.strictEqual(nearLeft.nextElementSibling.style.left, '4px');

  const nearRight = makeLink('https://example.com/b', [
    { left: 700, right: 900, top: 100, bottom: 116 },
  ]);
  fire('mouseover', hoverTarget(nearRight));
  assert.strictEqual(nearRight.nextElementSibling.style.left, '726px');

  const atTop = makeLink('https://example.com/c', [{ left: 100, right: 300, top: 5, bottom: 21 }]);
  fire('focusin', hoverTarget(atTop));
  assert.strictEqual(atTop.nextElementSibling.style.top, '19px');
});

test('hovering again re-places the existing button instead of adding a second one', () => {
  const { fire } = setup(() => Promise.resolve());
  const rects = [{ left: 100, right: 300, top: 200, bottom: 216 }];
  const link = makeLink('https://example.com/a', rects);
  fire('mouseover', hoverTarget(link));
  const btn = link.nextElementSibling;
  rects[0] = { left: 100, right: 300, top: 300, bottom: 316 };
  fire('mouseover', hoverTarget(link));
  assert.strictEqual(link.nextElementSibling, btn);
  assert.strictEqual(btn.style.top, '282px');
});

test('scrolling removes the active button so it cannot float away from its link', () => {
  const { fire } = setup(() => Promise.resolve());
  const link = makeLink('https://example.com/a');
  fire('mouseover', hoverTarget(link));
  assert(link.nextElementSibling, 'button shown');
  fire('scroll', {});
  assert.strictEqual(link.nextElementSibling, null);
  fire('mouseover', hoverTarget(link));
  assert(link.nextElementSibling, 'hovering again brings the button back');
});

test('the copy button is out of the text flow, so showing or hiding it moves nothing', () => {
  const body = rule('.chat-link-copy');
  assert(/position:\s*fixed/.test(body), 'an in-flow button shifts the text after the link');
  assert(!/margin(-left)?:/.test(body), 'margins on the button push text around');
  assert(/visibility:\s*hidden/.test(body), 'a hidden button must not keep a hit area');
  const reveal = css.match(/\n([^{}]*\.chat-link-copy:hover[^{}]*)\{([^}]*)\}/);
  assert(/visibility:\s*visible/.test(reveal[2]), 'the reveal rule must make the button visible');
});
