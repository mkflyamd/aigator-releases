'use strict';

// Terminal "switch to left" (vertical) layout vs. the other things that want
// the same row:
//  - an open third pane / browser pane: the vertical terminal claims the slot,
//    so the panes must actually be closed (the old code clicked a nonexistent
//    #tp-detail-close, then the conflict watcher flipped the terminal back to
//    horizontal, making the button a no-op).
//  - a tiled native app (body.gator-split / gator-squeezed): the Gator viewport
//    can be as narrow as 400px, so the 420px vertical terminal pushes chat and
//    the dock out of view. Vertical must never persist in that state.
//
// jsdom is not available in this repo, so a small DOM shim is used.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'terminal.js'), 'utf8');

function makeEnv({
  saved = null,
  bodyClasses = [],
  thirdPaneOpen = false,
  browserPaneOpen = false,
}) {
  const registry = {};
  const observers = [];
  const store = {};
  if (saved) store['gator.terminal.layout'] = saved;

  class FakeEl {
    constructor(tag) {
      this.tag = tag;
      this._cls = [];
      this._id = '';
      this.children = [];
      this.parentNode = null;
      this.dataset = {};
      this.style = { setProperty() {}, removeProperty() {} };
      this.offsetWidth = 100;
      this.listeners = {};
      this.classList = {
        add: (...c) => c.forEach((x) => this._cls.includes(x) || this._cls.push(x)),
        remove: (...c) => (this._cls = this._cls.filter((x) => !c.includes(x))),
        contains: (c) => this._cls.includes(c),
        toggle: (c, on) => {
          const want = on === undefined ? !this._cls.includes(c) : !!on;
          if (want) this.classList.add(c);
          else this.classList.remove(c);
          return want;
        },
      };
    }
    get className() {
      return this._cls.join(' ');
    }
    set className(v) {
      this._cls = String(v).split(/\s+/).filter(Boolean);
    }
    get id() {
      return this._id;
    }
    set id(v) {
      this._id = v;
      registry[v] = this;
    }
    set innerHTML(_v) {
      this.children = [];
    }
    get previousSibling() {
      const s = this.parentNode ? this.parentNode.children : [];
      return s[s.indexOf(this) - 1] || null;
    }
    get nextSibling() {
      const s = this.parentNode ? this.parentNode.children : [];
      return s[s.indexOf(this) + 1] || null;
    }
    get firstChild() {
      return this.children[0] || null;
    }
    appendChild(c) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      this.children.push(c);
      return c;
    }
    insertBefore(c, ref) {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = this;
      const i = ref ? this.children.indexOf(ref) : -1;
      if (i < 0) this.children.push(c);
      else this.children.splice(i, 0, c);
      return c;
    }
    removeChild(c) {
      this.children = this.children.filter((x) => x !== c);
      c.parentNode = null;
      return c;
    }
    querySelector(sel) {
      const cls = sel.slice(1);
      const walk = (el) => {
        for (const c of el.children) {
          if (c._cls.includes(cls)) return c;
          const r = walk(c);
          if (r) return r;
        }
        return null;
      };
      return walk(this);
    }
    addEventListener(t, fn) {
      (this.listeners[t] = this.listeners[t] || []).push(fn);
    }
    removeEventListener() {}
    click() {
      (this.listeners.click || []).forEach((fn) => fn({ target: this, stopPropagation() {} }));
    }
    getBoundingClientRect() {
      return { width: 0, height: 280 };
    }
    getAttribute() {
      return null;
    }
  }

  const make = (id, classes, parent) => {
    const el = new FakeEl('div');
    el.className = classes;
    if (id) el.id = id;
    if (parent) parent.appendChild(el);
    return el;
  };

  const body = new FakeEl('body');
  bodyClasses.forEach((c) => body.classList.add(c));
  const layout = make(null, 'layout', body);
  make(null, 'main', layout);
  make(null, 'dock', layout);
  const thirdPane = make(
    'third-pane',
    'third-pane ' + (thirdPaneOpen ? 'is-open' : 'hidden'),
    layout,
  );
  thirdPane.offsetWidth = thirdPaneOpen ? 530 : 0;
  const browserPane = make(
    'browser-pane',
    'browser-pane ' + (browserPaneOpen ? '' : 'hidden'),
    layout,
  );
  browserPane.offsetWidth = browserPaneOpen ? 400 : 0;
  // app.js wires #bp-close-btn to _closeBrowserPane, which hides the pane.
  const bpClose = make('bp-close-btn', 'bp-btn', browserPane);
  bpClose.addEventListener('click', () => {
    browserPane.classList.add('hidden');
    browserPane.offsetWidth = 0;
  });

  const closeThirdPaneCalls = [];
  const context = {
    console,
    addEventListener() {},
    setTimeout: () => 0,
    getComputedStyle: () => ({ display: 'block' }),
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
    location: { protocol: 'http:', host: 'localhost' },
    Terminal: class {
      loadAddon() {}
      open() {}
      attachCustomKeyEventHandler() {}
      onData() {}
      focus() {}
    },
    FitAddon: {
      FitAddon: class {
        fit() {}
      },
    },
    WebSocket: class {
      static get OPEN() {
        return 1;
      }
    },
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
    MutationObserver: class {
      constructor(cb) {
        this.cb = cb;
        this.targets = [];
        observers.push(this);
      }
      observe(t) {
        this.targets.push(t);
      }
    },
    // Mirrors the observable effect of the real closeThirdPane() in third-pane.js.
    closeThirdPane() {
      closeThirdPaneCalls.push(1);
      thirdPane.classList.remove('is-open');
      thirdPane.classList.add('hidden');
      thirdPane.offsetWidth = 0;
    },
  };
  context.document = {
    body,
    documentElement: new FakeEl('html'),
    createElement: (t) => new FakeEl(t),
    getElementById: (id) => registry[id] || null,
    querySelector: (sel) => (sel === '.layout' ? layout : null),
    addEventListener() {},
  };
  context.window = context;
  vm.runInNewContext(source, context);

  return {
    GatorTerminal: context.window.GatorTerminal,
    body,
    thirdPane,
    browserPane,
    closeThirdPaneCalls,
    store,
    panel: () => registry['gator-terminal-panel'],
    // Simulate a DOM mutation on `el` by firing the observers watching it.
    mutate: (el) => observers.filter((o) => o.targets.includes(el)).forEach((o) => o.cb([])),
  };
}

