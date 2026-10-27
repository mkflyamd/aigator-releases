const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const pkg = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'shell', 'package.json'), 'utf8'),
);

test('macOS app declares why it needs the microphone', () => {
  const info = pkg.build.mac.extendInfo;
  assert.ok(info, 'build.mac.extendInfo is missing');
  assert.ok(
    typeof info.NSMicrophoneUsageDescription === 'string' &&
      info.NSMicrophoneUsageDescription.trim().length > 0,
    'NSMicrophoneUsageDescription must be a non-empty string',
  );
});
