// A late chat_done for a finished task must not clear the state of a newer task on the same tab.
// The real chat_done block is cut out of app.js and run against fake state.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function chatDoneBlock() {
  const start = source.indexOf("if (msg.type === 'chat_done') {");
  assert(start > 0, 'chat_done block found');
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('chat_done block not closed');
}

const handler = chatDoneBlock();

function makeEnv() {
  const sendBtn = {
    classList: {
      removed: [],
      remove(c) {
        this.removed.push(c);
      },
    },
    setAttribute() {},
  };
  const ctx = {
    _chatTaskIds: new Map(),
    _inflightRequests: new Map(),
    _locallyFinishedTasks: new Set(),
    _activeTabId: 'tab-1',
    _isStreaming: true,
    _tabs: [],
    _tabsWithUpdates: new Set(),
    working: [],
    idle: 0,
    _setTabWorking: (id, on) => ctx.working.push([id, on]),
    _flushSandboxFollowUp: () => {},
    setStatus: (s) => {
      if (s === 'idle') ctx.idle++;
    },
    setTimeout: () => {},
    document: { getElementById: () => sendBtn, querySelector: () => null },
    _showConnectivityToast: () => {},
    sendBtn,
  };
  vm.createContext(ctx);
  ctx.run = (msg) => {
    ctx.msg = msg;
    vm.runInContext(`(function () { ${handler} })()`, ctx);
  };
  return ctx;
}

// A late chat_done for a finished task leaves the newer task alone.
let env = makeEnv();
env._locallyFinishedTasks.add('old');
env._chatTaskIds.set('tab-1', 'new');
env.run({ type: 'chat_done', context_id: 'tab-1', task_id: 'old' });
assert.strictEqual(env._chatTaskIds.get('tab-1'), 'new');
assert.strictEqual(env._isStreaming, true);
assert.strictEqual(env.idle, 0);
assert.deepStrictEqual(env.sendBtn.classList.removed, []);
assert.strictEqual(env._locallyFinishedTasks.has('old'), false);

// The same late chat_done, before the newer task is registered (its POST is still in flight).
env = makeEnv();
env._locallyFinishedTasks.add('old');
env.run({ type: 'chat_done', context_id: 'tab-1', task_id: 'old' });
assert.strictEqual(env._isStreaming, true);
assert.strictEqual(env.idle, 0);

// A chat_done that names a different task than the running one is ignored.
env = makeEnv();
env._chatTaskIds.set('tab-1', 'new');
env.run({ type: 'chat_done', context_id: 'tab-1', task_id: 'other' });
assert.strictEqual(env._chatTaskIds.get('tab-1'), 'new');
assert.strictEqual(env._isStreaming, true);

// A stalled task that never sent [DONE] still resets the tab (zombie-task fix).
env = makeEnv();
env._chatTaskIds.set('tab-1', 'stalled');
env.run({ type: 'chat_done', context_id: 'tab-1', task_id: 'stalled' });
assert.strictEqual(env._chatTaskIds.has('tab-1'), false);
assert.strictEqual(env._isStreaming, false);
assert.strictEqual(env.idle, 1);
assert.deepStrictEqual(env.sendBtn.classList.removed, ['is-streaming']);

// An older server without task_id keeps the previous behavior.
env = makeEnv();
env._chatTaskIds.set('tab-1', 'x');
env.run({ type: 'chat_done', context_id: 'tab-1' });
assert.strictEqual(env._isStreaming, false);

// Every local finish path records the task id, and the server sends it.
assert(/es\.close\(\);\s*_locallyFinishedTasks\.add\(task_id\);/.test(source), '[DONE] path');
assert(
  /EventSource\.CLOSED\) \{\s*_userScrolledUp = false;\s*_locallyFinishedTasks\.add\(task_id\);/.test(
    source,
  ),
  'closed-stream path',
);
assert(/_locallyFinishedTasks\.add\(_stopTaskId\);/.test(source), 'Stop path');
const chatPy = fs.readFileSync(path.join(__dirname, '..', 'web', 'routes', 'chat.py'), 'utf8');
assert(/"type": "chat_done", "context_id": context_id, "task_id": task_id/.test(chatPy));

console.log('chat_done_late: ok');
