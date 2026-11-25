// The destructive confirmation (e.g. "Close and open here") must be keyboard- and
// screen-reader-safe: Cancel is the default focus, Escape cancels, Tab stays inside the
// dialog, focus returns to the control that opened it, and the dialog is labelled.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function extract(name) {
  const m = source.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  assert(m, name + ' not found in app.js');
  return m[0];
}

function fakeEl(name, doc) {
  return {
    name,
    listeners: {},
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    focus() {
      doc.activeElement = this;
    },
    contains(el) {
      return el === this || this.children.includes(el);
    },
    children: [],
  };
}

function setup({ invokerInDom = true } = {}) {
  const doc = { activeElement: null, body: { appended: [] } };
  const invoker = fakeEl('invoker', doc);
  doc.activeElement = invoker;
  const overlay = fakeEl('overlay', doc);
  const box = fakeEl('box', doc);
  const cancel = fakeEl('cancel', doc);
  const ok = fakeEl('ok', doc);
  box.children = [cancel, ok];
  overlay.children = [box, cancel, ok];
  overlay.removed = false;
  overlay.remove = () => {
    overlay.removed = true;
  };
  overlay.querySelector = (sel) =>
    ({ '.confirm-modal-box': box, '.confirm-modal-cancel': cancel, '.confirm-modal-ok': ok })[sel];
  box.querySelectorAll = () => [cancel, ok];
  doc.getElementById = () => null;
  doc.createElement = () => overlay;
  doc.body.appendChild = (el) => doc.body.appended.push(el);
  doc.contains = (el) => (el === invoker ? invokerInDom : false);
  const ctx = { document: doc };
  vm.createContext(ctx);
  vm.runInContext(extract('_confirmModalKeydown') + extract('_showConfirmModal'), ctx);
  return { ctx, doc, invoker, overlay, box, cancel, ok };
}

function key(k, extra = {}) {
  return { key: k, prevented: false, preventDefault() { this.prevented = true; }, ...extra };
}

// destructive dialogs start on Cancel; others keep the old default
{
  const a = setup();
  a.ctx._showConfirmModal('t', 'b', 'Go', () => {}, { cancelFirst: true });
  assert.strictEqual(a.doc.activeElement, a.cancel, 'Cancel has focus');
  const b = setup();
  b.ctx._showConfirmModal('t', 'b', 'Go', () => {});
  assert.strictEqual(b.doc.activeElement, b.ok, 'other callers keep focusing the confirm button');
}

// Escape cancels without confirming and returns focus to the invoking control
{
  const s = setup();
  let confirmed = false;
  s.ctx._showConfirmModal('t', 'b', 'Go', () => (confirmed = true), { cancelFirst: true });
  const e = key('Escape');
  s.overlay.listeners.keydown(e);
  assert(e.prevented);
  assert(s.overlay.removed, 'dialog closed');
  assert.strictEqual(confirmed, false, 'Escape never confirms');
  assert.strictEqual(s.doc.activeElement, s.invoker, 'focus restored to the invoker');
}

// Cancel button and backdrop also restore focus and never confirm
{
  const s = setup();
  let confirmed = false;
  s.ctx._showConfirmModal('t', 'b', 'Go', () => (confirmed = true), { cancelFirst: true });
  s.cancel.listeners.click();
  assert(s.overlay.removed && !confirmed);
  assert.strictEqual(s.doc.activeElement, s.invoker);
  const t = setup();
  t.ctx._showConfirmModal('t', 'b', 'Go', () => {}, { cancelFirst: true });
  t.overlay.listeners.click({ target: t.overlay });
  assert(t.overlay.removed);
  assert.strictEqual(t.doc.activeElement, t.invoker);
}

// confirming closes first, then runs the action
{
  const s = setup();
  let sawRemoved = null;
  s.ctx._showConfirmModal('t', 'b', 'Go', () => (sawRemoved = s.overlay.removed), { cancelFirst: true });
  s.ok.listeners.click();
  assert.strictEqual(sawRemoved, true);
}

// no focus restore when the invoking control left the page (a re-render replaced it)
{
  const s = setup({ invokerInDom: false });
  s.ctx._showConfirmModal('t', 'b', 'Go', () => {}, { cancelFirst: true });
  s.overlay.listeners.keydown(key('Escape'));
  assert.notStrictEqual(s.doc.activeElement, s.invoker);
}

// Tab and Shift+Tab wrap inside the dialog
{
  const s = setup();
  s.ctx._showConfirmModal('t', 'b', 'Go', () => {}, { cancelFirst: true });
  s.ok.focus();
  const fwd = key('Tab');
  s.overlay.listeners.keydown(fwd);
  assert(fwd.prevented);
  assert.strictEqual(s.doc.activeElement, s.cancel, 'Tab on the last control wraps to the first');
  const back = key('Tab', { shiftKey: true });
  s.overlay.listeners.keydown(back);
  assert(back.prevented);
  assert.strictEqual(s.doc.activeElement, s.ok, 'Shift+Tab on the first control wraps to the last');
  const mid = key('Tab');
  s.ok.focus();
  s.cancel.focus();
  s.overlay.listeners.keydown(mid);
  assert(!mid.prevented, 'Tab between the two controls is left to the browser');
}

// focus that escaped the dialog is pulled back in
{
  const s = setup();
  s.ctx._showConfirmModal('t', 'b', 'Go', () => {}, { cancelFirst: true });
  s.invoker.focus();
  const e = key('Tab');
  s.overlay.listeners.keydown(e);
  assert(e.prevented);
  assert.strictEqual(s.doc.activeElement, s.cancel);
}

// the dialog is labelled for assistive technology
{
  const fn = extract('_showConfirmModal');
  assert(fn.includes('role="alertdialog"'));
  assert(fn.includes('aria-modal="true"'));
  assert(fn.includes('aria-labelledby="confirm-modal-title"'));
  assert(fn.includes('id="confirm-modal-title"'));
  assert(fn.includes('aria-describedby="confirm-modal-body"'));
  assert(fn.includes('id="confirm-modal-body"'));
}

console.log('confirm_modal_a11y ok');
