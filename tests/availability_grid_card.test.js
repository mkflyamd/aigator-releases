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

const composeUrl = load('_availabilityGridComposeUrl');
const url = new URL(
  composeUrl(
    {
      ...grid,
      people: [
        { you: true, email: 'me@example.com' },
        { email: 'sherry@example.com' },
        { email: 'james@example.com' },
      ],
    },
    1,
    19,
  ),
);
assert.strictEqual(
  url.origin + url.pathname,
  'https://outlook.office.com/calendar/0/deeplink/compose',
);
assert.strictEqual(url.searchParams.get('startdt'), '2030-01-08T17:30:00');
assert.strictEqual(url.searchParams.get('enddt'), '2030-01-08T18:00:00');
assert.strictEqual(url.searchParams.get('to'), 'sherry@example.com;james@example.com');

assert(/msg\.availability_grid\)\s*\{\s*_showAvailabilityGrid\(/.test(source), 'SSE handler wired');
assert(/fetch\('\/api\/calendar\/availability-days'/.test(source), 'later weeks calls the route');
const fits = load('_availabilityGridFits');
const open = '0'.repeat(16) + '1'.repeat(20) + '0'.repeat(12);
const busyAt = (slot) => 'f'.repeat(slot) + 'b' + 'f'.repeat(47 - slot);
const g2 = {
  step_minutes: 30,
  duration_minutes: 60,
  people: [{ you: true }, { email: 'sherry@example.com', optional: false }],
  days: [{ open, rows: ['f'.repeat(48), busyAt(20)] }],
};
assert.strictEqual(fits(g2, 0, 10), false, 'outside the work window');
assert.strictEqual(fits(g2, 0, 18), true, 'free in work hours');
assert.strictEqual(fits(g2, 0, 19), false, 'second half hour busy');
assert.strictEqual(fits(g2, 0, 20), false, 'first half hour busy');
g2.people[1].optional = true;
assert.strictEqual(fits(g2, 0, 20), true, 'an optional person does not block');

const attendeeText = load('_availabilityGridAttendeeText');
assert.strictEqual(
  attendeeText({
    people: [
      { you: true, email: 'me@example.com' },
      { email: 'sherry@example.com', optional: false },
      { email: 'james@example.com', optional: true },
    ],
  }),
  ' Required attendees: sherry@example.com. Optional attendees: james@example.com.',
);

const repeatText = load('_availabilityGridRepeatText');
assert.strictEqual(repeatText('none'), ' This is a one-time meeting, not recurring.');
assert.strictEqual(repeatText('weekly'), ' Make it recurring weekly.');
assert.strictEqual(repeatText('biweekly'), ' Make it recurring every 2 weeks.');
assert.strictEqual(repeatText('weekdays'), ' Make it recurring every weekday.');
assert.strictEqual(repeatText(undefined), ' This is a one-time meeting, not recurring.');

assert(/ag-chip-remove/.test(source) && !/ag-role/.test(source), 'people are chips with a remove button');

console.log('availability_grid_card: ok');
