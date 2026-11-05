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

const detailed = new URL(
  composeUrl(
    { ...grid, people: [{ you: true, email: 'me@example.com' }, { email: 'sherry@example.com' }] },
    1,
    19,
    { subject: 'Design sync', body: 'Agenda & notes' },
  ),
);
assert.strictEqual(detailed.searchParams.get('subject'), 'Design sync');
assert.strictEqual(detailed.searchParams.get('body'), 'Agenda & notes');
assert.strictEqual(url.searchParams.get('subject'), null, 'no details, no subject parameter');

const detailsText = load('_availabilityGridDetailsText');
assert.strictEqual(detailsText({}), '');
assert.strictEqual(detailsText({ subject: ' Sync ', body: '' }), ' Meeting title: Sync.');
assert.strictEqual(
  detailsText({ subject: 'Sync', body: 'Line one\nLine two' }),
  ' Meeting title: Sync. Meeting message: Line one\nLine two',
);

const zoneLines = load('_availabilityGridZoneLines');
assert.deepStrictEqual(
  [
    ...zoneLines(
      [
        { label: '11:00 AM – 11:30 AM CST', people: ['aswin@example.com', 'tej@example.com'] },
        { label: '5:00 PM – 5:30 PM GMT', people: ['faisal@example.com', 'x@example.com'] },
      ],
      {
        people: [
          { you: true, email: 'me@example.com' },
          { name: 'Aswin', email: 'aswin@example.com' },
          { name: 'Tej', email: 'tej@example.com' },
          { name: 'Faisal', email: 'faisal@example.com' },
        ],
      },
    ),
  ],
  ['11:00 AM – 11:30 AM CST · Aswin, Tej', '5:00 PM – 5:30 PM GMT · Faisal, x@example.com'],
);
assert.deepStrictEqual([...zoneLines(null, { people: [] })], []);

let fire = null;
const shell = {
  isShell: true,
  onOutlookComposeClosed(cb) {
    fire = cb;
    return () => {
      fire = null;
    };
  },
};
const watch = load('_watchOutlookComposeClosed', { window: { gatorShell: shell } });
let closed = 0;
watch('https://outlook.office.com/a', () => closed++);
fire('https://outlook.office.com/other');
assert.strictEqual(closed, 0, 'another window closing is ignored');
fire('https://outlook.office.com/a');
assert.strictEqual(closed, 1, 'its own window closing re-enables the button');
assert.strictEqual(fire, null, 'and unsubscribes');
const watchPlain = load('_watchOutlookComposeClosed', { window: {} });
watchPlain('https://outlook.office.com/a', () => closed++);
assert.strictEqual(closed, 2, 'without the shell the button is ready straight away');

assert(/msg\.availability_grid\)\s*\{\s*_showAvailabilityGrid\(/.test(source), 'SSE handler wired');
assert(
  /postGridJson\('\/api\/calendar\/availability-days'/.test(source),
  'later weeks calls the route',
);
assert(
  /postGridJson\('\/api\/calendar\/grid-draft-series'/.test(source),
  'a repeating pick opens a draft series made by the server',
);
assert(
  /!repeating && !others\.some\(\(p\) => p\.optional\)/.test(source),
  'a one-time pick with an optional attendee opens a server-made draft, since the compose link cannot mark anyone optional',
);
assert(
  /sectionRow\('Required'\)[\s\S]*sectionRow\('Optional'\)/.test(source),
  'once someone is optional the grid rows are grouped under Required and Optional',
);
assert(
  /openOutlook\.disabled = !pickedAt \|\|/.test(source) && /Choose a time first/.test(source),
  'Open in Outlook stays disabled with a hint until a time is chosen',
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

const gridCard = source.match(/function _showAvailabilityGrid\([\s\S]*?\r?\n\}\r?\n/);
assert(gridCard, 'grid card found');
const card = gridCard[0];
assert(
  /_jiraEditRow\('subject', 'Title'[\s\S]*_jiraEditRow\('body', 'Message'/.test(card),
  'the grid has Title and Message boxes',
);
assert(
  /_availabilityGridComposeUrl\(grid, pickedAt\.di, pickedAt\.k, detailValues\(\)\)/.test(card),
  'a one-time Open in Outlook carries the title and message',
);
assert(
  /postGridJson\('\/api\/calendar\/grid-draft-series', \{[\s\S]*?\.\.\.detailValues\(\)/.test(card),
  'a server-made draft carries the title and message',
);
assert(
  /_availabilityGridDetailsText\(detailValues\(\)\)/.test(card),
  'Use this time hands the title and message to the model',
);
assert(
  /postGridJson\('\/api\/calendar\/slot-zones'/.test(card) &&
    /_availabilityGridZoneLines\(/.test(card),
  'picking a slot shows the time in each attendee zone',
);
assert(/zones: true/.test(card), 'adding a person also loads their zone');
assert(
  /_watchOutlookComposeClosed\(url,/.test(card) && /if \(openedUrl\)/.test(card),
  'Open in Outlook comes back after the window closes and reopens the stored URL',
);
assert(!/Draft opened in Outlook|Draft series opened in Outlook/.test(card), 'no stuck label');
assert(
  card.indexOf('let openedUrl') < card.indexOf('_availabilityGridRepeatPanel(() =>'),
  'state used by syncOutlookLink is declared before the repeat panel callback can run',
);

console.log('availability_grid_card: ok');
