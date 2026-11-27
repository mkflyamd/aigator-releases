// The woken marker on a tab takes over its tooltip, and clearing it gives the old tooltip back.
// The real functions are cut out of tp-generic-agent-terminal.js and run against a fake tab.

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

const code = ['_genAgentDecorateWokenTab', '_genAgentClearWokenMark'].map(fn).join('\n');

class FakeElement {
  constructor(title) {
    this.title = title || '';
    this.dataset = {};
    this.children = [];
    this.removed = false;
  }
  setAttribute() {}
  removeAttribute(name) {
    if (name === 'title') this.title = '';
  }
  append(...kids) {
    this.children.push(...kids);
  }
  after(kid) {
    this.mark = kid;
  }
  remove() {
    this.removed = true;
  }
}

function world(tabTitle) {
  const label = new FakeElement();
  const tab = new FakeElement(tabTitle);
  tab.querySelector = (sel) => (sel === '.gtp-tab-label' ? label : null);
  tab.querySelectorAll = () => (label.mark && !label.mark.removed ? [label.mark] : []);
  const sess = { _wokenMark: 'Design head' };
  const ctx = {
    document: {
      createElement: () => new FakeElement(),
      querySelector: () => tab,
    },
    _genAgentTerminals: { k: { sessions: { 'pty-1': sess } } },
    _caSessionKey: () => 'k',
    _genAgentHeaderTabStripId: () => 'strip',
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return {
    tab,
    sess,
    mark: () => ctx._genAgentDecorateWokenTab(tab, sess),
    clear: () => ctx._genAgentClearWokenMark('t', 'pty-1'),
  };
}

// the tooltip says who woke the agent, then goes back to what it was
{
  const w = world('Fix the login bug');
  w.mark();
  assert.strictEqual(w.tab.title, 'Woken by Design head');
  w.clear();
  assert.strictEqual(w.tab.title, 'Fix the login bug');
  assert.strictEqual(w.tab.dataset.titleBeforeWoken, undefined);
}

// a second wake while the tab is still marked does not save the "Woken by" text as the old title
{
  const w = world('Fix the login bug');
  w.mark();
  w.sess._wokenMark = 'Memory leak';
  w.mark();
  assert.strictEqual(w.tab.title, 'Woken by Memory leak');
  w.clear();
  assert.strictEqual(w.tab.title, 'Fix the login bug');
}

// a tab that had no tooltip ends with none
{
  const w = world('');
  w.mark();
  w.clear();
  assert.strictEqual(w.tab.title, '');
}

console.log('woken tab title: ok');
