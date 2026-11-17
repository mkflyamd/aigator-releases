// The calendar-update draft card: a read-only before/after diff with Send update and Open in Outlook.

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

const escapeHtml = load('escapeHtml');
const rows = load('_buildCalendarUpdateRows', {
  escapeHtml,
  _calendarDraftWhen: load('_calendarDraftWhen', { escapeHtml }),
  _calendarRecurrenceText: load('_calendarRecurrenceText'),
});

const base = {
  subject: 'Weekly <Sync>',
  scope: 'occurrence',
  timezone: 'Pacific Standard Time',
  before: { start: '2026-11-04T09:00:00', end: '2026-11-04T09:30:00', subject: 'Weekly <Sync>' },
  after: { start: '2026-11-05T10:00:00', end: '2026-11-05T10:30:00', subject: 'Weekly <Sync>' },
  notify: 'All',
  added: [],
  removed: [],
  moved: [],
};

const moved = rows({ ...base, changed: ['when'] });
assert(moved.includes('This occurrence only'), moved);
assert(moved.includes('Weekly &lt;Sync&gt;'), 'event title is escaped');
assert(moved.includes('<s>') && moved.includes('9:00 AM – 9:30 AM'), 'old time struck through');
assert(moved.includes('10:00 AM – 10:30 AM'), 'new time shown');
assert(moved.includes('Everyone on the invite'), moved);
assert(!moved.includes('Adding') && !moved.includes('Removing'), 'no attendee rows when unchanged');
assert(!/<input|<textarea/.test(moved), 'the card is read-only');

assert(rows({ ...base, scope: 'series', changed: [] }).includes('Whole series'));
assert(rows({ ...base, changed: [], notify: 'None' }).includes('No one is emailed'));

const people = rows({
  ...base,
  changed: ['attendees'],
  added: [{ email: 'new@x.com', name: 'New Person', type: 'required' }],
  removed: [{ email: 'old@x.com', name: 'old@x.com', type: 'optional' }],
  moved: [{ email: 'mv@x.com', name: '', from: 'optional', to: 'required' }],
});
assert(people.includes('New Person (new@x.com)'), people);
assert(/Removing[\s\S]*old@x\.com[\s\S]*optional/.test(people), people);
assert(people.includes('optional → required'), people);

const config = source.match(/'calendar-update': \{[\s\S]*?\n    \},/);
assert(config, 'calendar-update config present');
assert(/sendLabel: 'Send update'/.test(config[0]), 'Send update label');
assert(/openButton: true/.test(config[0]) && /openLabel: 'Open in Outlook'/.test(config[0]));
assert(/Nothing changes until you press Send update/.test(config[0]), 'footer note');
assert(/handoffNote: 'Opened in Outlook. Nothing was changed.'/.test(config[0]), 'handoff note');
assert(!/hideApprove/.test(config[0]), 'approve button is not hidden');
assert(/type === 'calendar-update'/.test(source), 'no subject line above the card');

console.log('calendar_update_card ok');
