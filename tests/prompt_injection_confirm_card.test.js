// The in-loop confirm card serves two callers: the browser gate (no title: keeps
// "Open browser?" / Allow / Cancel) and the data-source gate (title and labels given).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const match = source.match(/function _confirmCardText\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(match, '_confirmCardText not found in app.js');
const _confirmCardText = vm.runInNewContext(match[0] + ';_confirmCardText;', {});

{
  const t = _confirmCardText({});
  assert.strictEqual(t.title, 'Open browser?');
  assert.strictEqual(t.allowLabel, 'Allow');
  assert.strictEqual(t.denyLabel, 'Cancel');
  assert.strictEqual(t.isSource, false);
}
{
  const t = _confirmCardText({ title: 'Allow access to Jira?', allow_label: 'Allow for this tab', deny_label: 'Deny' });
  assert.strictEqual(t.title, 'Allow access to Jira?');
  assert.strictEqual(t.allowLabel, 'Allow for this tab');
  assert.strictEqual(t.denyLabel, 'Deny');
  assert.strictEqual(t.isSource, true);
}
assert(/source-confirm-\$\{confirm_id\}/.test(source), 'source cards must get a per-request id so two pending cards do not replace each other');

const expiredMatch = source.match(/function _confirmReplyExpired\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(expiredMatch, '_confirmReplyExpired not found in app.js');
const _confirmReplyExpired = vm.runInNewContext(expiredMatch[0] + ';_confirmReplyExpired;', {});
assert.strictEqual(_confirmReplyExpired({ ok: true }, { ok: true }), false);
assert.strictEqual(_confirmReplyExpired({ ok: true }, { ok: false, expired: true }), true);
assert.strictEqual(_confirmReplyExpired({ ok: false }, null), true, 'a rejected request is not a success');
assert.strictEqual(_confirmReplyExpired(null, null), true);
assert(/msg\.browser_confirm_expired/.test(source), 'the stream event that expires a card must be handled');
assert(!/_dismiss\(\);\s*await fetch\(`\/api\/browser\/confirm/.test(source), 'the card must not vanish before the server has answered');
// An expired card keeps its title and offers "Ask again" only when the request can be re-sent.
{
  const m = source.match(/function _expireConfirmCard\(card\) \{[\s\S]*?\n\}/);
  assert(m, '_expireConfirmCard not found in app.js');
  const el = () => ({
    children: [], listeners: {}, style: {}, textContent: '', removed: false,
    append(...c) { this.children.push(...c); }, appendChild(c) { this.children.push(c); },
    replaceChildren() { this.children = []; },
    addEventListener(t, f) { this.listeners[t] = f; },
    remove() { this.removed = true; },
    querySelector() { return { textContent: this._title }; },
  });
  const expire = vm.runInNewContext(m[0] + ';_expireConfirmCard;', { document: { createElement: el }, _pinConfirmCardInView: (c) => { c.pinned = true; } });
  const flat = (n) => [n, ...n.children.flatMap(flat)];

  const asked = [];
  const card = el();
  card._title = 'Allow access to Jira?';
  card._askAgain = () => asked.push(1);
  expire(card);
  assert.strictEqual(card.pinned, true, 'the expired card must be pinned into view');
  const nodes = flat(card);
  assert(nodes.some((n) => n.textContent === 'Allow access to Jira? (expired)'), 'the expired card keeps its title');
  const btn = nodes.find((n) => n.textContent === 'Ask again');
  assert(btn, 'an expired card needs a way to ask again');
  btn.listeners.click();
  assert.strictEqual(card.removed, true);
  assert.deepStrictEqual(asked, [1]);

  const noRetry = el();
  noRetry._title = 'Allow access to Jira?';
  expire(noRetry);
  assert(!flat(noRetry).some((n) => n.textContent === 'Ask again'), 'no button when there is nothing to re-send');
}
const showFn = source.match(/function _showBrowserConfirmCard\([\s\S]*?\n\}\s*\n/);
assert(showFn && /_pinConfirmCardInView\(card\)/.test(showFn[0]), 'a new card must be pinned into view like the text stream');
const pinFn = source.match(/function _pinConfirmCardInView\([\s\S]*?\n\}/);
assert(pinFn && /_pinScrollToBottom\(/.test(pinFn[0]), 'pin with the same helper the text stream uses');
console.log('ok');
