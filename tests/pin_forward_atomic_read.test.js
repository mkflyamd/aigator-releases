// The shell takes a pending pin and clears it in one script so a busy page cannot hand the same
// pin to two polls (one pin used to insert several chips).

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');
const start = source.indexOf('function _forwardPinFromFrame(');
assert(start > 0, '_forwardPinFromFrame found');
const body = source.slice(start, start + 1500);

assert(
  /executeJavaScript\(\s*'\(function\(\)\{var c=window\.__gatorPinCtx\|\|null;window\.__gatorPinCtx=null;return c;\}\)\(\)'/.test(
    body,
  ),
  'pin context is read and cleared in one script',
);
assert(
  !/executeJavaScript\('window\.__gatorPinCtx = null;'\)/.test(body),
  'no separate clear call',
);
console.log('pin_forward_atomic_read: ok');
