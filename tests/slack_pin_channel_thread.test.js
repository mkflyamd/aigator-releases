// Slack pin: channel vs thread header conflation regression.
//
// BUG: When a thread pane was open alongside the channel view, the Slack pin
// module used a GLOBAL isInThread check (`!!document.querySelector('.p-flexpane_header__primary')`)
// for BOTH the channel header pin and the thread header pin. This meant clicking
// the CHANNEL pin button reported kind='thread' and carried the thread's ts —
// so pinning a channel actually pinned the open thread.
//
// Additionally, the thread label was scraped from `.p-flexpane_header__primary`
// textContent (which is literally "Thread"), producing chip labels like
// "Thread (thread)".
//
// FIX: The Slack module now injects SEPARATE pin buttons (one per header, each
// with a distinct id and dataset.gatorKind), and headerClick determines kind
// from the clicked button's location, not a global check. The thread label is
// the first message's text, not the literal "Thread" header text.
//
// This test asserts the source-level guards: the old single-id/global-check
// pattern is gone, and the new per-header pattern is present.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'shell', 'main.js'), 'utf8');

// Isolate the Slack pin module by finding its sentinel block. The Slack module
// is the IIFE that contains GATOR_SVG (a Slack-specific var). We slice from
// that sentinel to the pin-forwarder section to avoid matching Teams/Outlook/
// OneNote modules. Normalize CRLF -> LF for stable regex matching.
const sourceLF = source.replace(/\r\n/g, '\n');
const slackStart = sourceLF.indexOf('var GATOR_SVG');
assert(slackStart !== -1, 'Slack pin module sentinel (GATOR_SVG) not found in main.js');
// Back up to the IIFE opener for context.
const iifeStart = sourceLF.lastIndexOf('(function() {', slackStart);
const slackModuleStart = iifeStart !== -1 ? iifeStart : slackStart;
// The Slack module ends before the pin-forwarder section.
const forwarderIdx = sourceLF.indexOf('Pin forwarding: poll active app view', slackStart);
assert(forwarderIdx !== -1, 'Slack module end marker not found');
const slackModule = sourceLF.slice(slackModuleStart, forwarderIdx);

// --- Guard: old single __gator_pin_header id must be gone from Slack module ---
// The Slack module must NOT create/build a pin with id __gator_pin_header (that
// id is now reserved for Teams/Outlook). Slack uses __gator_pin_channel and
// __gator_pin_thread. A cleanup reference (getElementById to remove stale old
// buttons) is allowed but buildGatorBtn must never receive __gator_pin_header.
assert(
  !/buildGatorBtn\(\s*['"]__gator_pin_header['"]/.test(slackModule),
  'Slack pin module must not build a pin with id __gator_pin_header (now uses __gator_pin_channel + __gator_pin_thread)',
);

// --- Guard: separate channel + thread pin ids must be present ---
assert(
  /__gator_pin_channel/.test(slackModule),
  'Slack module must inject a channel-header pin with id __gator_pin_channel',
);
assert(
  /__gator_pin_thread/.test(slackModule),
  'Slack module must inject a thread-pane pin with id __gator_pin_thread',
);

// --- Guard: headerClick must use kindFromBtn, NOT a global isInThread ---
// The old code did `var isInThread = !!document.querySelector('.p-flexpane_header__primary');`
// inside headerClick. That global check is the root cause of the conflation.
assert(
  !/var isInThread\s*=\s*!!document\.querySelector\(['"]\.p-flexpane_header__primary['"]\)/.test(
    slackModule,
  ),
  'headerClick must not use a global isInThread check (conflates channel + thread headers)',
);
assert(
  /function kindFromBtn/.test(slackModule),
  'Slack module must define kindFromBtn to determine kind from the clicked button',
);
assert(
  /b\.dataset\.gatorKind/.test(slackModule),
  'Slack pin buttons must carry dataset.gatorKind for kindFromBtn to read',
);

// --- Guard: thread label must come from message text, not "Thread" header ---
// The old code read `.p-flexpane_header__primary` textContent (which is "Thread")
// and stripped the "Thread" prefix, leaving an empty label that fell back to
// "Thread". The fix reads the first message's text via threadLabelFromDOM.
assert(
  /function threadLabelFromDOM/.test(slackModule),
  'Slack module must define threadLabelFromDOM to extract a rich label from the first message',
);
assert(
  !/flexText\.replace\(\s*\/\^Thread\/i/.test(slackModule),
  'Slack module must not scrape the thread label from the "Thread" header text',
);

// --- Guard: the redundant " (thread)" suffix must be gone from the forwarder ---
// The pin forwarder (_forwardPinFromFrame) appended " (thread)" to thread labels,
// producing "Thread (thread)". The label is now descriptive on its own.
assert(
  !/pinKind\s*===\s*['"]thread['"]\s*\)\s*pinLabel\s*\+=\s*['"]\s*\(thread\)['"]/.test(sourceLF),
  'pin forwarder must not append " (thread)" to thread labels (was producing "Thread (thread)")',
);

// --- Guard: threadLabelFromDOM must handle the small-screen layout ----------
// On small screens, the thread REPLACES the primary view — no [role="dialog"].
// The messages live inside the .p-flexpane ancestor of the thread header. The
// old code fell back to .p-flexpane_header__primary (the header bar) and
// searched for messages WITHIN it — finding none, returning empty, which
// produced the "thread thread" tooltip.
assert(
  /\.p-flexpane_header__primary/.test(slackModule) &&
    /\.closest\(['"]\.p-flexpane['"]\)/.test(slackModule),
  'threadLabelFromDOM must search the .p-flexpane container (not just the header) for messages on small screens',
);
// The old [roledescription="message"] selector doesn't match Slack's DOM
// (Slack uses aria-roledescription, and it's on a child of [data-item-key]).
assert(
  !/\[roledescription=['"]message['"]\]/.test(slackModule),
  'threadLabelFromDOM must not use [roledescription="message"] (use [data-item-key] instead)',
);

// --- Guard: no "thread thread" tooltip double-word ---------------------------
// The old fallback produced label "thread" and the tooltip was
// 'Pin to Gator: thread ' + 'thread' = 'Pin to Gator: thread thread'.
// The fallback must not produce the word "thread" as the label.
assert(
  !/ctx\.channel\s*\?\s*ctx\.channel\s*\+\s*['"]\s*thread['"]\s*:\s*['"]thread['"]/.test(
    slackModule,
  ),
  'thread label fallback must not produce the literal word "thread" (causes "Pin to Gator: thread thread")',
);

console.log('slack_pin_channel_thread.test.js: all assertions passed');
