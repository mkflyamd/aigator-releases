// The text copy of the chat that the browser keeps carries each attached image's saved path, so the
// server can still point the model at the file after it restarts and rebuilds the chat from it.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

const block = source.match(
  /const _imageNote = imagesSnapshot[\s\S]*?_saveTabHistory\(requestTabId, requestHistory\);/,
);
assert(block, 'history entry for a user turn builds an image note');
assert(/i\.savedPath/.test(block[0]), 'only images with a saved path are listed');
assert(/saved at \$\{i\.savedPath\}/.test(block[0]), 'the note names the saved path');
assert(/content: _imageNote \?/.test(block[0]), 'the note is appended to the stored user text');
assert(
  !/requestHistory\.push\(\{ role: 'user', content: finalText \}\)/.test(source),
  'plain finalText entry is gone',
);

console.log('image_path_in_history ok');
