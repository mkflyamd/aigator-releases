// The reply-draft card: real To/CC chips the user can add to or remove from before approving.
// Runs the real _buildReplyRecipientRows against a small DOM shim (jsdom is not in this repo).

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.listeners = {};
    this.attrs = {};
    this.classes = new Set();
    this.value = '';
    this.title = '';
    this._text = '';
    const el = this;
    this.classList = {
      add: (...c) => c.forEach((x) => el.classes.add(x)),
      remove: (...c) => c.forEach((x) => el.classes.delete(x)),
      toggle: (c, force) => {
        const on = force === undefined ? !el.classes.has(c) : force;
        on ? el.classes.add(c) : el.classes.delete(c);
        return on;
      },
      contains: (c) => el.classes.has(c),
    };
  }
  set className(v) {
    this.classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  get className() {
    return [...this.classes].join(' ');
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  get childElementCount() {
    return this.children.length;
  }
  append(...kids) {
    this.children.push(...kids);
  }
  appendChild(kid) {
    this.children.push(kid);
    return kid;
  }
  replaceChildren(...kids) {
    this.children = [...kids];
    this._text = '';
  }
  setAttribute(k, v) {
    this.attrs[k] = v;
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  focus() {}
  fire(type, event = {}) {
    (this.listeners[type] || []).forEach((fn) => fn({ preventDefault() {}, ...event }));
  }
  click() {
    this.fire('click');
  }
  find(pred, out = []) {
    this.children.forEach((c) => {
      if (pred(c)) out.push(c);
      c.find(pred, out);
    });
    return out;
  }
  querySelector(sel) {
    assert.strictEqual(sel, 'button');
    return this.find((c) => c.tag === 'button')[0] || null;
  }
}

function setup({ people = [] } = {}) {
  const toasts = [];
  const timers = [];
  const fetched = [];
  const consts = source.match(/const _REPLY_RECIPIENT_MAX[^\n]*\nconst _REPLY_EMAIL_RE[^\n]*\n/);
  const fn = source.match(/function _buildReplyRecipientRows\(data\) \{[\s\S]*?\n\}/);
  assert(consts && fn, 'recipient editor found in app.js');
  const build = vm.runInNewContext(consts[0] + fn[0] + '; _buildReplyRecipientRows;', {
    document: { createElement: (tag) => new FakeEl(tag) },
    fetch: async (url) => {
      fetched.push(url);
      return { ok: true, json: async () => ({ people }) };
    },
    setTimeout: (f) => timers.push(f),
    clearTimeout: () => {},
    _showConnectivityToast: (msg, kind) => toasts.push([msg, kind]),
  });
  return { build, toasts, timers, fetched };
}

const person = (email) => ({ name: email.split('@')[0], email });
const chipNames = (row) => row.find((c) => c.classes.has('ag-chip-name')).map((c) => c.textContent);
const removeButtons = (row) => row.find((c) => c.classes.has('ag-chip-remove'));
const addInput = (row) => row.find((c) => c.classes.has('ag-add-input'))[0];
const addLink = (row) => row.find((c) => c.classes.has('gcc-recipient-add'))[0];
const enter = (row, text) => {
  addLink(row).click();
  const input = addInput(row);
  input.value = text;
  input.fire('keydown', { key: 'Enter' });
};
const json = (v) => JSON.stringify(v);

// Every To and CC person is shown, and nothing is reported until the user changes something.
{
  const { build } = setup();
  const ed = build({
    to_people: [person('ann@amd.com'), person('bob@amd.com')],
    cc_people: [person('cy@amd.com')],
  });
  const [to, cc] = ed.rows;
  assert.strictEqual(ed.rows.length, 2, 'To and CC rows only, no Bcc');
  assert.strictEqual(json(chipNames(to)), json(['ann', 'bob']));
  assert.strictEqual(json(chipNames(cc)), json(['cy']));
  assert.strictEqual(ed.edits(), null, 'untouched card sends no recipient edits');
}

// Removing a person reports only the line that changed.
{
  const { build } = setup();
  const ed = build({
    to_people: [person('ann@amd.com'), person('bob@amd.com')],
    cc_people: [person('cy@amd.com')],
  });
  const [to, cc] = ed.rows;
  removeButtons(cc)[0].click();
  assert.strictEqual(json(ed.edits()), json({ cc: [] }));
  removeButtons(to)[1].click();
  assert.strictEqual(json(ed.edits()), json({ to: ['ann@amd.com'], cc: [] }));
  assert.strictEqual(removeButtons(to).length, 0, 'the last To person cannot be removed');
}

// A typed email address is added on Enter; repeats and junk are ignored.
{
  const { build } = setup();
  const ed = build({ to_people: [person('ann@amd.com')], cc_people: [person('cy@amd.com')] });
  const [to, cc] = ed.rows;
  enter(cc, 'new@amd.com');
  assert.strictEqual(json(ed.edits()), json({ cc: ['cy@amd.com', 'new@amd.com'] }));
  enter(to, 'NEW@amd.com');
  enter(to, 'ann@amd.com');
  enter(to, 'not-an-address');
  assert.strictEqual(json(chipNames(to)), json(['ann']), 'duplicates and junk are not added');
  assert.strictEqual(json(chipNames(cc)), json(['cy', 'new@amd.com']));
}

// Removing and re-adding the same person leaves nothing to report.
{
  const { build } = setup();
  const ed = build({ to_people: [person('ann@amd.com')], cc_people: [person('cy@amd.com')] });
  const [, cc] = ed.rows;
  removeButtons(cc)[0].click();
  enter(cc, 'cy@amd.com');
  assert.strictEqual(ed.edits(), null);
}

// An empty CC line collapses to a single "+ Add CC" link instead of a blank row.
{
  const { build } = setup();
  const ed = build({ to_people: [person('ann@amd.com')], cc_people: [] });
  const [to, cc] = ed.rows;
  assert(cc.classes.has('gcc-recipient-empty'));
  assert.strictEqual(addLink(cc).textContent, '+ Add CC');
  assert(!to.classes.has('gcc-recipient-empty'));
  enter(cc, 'new@amd.com');
  assert(!cc.classes.has('gcc-recipient-empty'));
  assert.strictEqual(addLink(cc).textContent, '+ Add');
  removeButtons(cc)[0].click();
  assert(cc.classes.has('gcc-recipient-empty'), 'removing the last CC person collapses the row');
}

// Typing a name searches people; picking a suggestion adds that person.
(async () => {
  const { build, timers, fetched } = setup({
    people: [
      { name: 'Dee Lee', email: 'dee@amd.com' },
      { name: 'Ann', email: 'ann@amd.com' },
    ],
  });
  const ed = build({ to_people: [person('ann@amd.com')], cc_people: [] });
  const [to] = ed.rows;
  addLink(to).click();
  const input = addInput(to);
  input.value = 'd';
  input.fire('input');
  assert.strictEqual(timers.length, 0, 'one letter does not search');
  input.value = 'dee';
  input.fire('input');
  await timers[0]();
  assert(/\/api\/people\/search\?q=dee/.test(fetched[0]), fetched[0]);
  const suggestions = to.find((c) => c.classes.has('ag-suggestion'));
  assert.strictEqual(suggestions.length, 1, 'people already on the reply are not suggested');
  suggestions[0].click();
  assert.strictEqual(json(ed.edits()), json({ to: ['ann@amd.com', 'dee@amd.com'] }));

  // Once sent or handed to Outlook, the editor locks; a failed send unlocks it.
  ed.lock();
  assert(ed.rows.every((r) => r.classList.contains('gcc-recipients-locked')));
  ed.lock(false);
  assert(ed.rows.every((r) => !r.classList.contains('gcc-recipients-locked')));

  // The recipient cap matches the server's.
  const cap = setup();
  const many = Array.from({ length: 50 }, (_, i) => person(`p${i}@amd.com`));
  const full = cap.build({ to_people: many, cc_people: [] });
  enter(full.rows[1], 'extra@amd.com');
  assert.strictEqual(cap.toasts.length, 1, 'a 51st recipient is refused with a message');
  assert.strictEqual(full.rows[1].find((c) => c.classes.has('ag-chip-name')).length, 0);

  // The card uses the editor for replies and new emails, and sends only what changed, on both paths.
  assert(
    /\(type === 'email-reply' \|\| type === 'email-send'\) &&\s*Array\.isArray\(data\.to_people\)/.test(
      source,
    ),
  );
  assert(
    /\.\.\.headerEdits\(\),\s*\}\);\s*let res = await fetch\('\/api\/drafts\/' \+ draftId \+ '\/approve'/.test(
      source,
    ),
  );
  assert(/\{ \.\.\.bodyEdit, \.\.\.headerEdit \}/.test(source), 'open-in-outlook sends edits');

  // A new email's subject is a text box whose edit rides along; the data-flow line needs a source.
  assert(
    /type === 'email-send'\s*\?\s*'<div class="gcc-meta-row">[^']*gcc-subject-input/.test(source),
  );
  assert(/edited_subject: subject/.test(source));
  assert(/destinationLabel && sourcesRead\.length/.test(source));
  assert(!/no apps read in this request/.test(source), 'no empty data-flow line');

  console.log('reply_card_recipients ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
