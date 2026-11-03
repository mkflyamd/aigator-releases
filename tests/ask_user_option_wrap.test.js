// The ask_user option buttons carry long label+description text; the shared .btn-secondary
// rule sets white-space: nowrap, so the option rule must turn wrapping back on.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');

function block(selector) {
  const m = css.match(
    new RegExp('(^|\\n)' + selector.replace(/[.]/g, '\\.') + '\\s*\\{([^}]*)\\}'),
  );
  assert(m, selector + ' rule exists');
  return m[2];
}

test('ask-user option button wraps long text', () => {
  const b = block('.ask-user-option');
  assert(/white-space:\s*normal/.test(b), 'white-space: normal');
  assert(/overflow-wrap:\s*anywhere/.test(b), 'overflow-wrap: anywhere');
});

test('ask-user option label and description wrap', () => {
  assert(/overflow-wrap:\s*anywhere/.test(block('.ask-user-option-label')));
  assert(/overflow-wrap:\s*anywhere/.test(block('.ask-user-option-desc')));
});
