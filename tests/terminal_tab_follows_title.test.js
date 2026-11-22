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
const source2 = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'tp-generic-agent-terminal.js'),
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
  sess._manualRename = true;
  emit('✳ third-name');
  assert.strictEqual(sess.label, 'My own name', 'manual rename wins');
  assert.strictEqual(renders.length, 2);
}

{
  const clean = load().ctx._ocCleanProgramTitle;
  assert.strictEqual(clean('codex'), '', 'generic Codex title ignored');
  assert.strictEqual(clean('Crush'), '', 'generic Crush title ignored');
  assert.strictEqual(clean('x'.repeat(40)), 'x'.repeat(40), '40 characters kept whole');
  assert.strictEqual(clean('x'.repeat(41)), 'x'.repeat(39) + '…', '41 characters truncated to 40');
  assert.strictEqual(clean('a\u0085b'), 'a b', 'C1 control character removed');
  assert.strictEqual(clean('· task'), 'task', 'leading middle dot stripped');
  assert.strictEqual(clean('^ task'), 'task', 'leading modifier symbol stripped');
  assert.strictEqual(clean('✳'), '', 'glyph-only title ignored');
  assert.strictEqual(clean('✳ ◐ '), '', 'several glyphs and spaces ignored');
}

{
  // A rename to the very label the tab started with must still end the following.
  const { ctx, renders } = load();
  const sess = session();
  const emit = spawn(ctx, sess);
  sess.label = 'Claude 1';
  sess._manualRename = true;
  emit('✳ program-name');
  assert.strictEqual(sess.label, 'Claude 1', 'user rename back to the default label is kept');
  assert.strictEqual(renders.length, 0);
}

{
  const fns = source2.match(/\nfunction _genAgentBeginRename\([^)]*\)\s*\{[\s\S]*?\n\}/);
  assert(fns, '_genAgentBeginRename not found');
  const renameSrc =
    'let _genAgentEditing = false;\n' + fns[0] + '\nthis._editing = () => _genAgentEditing;';
  const make = () => {
    const handlers = {};
    const labelEl = {
      textContent: '',
      classList: { add() {}, remove() {} },
      focus() {},
      addEventListener(n, f) {
        handlers[n] = f;
      },
      removeEventListener() {},
      selectNodeContents() {},
    };
    const ctx = {
      setTimeout: () => 0,
      document: { createRange: () => ({ selectNodeContents() {} }) },
      window: { getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
    };
    vm.createContext(ctx);
    vm.runInContext(renameSrc, ctx);
    return { ctx, labelEl, handlers };
  };

  {
    const { ctx, labelEl, handlers } = make();
    const sess = { label: 'program-title' };
    ctx._genAgentBeginRename(sess, labelEl);
    assert.strictEqual(ctx._editing(), true);
    labelEl.textContent = 'Claude 1';
    handlers.keydown({ key: 'Enter', preventDefault() {} });
    assert.strictEqual(sess.label, 'Claude 1');
    assert.strictEqual(
      sess._manualRename,
      true,
      'a typed name that equals the default still counts',
    );
    assert.strictEqual(ctx._editing(), false);
  }
  {
    const { ctx, labelEl, handlers } = make();
    const sess = { label: 'program-title' };
    ctx._genAgentBeginRename(sess, labelEl);
    labelEl.textContent = 'program-title';
    handlers.blur();
    assert.strictEqual(sess._manualRename, undefined, 'blur without a change is not a rename');
  }
  {
    const { ctx, labelEl, handlers } = make();
    const sess = { label: 'program-title' };
    ctx._genAgentBeginRename(sess, labelEl);
    labelEl.textContent = 'typed';
    handlers.keydown({ key: 'Escape', preventDefault() {} });
    assert.strictEqual(sess.label, 'program-title', 'Escape cancels');
    assert.strictEqual(sess._manualRename, undefined);
  }
}

{
  const m = source2.match(/\nfunction _genAgentRenderTabs\([^)]*\)\s*\{[\s\S]*?\n\}/);
  assert(m, '_genAgentRenderTabs not found');
  assert(
    /_genAgentEditing = false;\s*\n\s*\[\.\.\.scroll\.querySelectorAll\('\.gtp-tab'\)\]/.test(m[0]),
    'rebuilding the tab strip clears the editing flag',
  );
  assert(
    /\.length === 0\) \{\s*\n\s*_genAgentEditing = false;/.test(m[0]),
    'removing the tab strip clears the editing flag',
  );
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
