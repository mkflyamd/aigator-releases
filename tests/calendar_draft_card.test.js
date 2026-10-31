// The calendar-event draft card: rows shown to the user and the Open in Outlook-only action.

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
const when = load('_calendarDraftWhen', { escapeHtml });
const rows = load('_buildCalendarDraftRows', { escapeHtml, _calendarDraftWhen: when });

const html = rows({
  subject: 'Sync',
  start: '2026-11-02T09:00:00',
  end: '2026-11-02T09:30:00',
  timezone: 'Pacific Standard Time',
  attendees: ['A@x.com'],
  optional_attendees: ['c@z.com'],
  location: 'Room <4>',
  teams: true,
  attendee_local: { 'a@x.com': '10:30 PM – 11:00 PM IST' },
});
assert(
  html.includes('Mon, Nov 2') || html.includes('Mon Nov 2') || html.includes('Mon, Nov 02'),
  html,
);
assert(html.includes('9:00 AM – 9:30 AM Pacific Standard Time'), html);
assert(html.includes('A@x.com') && html.includes('10:30 PM – 11:00 PM IST'), html);
assert(html.includes('c@z.com') && html.includes('(optional)'), html);
assert(html.includes('Room &lt;4&gt;'), 'location is escaped');
assert(html.includes('Teams meeting') && html.includes('Yes'), html);

// Afternoon times and an unparsable start fall back sensibly.
assert(
  when({ start: '2026-11-02T14:05:00', end: '2026-11-02T15:00:00' }).includes('2:05 PM – 3:00 PM'),
);
assert.strictEqual(when({ start: 'garbage', end: '' }), 'garbage');

// The card config offers only Open in Outlook: no approve button for this type.
const config = source.match(/'calendar-event': \{[\s\S]*?\n    \},/);
assert(config, 'calendar-event config present');
assert(/hideApprove: true/.test(config[0]), 'no approve button');
assert(/openLabel: 'Open in Outlook'/.test(config[0]), 'Open in Outlook label');
assert(/config\.hideApprove\s*\?\s*`<button class="gcc-open-outlook-btn"/.test(source));

// The card does not claim an approval or a send: the user sends from Outlook.
assert(/title: 'Meeting draft ready'/.test(config[0]), 'calendar title');
assert(/flowVerb: 'Opens in'/.test(config[0]), 'calendar flow verb');
assert(/\$\{config\.title \|\| 'Draft ready for approval'\}/.test(source), 'title is configurable');
assert(/\$\{config\.flowVerb \|\| 'Sending to'\}/.test(source), 'flow verb is configurable');

console.log('calendar_draft_card ok');
