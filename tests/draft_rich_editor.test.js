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
assert.strictEqual(seed({ body_html: '  <p>x</p> ' }, 'fallback'), '<p>x</p>');
assert.strictEqual(seed({ body_html: '   ' }, 'a < b\nc'), 'a &lt; b<br>c');
assert.strictEqual(seed({}, 'a < b\nc'), 'a &lt; b<br>c');
assert.strictEqual(seed({}, undefined), '');

// _draftFormatButtons
const buttons = load('_draftFormatButtons');
const caps = (list) => JSON.stringify(buttons(list).map((b) => b.cap));
assert.strictEqual(caps(['bold', 'italic', 'ul', 'ol', 'link', 'code']), '["bold","italic","ul","ol","link","code"]');
assert.strictEqual(caps(['link', 'bold']), '["bold","link"]');
assert.strictEqual(caps([]), '[]');
assert.strictEqual(caps(undefined), '[]');
assert.strictEqual(buttons(['underline'])[0].command, 'underline');

// _upgradeDraftMentions
const chips = [];
const upgrade = load('_upgradeDraftMentions', {
  _draftMentionChip: (service, person) => {
    const chip = { service, person, textContent: '' };
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
];
upgrade({ querySelectorAll: () => spans });
assert.strictEqual(chips.length, 2);
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
