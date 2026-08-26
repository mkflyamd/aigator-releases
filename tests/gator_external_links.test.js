const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
const handlerStart = source.indexOf('gatorView.webContents.setWindowOpenHandler');
const loadStart = source.indexOf('gatorView.webContents.loadURL(GATOR_URL)');

assert(handlerStart !== -1, 'Gator window-open handler is missing');
assert(handlerStart < loadStart, 'Gator window-open handler must be installed before loading');

const handler = source.slice(handlerStart, loadStart);
assert.match(handler, /shell\.openExternal\(url\)/, 'External links must use the default browser');
assert.match(
  handler,
  /\^\(https\?:\\\/\\\/\|mailto:\)/,
  'Only web and mail links may open externally',
);
assert.match(handler, /return \{ action: 'deny' \}/, 'Electron child windows must be denied');

console.log('gator_external_links: all assertions passed');