const isVertical = (env) => env.panel().classList.contains('vertical');
const isHorizontal = (env) => env.panel().classList.contains('horizontal');

// (a) Switching to vertical while a third pane is open closes the pane, and the
// conflict watcher does not flip the terminal back.
{
  const env = makeEnv({ thirdPaneOpen: true });
  env.GatorTerminal.open();
  assert(isHorizontal(env), 'precondition: terminal opens horizontal');

  env.GatorTerminal.setLayout('vertical');
  env.mutate(env.thirdPane);

  assert.strictEqual(
    env.closeThirdPaneCalls.length,
    1,
    'third pane must be closed via closeThirdPane',
  );
  assert(env.thirdPane.classList.contains('hidden'), 'third pane is closed');
  assert(isVertical(env), 'terminal stays vertical after the third pane closes');
  assert.strictEqual(env.store['gator.terminal.layout'], 'vertical');
}

// (a2) Same for the browser pane.
{
  const env = makeEnv({ browserPaneOpen: true });
  env.GatorTerminal.open();
  env.GatorTerminal.setLayout('vertical');
  env.mutate(env.browserPane);

  assert(env.browserPane.classList.contains('hidden'), 'browser pane is closed');
  assert(isVertical(env), 'terminal stays vertical after the browser pane closes');
}

// (b) With a native app tiled, vertical is never displayed, but the user's
// explicit choice is still what is stored.
for (const cls of ['gator-split', 'gator-squeezed']) {
  const env = makeEnv({ bodyClasses: [cls] });
  env.GatorTerminal.open();
  env.GatorTerminal.setLayout('vertical');

  assert(isHorizontal(env), `setLayout('vertical') falls back to horizontal under ${cls}`);
  assert(!isVertical(env), `terminal is not vertical under ${cls}`);
  assert.strictEqual(
    env.store['gator.terminal.layout'],
    'vertical',
    `explicit vertical choice stays stored under ${cls}`,
  );
}

// (b2) A saved vertical preference is not displayed while a native app is
// tiled, and opening the terminal does not overwrite it.
{
  const env = makeEnv({ saved: 'vertical', bodyClasses: ['gator-split'] });
  env.GatorTerminal.open();

  assert(isHorizontal(env), 'open() with saved vertical + gator-split starts horizontal');
  assert.strictEqual(
    env.store['gator.terminal.layout'],
    'vertical',
    'open() under gator-split must not overwrite the saved vertical preference',
  );

  env.body.classList.remove('gator-split');
  env.mutate(env.body);
  assert(isVertical(env), 'terminal returns to the saved vertical once gator-split clears');
}

// (c) Terminal already vertical when a native app gets tiled afterwards: the
// terminal flips to horizontal for display only, keeps the stored preference,
// and goes back to vertical when the native tile goes away.
{
  const env = makeEnv({ saved: 'vertical' });
  env.GatorTerminal.open();
  assert(isVertical(env), 'precondition: terminal is vertical');

  env.body.classList.add('gator-split');
  env.mutate(env.body);

  assert(isHorizontal(env), 'terminal flips to horizontal once gator-split appears');
  assert.strictEqual(
    env.store['gator.terminal.layout'],
    'vertical',
    'automatic fallback must not overwrite the stored vertical preference',
  );

  env.body.classList.remove('gator-split');
  env.mutate(env.body);
  assert(isVertical(env), 'terminal returns to vertical after the native tile goes away');
  assert.strictEqual(env.store['gator.terminal.layout'], 'vertical');
}

// (c2) An explicit horizontal choice made under gator-split is the new
// preference and is not reverted when the tile goes away.
{
  const env = makeEnv({ saved: 'vertical', bodyClasses: ['gator-split'] });
  env.GatorTerminal.open();
  env.GatorTerminal.setLayout('horizontal');
  assert.strictEqual(env.store['gator.terminal.layout'], 'horizontal');

  env.body.classList.remove('gator-split');
  env.mutate(env.body);
  assert(isHorizontal(env), 'explicit horizontal stays horizontal after gator-split clears');
}

// A third pane opening while the terminal is vertical still flips it (existing
// behaviour) for display only, and the terminal returns to vertical when the
// pane closes.
{
  const env = makeEnv({ saved: 'vertical' });
  env.GatorTerminal.open();
  env.thirdPane.classList.remove('hidden');
  env.thirdPane.classList.add('is-open');
  env.thirdPane.offsetWidth = 530;
  env.mutate(env.thirdPane);

  assert(isHorizontal(env), 'terminal flips to horizontal when a pane opens beside it');
  assert.strictEqual(env.store['gator.terminal.layout'], 'vertical');

  env.thirdPane.classList.remove('is-open');
  env.thirdPane.classList.add('hidden');
  env.thirdPane.offsetWidth = 0;
  env.mutate(env.thirdPane);
  assert(isVertical(env), 'terminal returns to vertical once the pane closes');
}

console.log('terminal_layout_conflicts: all tests passed');
