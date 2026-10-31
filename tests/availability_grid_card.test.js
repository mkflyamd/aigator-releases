// The availability grid card: the text sent back when the user picks a slot.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

function load(name, stubs = {}) {
  const match = source.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  assert(match, name + ' found in app.js');
  return vm.runInNewContext(match[0] + '; ' + name + ';', stubs);
}

const clock = load('_availabilityGridClock');
const slotText = load('_availabilityGridSlotText', { _availabilityGridClock: clock });

assert.strictEqual(clock(8 * 60), '8:00 AM');
assert.strictEqual(clock(12 * 60 + 30), '12:30 PM');
assert.strictEqual(clock(0), '12:00 AM');

const grid = {
  timezone: 'Pacific Standard Time',
  first_minute: 480,
  step_minutes: 30,
  duration_minutes: 30,
  days: [{ date: '2030-01-07' }, { date: '2030-01-08' }],
};
assert.strictEqual(
  slotText(grid, 0, 4),
  'Monday, Jan 7, 10:00 AM – 10:30 AM (Pacific Standard Time)',
);
assert.strictEqual(
  slotText({ ...grid, duration_minutes: 60 }, 1, 19),
  'Tuesday, Jan 8, 5:30 PM – 6:30 PM (Pacific Standard Time)',
);

assert(/msg\.availability_grid\)\s*\{\s*_showAvailabilityGrid\(/.test(source), 'SSE handler wired');
console.log('availability_grid_card: ok');
