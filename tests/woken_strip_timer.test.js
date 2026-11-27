// The "Woken by" status line dismisses itself after 8 seconds on screen, waits while the user
// hovers or focuses it, and is remembered as seen. The real functions are cut out of
// tp-generic-agent-terminal.js and run against a fake page with controllable timers.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'tp-generic-agent-terminal.js'),
  'utf8',
);

function fn(name) {
  const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`));
  assert(match, `${name} not found`);
  return match[0];
}

function constant(name) {
  const match = source.match(new RegExp(`const ${name} = (\\d+);`));
  assert(match, `${name} not found`);
  return match[0];
}

const code = [
  constant('GEN_AGENT_WOKEN_MS'),
  constant('GEN_AGENT_WOKEN_FADE_MS'),
  ...[
    '_genAgentShowWokenBanner',
    '_genAgentWokenSeenKey',
    '_genAgentWokenSeenAt',
    '_genAgentWokenMarkSeen',
    '_genAgentWokenRenderText',
    '_genAgentWokenArm',
    '_genAgentWokenDrop',
    '_genAgentWokenDismiss',
  ].map(fn),
].join('\n');

class FakeElement {
  constructor() {
    this.className = '';
    this.children = [];
    this.listeners = {};
    this.attributes = {};
    this.classes = new Set();
    this.removed = false;
    this.hovered = false;
    this.classList = {
      add: (...names) => names.forEach((n) => this.classes.add(n)),
      remove: (...names) => names.forEach((n) => this.classes.delete(n)),
    };
  }
  setAttribute(k, v) {
    this.attributes[k] = v;
  }
  append(...kids) {
    this.children.push(...kids);
  }
  appendChild(kid) {
    this.children.push(kid);
  }
  replaceChildren(...kids) {
    this.children = kids;
  }
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }
  matches(selector) {
    return selector === ':hover' ? this.hovered : false;
  }
  remove() {
    this.removed = true;
  }
  fire(type) {
    this.listeners[type]();
  }
}

function world({ reducedMotion = false } = {}) {
  const timers = [];
  const storage = new Map();
  let io = null;
  const ctx = {
    document: { createElement: () => new FakeElement() },
    window: { matchMedia: () => ({ matches: reducedMotion }) },
    sessionStorage: {
      getItem: (k) => storage.get(k) ?? null,
      setItem: (k, v) => storage.set(k, v),
    },
    IntersectionObserver: class {
      constructor(callback) {
        this.callback = callback;
        io = this;
      }
      observe() {}
      disconnect() {}
    },
    setTimeout: (callback, ms) => {
      const timer = { callback, ms, live: true };
      timers.push(timer);
      return timer;
    },
    clearTimeout: (timer) => {
      if (timer) timer.live = false;
    },
    _ocFit: () => {},
    _genAgentSetWokenMark: () => {},
    Date,
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  const sess = { container: new FakeElement(), ptySessionId: 'pty-1' };
  return {
    ctx,
    sess,
    storage,
    live: () => timers.filter((t) => t.live),
    onScreen: (visible) => io.callback([{ isIntersecting: visible }]),
    show: (msg) => ctx._genAgentShowWokenBanner(sess, msg),
  };
}

// the timer starts only once the strip is on screen, and it is exactly 8 seconds
{
  const w = world();
  w.show({ by: 'Design head', at: 1000 });
  assert.strictEqual(w.live().length, 0, 'a strip on a background tab does not start counting');
  w.onScreen(true);
  assert.strictEqual(w.live().length, 1);
  assert.strictEqual(w.live()[0].ms, 8000, 'the dismiss timer is 8 seconds');
  assert(w.sess._woken, 'still showing before the timer fires');
}

// when the timer fires the strip fades, then is removed, and the wake is remembered as seen
{
  const w = world();
  w.show({ by: 'Design head', at: 1000 });
  const strip = w.sess._woken.el;
  w.onScreen(true);
  w.live()[0].callback();
  assert.strictEqual(w.sess._woken, null);
  assert(w.sess.container.classes.has('gtp-term--woken-leaving'), 'it fades before it goes');
  assert.strictEqual(w.storage.get('gtp-woken-seen:pty-1'), '1000');
  const fade = w.live()[0];
  assert.strictEqual(fade.ms, 300);
  fade.callback();
  assert(strip.removed);
  assert(!w.sess.container.classes.has('gtp-term--woken'));
}

// reduced motion skips the fade
{
  const w = world({ reducedMotion: true });
  w.show({ by: 'Design head', at: 1000 });
  const strip = w.sess._woken.el;
  w.onScreen(true);
  w.live()[0].callback();
  assert(strip.removed, 'removed straight away');
  assert.strictEqual(w.live().length, 0);
}

// hovering holds the strip; leaving starts the full 8 seconds again
{
  const w = world();
  w.show({ by: 'Design head', at: 1000 });
  const strip = w.sess._woken.el;
  w.onScreen(true);
  strip.fire('mouseenter');
  assert.strictEqual(w.live().length, 0, 'no countdown while the mouse is on it');
  strip.fire('mouseleave');
  assert.strictEqual(w.live().length, 1);
  assert.strictEqual(w.live()[0].ms, 8000);
}

// leaving the tab stops the count; coming back starts it again
{
  const w = world();
  w.show({ by: 'Design head', at: 1000 });
  w.onScreen(true);
  w.onScreen(false);
  assert.strictEqual(w.live().length, 0);
  w.onScreen(true);
  assert.strictEqual(w.live().length, 1);
}

// a second message from the same agent counts up and restarts the 8 seconds
{
  const w = world();
  w.show({ by: 'Design head', at: 1000 });
  w.onScreen(true);
  w.show({ by: 'Design head', at: 2000 });
  assert.strictEqual(w.sess._woken.count, 2);
  assert.strictEqual(w.live().length, 1, 'one timer, restarted');
  assert.strictEqual(w.live()[0].ms, 8000);
}

// a wake the user already had on screen is not shown again after a reload
{
  const w = world();
  w.storage.set('gtp-woken-seen:pty-1', '1000');
  w.show({ by: 'Design head', at: 1000 });
  assert.strictEqual(w.sess._woken, undefined);
  assert.strictEqual(w.live().length, 0);
}

console.log('woken strip timer: ok');
