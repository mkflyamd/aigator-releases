// The ask_user card draws the model's options with textContent only, sends the clicked option or the
// typed reply as the next chat message, and tells the user when the question is in another tab.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const match = source.match(/\nfunction _showAskUserCard\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(match, '_showAskUserCard not found in app.js');

class El {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.removed = false;
    this.classList = { add() {} };
  }
  appendChild(c) {
    this.children.push(c);
    return c;
  }
  append(...cs) {
    cs.forEach((c) => this.children.push(c));
  }
  setAttribute() {}
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  remove() {
    this.removed = true;
  }
  scrollIntoView() {}
  all(pred, out = []) {
    this.children.forEach((c) => {
      if (pred(c)) out.push(c);
      c.all(pred, out);
    });
    return out;
  }
}

function run(data, { activeTab = 'tab-1', owner = 'tab-1' } = {}) {
  const messages = new El('div');
  const sent = [];
  const toasts = [];
  const updates = new Set();
  const context = {
    document: {
      createElement: (t) => new El(t),
      getElementById: (id) => (id === 'messages' ? messages : null),
      querySelectorAll: () => [],
      querySelector: () => null,
    },
    _activeTabId: activeTab,
    _tabsWithUpdates: updates,
    _showConnectivityToast: (m) => toasts.push(m),
    _sendSandboxFollowUp: (tab, text) => {
      sent.push([tab, text]);
      return Promise.resolve();
    },
    console,
  };
  vm.runInNewContext(match[0] + '\n_showAskUserCard(__data, __owner);', {
    ...context,
    __data: data,
    __owner: owner,
  });
  return { messages, sent, toasts, updates };
}

const data = {
  ask_id: 'a1',
  question: 'Which notebook?',
  options: [
    { label: '<img src=x onerror=alert(1)>', description: 'Recommended' },
    { label: 'Work Notes' },
  ],
};

let r = run(data);
const card = r.messages.children[0];
assert(card, 'card must be added to the chat');
const buttons = card.all((c) => c.tag === 'button' && c.className.includes('ask-user-option'));
assert.strictEqual(buttons.length, 2);
const labels = card.all((c) => c.className === 'ask-user-option-label').map((c) => c.textContent);
assert.strictEqual(labels[0], '<img src=x onerror=alert(1)>', 'label must be plain text');

const title = card.all((c) => c.className === 'gcc-title')[0];
assert.strictEqual(title.textContent, 'Which notebook?', 'the question is the card title, next to the options');
assert(card.all((c) => c.className === 'ask-user-hint').length === 1, 'options come with a pick-one hint');

buttons[1].listeners.click({ stopPropagation() {} });
assert.deepStrictEqual(r.sent, [['tab-1', 'Work Notes']]);
assert(card.removed, 'card must go away once answered');

r = run(data);
const field = r.messages.children[0].all((c) => c.tag === 'input')[0];
const send = r.messages.children[0].all((c) => c.tag === 'button' && c.textContent === 'Send')[0];
assert.strictEqual(field.placeholder, 'Chat about this…');
field.value = '   ';
send.listeners.click({ stopPropagation() {} });
assert.strictEqual(r.sent.length, 0, 'blank reply must not be sent');
field.value = 'use the Sales notebook';
field.listeners.keydown({ key: 'Enter', isComposing: false, preventDefault() {} });
assert.deepStrictEqual(r.sent, [['tab-1', 'use the Sales notebook']]);

r = run({ ask_id: 'a2', question: 'Name?', options: [] });
assert.strictEqual(
  r.messages.children[0].all((c) => c.className.includes('ask-user-option')).length,
  0,
  'a question with no options is a text box only',
);
assert.strictEqual(r.messages.children[0].all((c) => c.className === 'ask-user-hint').length, 0, 'no hint without options');

r = run(data, { activeTab: 'tab-1', owner: 'tab-2' });
assert.strictEqual(r.messages.children.length, 0, 'another tab must not get the card');
assert(r.updates.has('tab-2') && r.toasts.length === 1, 'the user is told in the other tab');

r = run({ question: 'no id', options: [] });
assert.strictEqual(r.messages.children.length, 0, 'a card without an id is ignored');

console.log('ask_user_card: ok');
