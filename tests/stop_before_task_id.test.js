// Stop pressed while POST /api/chat is still in flight has no task id to cancel yet.
// Once the task id arrives, doSend must cancel it and abort instead of starting the turn.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

const afterPost = source.slice(source.indexOf('const { task_id } = await postRes.json();'));
const beforeRegister = afterPost.slice(0, afterPost.indexOf('_chatTaskIds.set(_tabKey, task_id)'));

assert(beforeRegister.length > 0, 'task id registration not found after the POST');
assert(
  /if \(_userStopped\) \{/.test(beforeRegister),
  'doSend must check _userStopped before registering the task',
);
assert(
  /\/api\/chat\/\$\{task_id\}\/cancel/.test(beforeRegister),
  'the late task id must be cancelled',
);
assert(
  /name: 'AbortError'/.test(beforeRegister),
  'doSend must abort through the AbortError path so cleanup runs',
);

console.log('stop_before_task_id: all assertions passed');
