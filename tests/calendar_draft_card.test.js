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

// Like the email card, the calendar card has two buttons: Send invite (explicit click)
// and Open in Outlook.
const config = source.match(/'calendar-event': \{[\s\S]*?\n    \},/);
assert(config, 'calendar-event config present');
assert(!/hideApprove/.test(config[0]), 'approve button is not hidden');
assert(/sendLabel: 'Send invite'/.test(config[0]), 'Send invite label');
assert(/openButton: true/.test(config[0]), 'Open button shown next to Send');
assert(/openLabel: 'Open in Outlook'/.test(config[0]), 'Open in Outlook label');
assert(/<button class="gcc-approve-btn"[^`]*\$\{config\.sendLabel \|\| 'Send'\}/.test(source));
assert(/config\.openButton \? `<button class="gcc-open-outlook-btn"/.test(source));

// Nothing is sent until the click, and the title says so.
assert(/title: 'Meeting draft ready'/.test(config[0]), 'calendar title');
assert(/Nothing is sent until you press Send invite/.test(config[0]), 'footer note');
assert(/\$\{config\.title \|\| 'Draft ready for approval'\}/.test(source), 'title is configurable');

// Open uses the native-style new-event popout, and Send/Open lock each other out.
const openHandler = source.match(
  /openCalendarBtn\.addEventListener\('click'[\s\S]*?\r?\n    \}\);\r?\n/,
);
assert(openHandler, 'open handler found');
assert(/gatorShell\.openOutlookCompose\(url\)/.test(openHandler[0]), 'opens the popout window');
assert(!/openThirdPane/.test(openHandler[0]), 'does not load the draft into the Outlook pane');
assert(/approveBtn\.disabled = true/.test(openHandler[0]), 'opened draft cannot also be sent');
assert(/if \(openCalendarBtn\) openCalendarBtn\.disabled = true;/.test(source), 'Send locks Open');

console.log('calendar_draft_card ok');
