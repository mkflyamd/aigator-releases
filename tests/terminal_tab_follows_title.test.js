// An agent terminal tab follows the title the running program sets (Claude Code /rename), minus its
// animated status glyph, ignores generic product titles, and never overrides a manual rename.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'tp-term-helpers.js'),
  'utf8',
);
const pieces = [
  /const _OC_GENERIC_TITLES[^\n]*\n/,
  /const _OC_TITLE_MAX[^\n]*\n/,
  /\nfunction _ocCleanProgramTitle\([^)]*\)\s*\{[\s\S]*?\n\}/,
  /\nfunction _ocFollowProgramTitle\([^)]*\)\s*\{[\s\S]*?\n\}/,
  /\nfunction _ocSpawnTerm\([^)]*\)\s*\{[\s\S]*?\n\}/,
].map((re) => {
  const m = source.match(re);
  assert(m, `${re} not found in tp-term-helpers.js`);
  return m[0];
});

function load(extra = {}) {
  const renders = [];
  const ctx = {
    _genAgentRenderTabs: (tabId) => renders.push(tabId),
    _ocXtermTheme: () => ({}),
    FitAddon: { FitAddon: class {} },
    WebSocket: { OPEN: 1 },
    Terminal: class {
      constructor() {
        this.handlers = [];
      }
      loadAddon() {}
      open() {}
      attachCustomKeyEventHandler() {}
      onData() {}
      onTitleChange(fn) {
        this.handlers.push(fn);
      }
    },
    ...extra,
  };
  vm.createContext(ctx);
  vm.runInContext(pieces.join('\n'), ctx);
  return { ctx, renders };
}

function session(over = {}) {
  return {
    tabId: 'tab1',
    agent: 'claude',
    label: 'Claude 1',
    container: { addEventListener() {} },
    ...over,
  };
}

function spawn(ctx, sess) {
  ctx._ocSpawnTerm(sess);
  return (title) => sess.term.handlers.forEach((h) => h(title));
}

{
  const { ctx } = load();
  const clean = ctx._ocCleanProgramTitle;
  assert.strictEqual(clean('✳ my-task'), 'my-task', 'idle glyph stripped');
  assert.strictEqual(clean('◐ my-task'), 'my-task', 'busy glyph stripped');
  assert.strictEqual(clean('◑ my-task'), 'my-task');
  assert.strictEqual(clean('⠋ build step'), 'build step', 'braille spinner stripped');
  assert.strictEqual(clean('[WIP] fix login'), '[WIP] fix login', 'brackets kept');
  assert.strictEqual(clean('#12 fix'), '#12 fix', 'issue number kept');
  assert.strictEqual(clean('a\u0007b\u001b[31mc'), 'a b [31mc', 'control characters removed');
  assert.strictEqual(clean('  a   b  '), 'a b', 'whitespace collapsed');
  assert.strictEqual(clean('✳ Claude Code'), '', 'generic Claude title ignored');
  assert.strictEqual(clean('claude'), '');
  assert.strictEqual(clean('OpenCode'), '');
  assert.strictEqual(clean(''), '');
  assert.strictEqual(clean(null), '');
  const long = clean('x'.repeat(100));
  assert.strictEqual(long.length, 40, 'capped');
  assert(long.endsWith('…'));
}

{
  const { ctx, renders } = load();
  const sess = session();
  const emit = spawn(ctx, sess);
  assert.strictEqual(sess._defaultLabel, 'Claude 1', 'default label remembered at spawn');
  assert.strictEqual(sess.term.handlers.length, 1, 'one title handler registered');

  emit('claude');
  emit('✳ Claude Code');
  assert.strictEqual(sess.label, 'Claude 1', 'generic titles leave the label alone');
  assert.strictEqual(renders.length, 0);

  emit('◐ aigator-osc-probe');
  assert.strictEqual(sess.label, 'aigator-osc-probe', '/rename title applied');
  assert.deepStrictEqual(renders, ['tab1'], 'tab re-rendered through the shared renderer');

  emit('◑ aigator-osc-probe');
  emit('✳ aigator-osc-probe');
  assert.strictEqual(renders.length, 1, 'spinner frames do not re-render');

  emit('✳ second-name');
  assert.strictEqual(sess.label, 'second-name', 'a later /rename still follows');
  assert.strictEqual(renders.length, 2);

  sess.label = 'My own name';
  emit('✳ third-name');
  assert.strictEqual(sess.label, 'My own name', 'manual rename wins');
  assert.strictEqual(renders.length, 2);
}

{
  const { ctx, renders } = load();
  const sess = session({ agent: 'terminal', label: 'Terminal 1' });
  const emit = spawn(ctx, sess);
  emit('Windows PowerShell');
  emit('C:\\Users\\x>');
  assert.strictEqual(sess.label, 'Terminal 1', 'plain shell tabs never follow the title');
  assert.strictEqual(renders.length, 0);
}

{
  const { ctx, renders } = load();
  ctx._genAgentEditing = true;
  const sess = session();
  const emit = spawn(ctx, sess);
  emit('✳ typed-while-editing');
  assert.strictEqual(sess.label, 'Claude 1', 'no overwrite while the user is renaming');
  assert.strictEqual(renders.length, 0);
  ctx._genAgentEditing = false;
  emit('✳ typed-while-editing');
  assert.strictEqual(sess.label, 'typed-while-editing', 'follows again once editing ends');
}

{
  const { ctx, renders } = load();
  const sess = session();
  const emit = spawn(ctx, sess);
  sess._closing = true;
  emit('✳ late-title');
  assert.strictEqual(sess.label, 'Claude 1', 'closing session ignores titles');
  assert.strictEqual(renders.length, 0);
}

console.log('terminal_tab_follows_title: ok');
