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

const slotTimes = load('_availabilityGridSlotTimes');
assert.deepStrictEqual(
  { ...slotTimes(grid, 1, 19) },
  { start: '2030-01-08T17:30:00', end: '2030-01-08T18:00:00' },
);

const composeUrl = load('_availabilityGridComposeUrl', { _availabilityGridSlotTimes: slotTimes });
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
assert(
  /postGridJson\('\/api\/calendar\/availability-days'/.test(source),
  'later weeks calls the route',
);
assert(
  /postGridJson\('\/api\/calendar\/grid-draft-series'/.test(source),
  'a repeating pick opens a draft series made by the server',
);
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
  ' Required attendees: sherry@example.com. Optional attendees: james@example.com.' +
    ' Invite only these people; anyone removed in the grid is not invited.',
);
assert.strictEqual(
  attendeeText({ people: [{ you: true, email: 'me@example.com' }] }),
  ' There are no other attendees; anyone mentioned earlier was removed in the grid.',
);

const repeatText = load('_availabilityGridRepeatText');
const noEnd = { end: 'none' };
assert.strictEqual(repeatText(null), ' This is a one-time meeting, not recurring.');
assert.strictEqual(repeatText(undefined), ' This is a one-time meeting, not recurring.');
assert.strictEqual(
  repeatText({ type: 'daily', interval: 1, ...noEnd }),
  ' Make it recurring every day, with no end date.',
);
assert.strictEqual(
  repeatText({ type: 'daily', weekdaysOnly: true, end: 'count', count: 10 }),
  ' Make it recurring every weekday, ending after 10 occurrences.',
);
assert.strictEqual(
  repeatText({
    type: 'weekly',
    interval: 2,
    days: ['Monday', 'Wednesday', 'Friday'],
    end: 'date',
    endDate: '2027-04-18',
  }),
  ' Make it recurring every 2 weeks on Monday, Wednesday and Friday, ending by 2027-04-18.',
);
assert.strictEqual(
  repeatText({ type: 'weekly', interval: 1, days: ['Sunday'], ...noEnd }),
  ' Make it recurring every week on Sunday, with no end date.',
);
assert.strictEqual(
  repeatText({ type: 'monthly', mode: 'day', day: 15, interval: 1, ...noEnd }),
  ' Make it recurring on day 15 of every month, with no end date.',
);
assert.strictEqual(
  repeatText({
    type: 'monthly',
    mode: 'nth',
    ordinal: 'first',
    weekday: 'Sunday',
    interval: 3,
    end: 'count',
    count: 4,
  }),
  ' Make it recurring on the first Sunday of every 3 months, ending after 4 occurrences.',
);
assert.strictEqual(
  repeatText({ type: 'yearly', mode: 'date', month: 11, day: 1, interval: 1, ...noEnd }),
  ' Make it recurring every year on November 1, with no end date.',
);
assert.strictEqual(
  repeatText({
    type: 'yearly',
    mode: 'nth',
    ordinal: 'last',
    weekday: 'Friday',
    month: 3,
    interval: 2,
    ...noEnd,
  }),
  ' Make it recurring every 2 years on the last Friday of March, with no end date.',
);

const firstMeeting = load('_availabilityGridFirstMeeting');
// 2026-11-03 is a Tuesday.
assert.strictEqual(
  firstMeeting('2026-11-03', {
    type: 'monthly',
    mode: 'nth',
    ordinal: 'second',
    weekday: 'Monday',
    interval: 1,
  }),
  '2026-11-09',
);
assert.strictEqual(
  firstMeeting('2026-11-03', {
    type: 'monthly',
    mode: 'nth',
    ordinal: 'first',
    weekday: 'Tuesday',
    interval: 1,
  }),
  '2026-11-03',
);
assert.strictEqual(
  firstMeeting('2026-11-03', { type: 'weekly', interval: 1, days: ['Monday', 'Wednesday'] }),
  '2026-11-04',
);
assert.strictEqual(
  firstMeeting('2026-11-03', { type: 'weekly', interval: 2, days: ['Monday'] }),
  '2026-11-16',
);
assert.strictEqual(firstMeeting('2026-11-03', { type: 'daily', weekdaysOnly: true }), '2026-11-03');
assert.strictEqual(firstMeeting('2026-11-07', { type: 'daily', weekdaysOnly: true }), '2026-11-09');
assert.strictEqual(
  firstMeeting('2026-11-03', { type: 'monthly', mode: 'day', day: 1, interval: 1 }),
  '2026-12-01',
);
assert.strictEqual(
  firstMeeting('2026-11-03', {
    type: 'yearly',
    mode: 'nth',
    ordinal: 'last',
    weekday: 'Friday',
    month: 3,
    interval: 1,
  }),
  '2027-03-26',
);
assert.strictEqual(
  firstMeeting('2026-11-03', { type: 'yearly', mode: 'date', month: 11, day: 3, interval: 1 }),
  '2026-11-03',
);
assert.strictEqual(
  repeatText(
    { type: 'monthly', mode: 'nth', ordinal: 'second', weekday: 'Monday', interval: 1, ...noEnd },
    '2026-11-03',
    '2026-11-09',
  ),
  ' Make it recurring on the second Monday of every month, with no end date.' +
    ' The picked day is not on this repeat, so the first meeting is Monday, Nov 9, at the picked time.',
);
assert.strictEqual(
  repeatText({ type: 'daily', interval: 1, ...noEnd }, '2026-11-03', '2026-11-03'),
  ' Make it recurring every day, with no end date.',
);

const preset = load('_availabilityGridRepeatPreset');
assert.deepStrictEqual({ ...preset('biweekly') }, { type: 'weekly', interval: 2 });
assert.deepStrictEqual({ ...preset('weekdays') }, { type: 'daily', weekdaysOnly: true });
assert.strictEqual(preset('none'), null);

assert(
  /ag-chip-remove/.test(source) && /ag-chip-role/.test(source) && !/ag-role\b/.test(source),
  'people are chips with a visible Required/Optional pill and a remove button',
);

console.log('availability_grid_card: ok');
