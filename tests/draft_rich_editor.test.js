// Pure helpers behind the draft card rich editor. Each function is cut out of app.js and run in a vm.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function load(name, stubs = {}) {
  const match = source.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  assert(match, name + ' found in app.js');
  return vm.runInNewContext(match[0] + '; ' + name + ';', stubs);
}

const escapeHtml = load('escapeHtml');

// _normalizeDraftLinkUrl
const normalize = load('_normalizeDraftLinkUrl');
assert.strictEqual(normalize(''), '');
assert.strictEqual(normalize('  '), '');
assert.strictEqual(normalize('https://a.com/x'), 'https://a.com/x');
assert.strictEqual(normalize('HTTP://A.COM'), 'HTTP://A.COM');
assert.strictEqual(normalize('example.com'), 'https://example.com');
assert.strictEqual(normalize('a@b.com'), 'mailto:a@b.com');
assert.strictEqual(normalize('javascript:alert(1)'), '');
assert.strictEqual(normalize('data:text/html,x'), '');
assert.strictEqual(normalize('a b.com'), '');
assert.strictEqual(normalize('localhost:8080/x'), 'https://localhost:8080/x');

// _draftEditorSeedHtml
const seed = load('_draftEditorSeedHtml', { escapeHtml });
assert.strictEqual(
  seed({ body_html: '  <p>x</p> ', format_capabilities: ['bold'] }, 'fallback'),
  '<p>x</p>',
);
assert.strictEqual(
  seed({ body_html: '   ', format_capabilities: ['bold'] }, 'a < b\nc'),
  'a &lt; b<br>c',
);
// Drafts restored from before server-side sanitizing carry no format_capabilities: never trust their body_html.
assert.strictEqual(seed({ body_html: '<img src=x onerror=alert(1)>' }, 'a < b'), 'a &lt; b');
assert.strictEqual(seed({}, 'a < b\nc'), 'a &lt; b<br>c');
assert.strictEqual(seed({}, undefined), '');

// _draftFormatButtons
const buttons = load('_draftFormatButtons');
const caps = (list) => JSON.stringify(buttons(list).map((b) => b.cap));
assert.strictEqual(
  caps(['bold', 'italic', 'ul', 'ol', 'link', 'code']),
  '["bold","italic","ul","ol","link","code"]',
);
assert.strictEqual(caps(['link', 'bold']), '["bold","link"]');
assert.strictEqual(caps([]), '[]');
assert.strictEqual(caps(undefined), '[]');
assert.strictEqual(buttons(['underline'])[0].command, 'underline');
const groups = (list) => JSON.stringify(buttons(list).map((b) => b.group));
assert.strictEqual(
  groups(['bold', 'italic', 'underline', 'ul', 'ol', 'link', 'code']),
  '[1,1,1,2,2,3,3]',
);
assert.strictEqual(groups(['bold', 'italic', 'ul', 'ol', 'link']), '[1,1,2,2,3]');
assert.strictEqual(groups(['link', 'bold']), '[1,3]');

// _draftToolbarSeparatorBefore: dividers only between different groups, never leading
const separatorBefore = load('_draftToolbarSeparatorBefore');
const dividerPlan = (list) => {
  const all = buttons(list);
  return JSON.stringify(all.map((b, i) => separatorBefore(all[i - 1], b)));
};
assert.strictEqual(
  dividerPlan(['bold', 'italic', 'underline', 'ul', 'ol', 'link', 'code']),
  '[false,false,false,true,false,true,false]',
);
assert.strictEqual(dividerPlan(['bold', 'italic', 'link']), '[false,false,true]');
assert.strictEqual(dividerPlan(['ul', 'ol']), '[false,false]');
assert.strictEqual(dividerPlan(['code']), '[false]');

// _upgradeDraftMentions
const chips = [];
const upgrade = load('_upgradeDraftMentions', {
  _draftMentionChip: (service, person) => {
    // Like the real chip: the label comes from the person's name, not from the span it replaces.
    const chip = { service, person, textContent: '@' + person.name };
    chips.push(chip);
    return chip;
  },
});
const fakeSpan = ({ id, service, name, text, upgraded = false }) => ({
  dataset: { mentionId: id, mentionService: service, mentionName: name },
  classList: { contains: (c) => upgraded && c === 'gcc-inline-mention' },
  textContent: text,
  replacedWith: null,
  replaceWith(node) {
    this.replacedWith = node;
  },
});
const spans = [
  fakeSpan({ id: 'U1', service: 'slack', name: 'Alex', text: '@Alex' }),
  fakeSpan({ id: 'AAD1', service: 'teams', name: '', text: '@Sam' }),
  fakeSpan({ id: 'U2', service: 'slack', name: 'Z', text: '@Z', upgraded: true }),
  fakeSpan({ id: 'U3', service: 'slack', name: 'Ceo Name', text: '@Bob' }),
  fakeSpan({ id: '#C1', service: 'slack', name: 'general', text: '#general' }),
];
upgrade({ querySelectorAll: () => spans });
assert.strictEqual(chips.length, 4);
assert.strictEqual(chips[3].textContent, '#general');
assert.strictEqual(chips[2].textContent, '@Ceo Name');
assert.strictEqual(spans[3].replacedWith, chips[2]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(chips[0])), {
  service: 'slack',
  person: { name: 'Alex', id: 'U1' },
  textContent: '@Alex',
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(chips[1])), {
  service: 'teams',
  person: { name: 'Sam', id: 'AAD1' },
  textContent: '@Sam',
});
assert.strictEqual(spans[0].replacedWith, chips[0]);
assert.strictEqual(spans[1].replacedWith, chips[1]);
assert.strictEqual(spans[2].replacedWith, null);

console.log('ok');
