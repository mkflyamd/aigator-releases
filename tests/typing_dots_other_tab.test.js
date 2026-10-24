const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const start = source.indexOf('const _streamLive = () =>');
const turn = source.slice(start, source.indexOf('_activeStops.add(_onStop)'));

test('a turn keeps its dots and streaming render when another tab finishes', () => {
  assert(start > 0, 'per-turn liveness check exists');
  assert(turn.includes('_chatTaskIds.get(requestTabId) === _streamTaskId'));
  const body = source.slice(start, source.indexOf('_browserPoll', start));
  assert(
    !/\b_isStreaming\s*(&&|\?|\))/.test(body.replace(/_isStreaming\s*=\s*(true|false)/g, '')),
    'the dots interval and renderers must not read the tab-shared _isStreaming flag',
  );
});

test('every way a turn ends marks it over', () => {
  const ends = source.match(/_streamOver = true;/g) || [];
  assert(ends.length >= 5, 'stop, POST error, done, stream error and final cleanup');
});
