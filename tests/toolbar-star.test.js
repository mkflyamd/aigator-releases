const test = require('node:test');
const assert = require('node:assert');
const star = require('../shell/toolbar-star');

const apps = [
  { id: 'custom-power-bi', url: 'https://app.powerbi.com/home' },
  { id: 'custom-cnn', url: 'https://www.cnn.com/' },
];

test('originKey lower-cases and rejects non-http', () => {
  assert.strictEqual(star.originKey('HTTPS://App.PowerBI.com/x?y=1'), 'https://app.powerbi.com');
  assert.strictEqual(star.originKey('about:blank'), '');
  assert.strictEqual(star.originKey('not a url'), '');
});

test('findStarredApp matches by origin, ignoring path', () => {
  assert.strictEqual(
    star.findStarredApp('https://app.powerbi.com/groups/1/reports/2', apps, new Set()),
    'custom-power-bi',
  );
  assert.strictEqual(star.findStarredApp('https://edition.cnn.com/', apps, new Set()), null);
});

test('findStarredApp skips apps pending deletion', () => {
  assert.strictEqual(
    star.findStarredApp('https://www.cnn.com/world', apps, new Set(['custom-cnn'])),
    null,
  );
});

test('starState reports filled with the app id, else empty', () => {
  assert.deepStrictEqual(star.starState('https://www.cnn.com/a', apps, new Set()), {
    state: 'filled',
    appId: 'custom-cnn',
  });
  assert.deepStrictEqual(star.starState('https://example.com/', apps, new Set()), {
    state: 'empty',
    appId: null,
  });
});

test('defaultAppName prefers the title, falls back to the host, caps length', () => {
  assert.strictEqual(star.defaultAppName('  Sales Dashboard ', 'https://x.com'), 'Sales Dashboard');
  assert.strictEqual(star.defaultAppName('', 'https://www.example.com/a'), 'example.com');
  assert.strictEqual(star.defaultAppName('a'.repeat(60), 'https://x.com').length, 40);
});

test('clicking a filled star un-favorites directly instead of opening the edit bubble', () => {
  const html = require('node:fs').readFileSync(
    require('node:path').join(__dirname, '..', 'shell', 'toolbar.html'),
    'utf8',
  );
  const click = html.match(/elStar\.addEventListener\('click'[\s\S]*?\n        \}\);/)[0];
  assert(/star\.state === 'filled'[\s\S]*toolbar:star-remove/.test(click));
  assert(!/openBubble/.test(click));
});
