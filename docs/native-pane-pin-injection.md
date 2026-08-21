# Gator Pin Injection — Architecture & Implementation Guide

## Overview

The Gator Pin system injects small green buttons into third-party web apps
(Slack, Teams, Outlook, OneDrive, OneNote, Confluence, Jira, GitHub) loaded
inside the Electron shell's `WebContentsView`. The buttons let users pin context
(channels, threads, messages, emails, files, pages, issues) to Gator's chat
composer, where the agent can use it as reference.

This document covers the hardened architecture (post-review consensus) and
how to add pin support for new apps.

Apps implemented today: **Slack** (the original), **Teams** (the first
Microsoft 365 app), **Outlook / OWA** (the second MS app), **OneDrive** (the
third MS app — Phase 1+2 complete: shell plumbing, native/classic switching,
pin injection across 3 layouts), **OneNote** (the fourth MS app — Phase 1+2
complete: pin injection into the cross-origin editor OOPIF via `webFrameMain`,
child-window pin forwarding, SharePoint team notebook resolution via
`/sites/{id}/onenote`), **Confluence** (Atlassian wiki — pin in the
Edit/Share/Actions toolbar on detail views + inline pins on sidebar page links;
uses `ajs-page-id` meta tag for real page IDs, URL slug for clean titles), and
**Jira** (Atlassian issue tracker — pin in the Watch/Share/Actions toolbar on
issue detail views + inline pins on `/browse/KEY-NNN` links in board/backlog
views). **GitHub** native pane is wired (shell plumbing, session, navigation
policy, pin forwarding) but pin injection is not yet implemented — parked for
a future pass.

They differ in fundamental ways — Teams broke several assumptions baked into
the Slack design (URL routing, `innerHTML`, no CSP). Outlook re-uses the Teams
MS-app fixes but, unlike Teams, DOES use real URL routing. OneDrive and OneNote
are the first apps whose native migration is read/browse-focused with no HITL —
files open in child windows so the file list stays intact. Confluence and Jira
are Atlassian apps — no Trusted Types CSP, no UA block, real URL routing, and
a shared `atlassian.net` domain. **Known gap:** the M17 cross-app nav guard
(`onCrossAppNav`) is not yet wired for Confluence/Jira — clicking the Atlassian
waffle app-switcher _inside_ the pane (rather than the dock icons) can load the
wrong app in the wrong view. Low-impact in practice; parked for a future pass.

**If you are adding another Microsoft app, read the "Microsoft 365 Apps —
Hard-Won Learnings" section FIRST** — most of what bit us in Teams will bite you
again, and the fixes are already in `shell/main.js`.

> **Native panes are the DEFAULT** (in the Electron shell) for all supported
> apps. Classic UIs are the fallback, selected only by an explicit
> `*_pane_mode="classic"` in config. See "Pane mode defaults" below.

---

## Architecture (Consensus Design)

Three reviewers (dev-correctness, regression-risk, architecture) agreed on
this model. The key principle: **inject once, self-manage, never re-inject.**

### Data Flow

```
┌─ Shell (main.js, main process) ──────────────────────────────────────┐
│                                                                       │
│  URL Watcher (750ms)                                                  │
│    ├─ dispatchCtx(ctx)  ──→ Gator page: CustomEvent('slack:ctx')     │
│    └─ updateSlackCtx(ctx) ──→ Slack page: window.__gatorSetCtx(ctx)   │
│                                                                       │
│  Pin Forwarder (300ms)                                                │
│    └─ polls Slack: window.__gatorPinCtx                               │
│       └─ if set: inserts .pin-ref-chip in Gator's #chat-input         │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘

┌─ Slack Page (injected module, runs in Slack's renderer) ─────────────┐
│                                                                       │
│  Injected ONCE on dom-ready (sentinel: __gatorPinModule)              │
│                                                                       │
│  MutationObserver (debounced via rAF) + setInterval(2s safety net)   │
│    └─ scanAll()                                                       │
│       ├─ scanHeader()    → idempotent: only acts if missing/misplaced │
│       └─ scanMessages()  → idempotent: only injects if missing        │
│                                                                       │
│  Button clicks set: window.__gatorPinCtx = {channel, thread_ts, ...} │
│  (NOT __gatorSetCtx — that's for context updates only)                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### Critical Separations (per regression review)

| Channel                                | Purpose                                        | Direction                   |
| -------------------------------------- | ---------------------------------------------- | --------------------------- |
| `dispatchCtx()`                        | Cross-page context → Gator's `CustomEvent`     | Shell → Gator page          |
| `updateSlackCtx()` / `__gatorSetCtx()` | In-app context update (tooltip, click context) | Shell → Slack page          |
| `window.__gatorPinCtx`                 | Pin click → Gator composer chip                | Slack page → Shell (polled) |

**Never conflate these.** `__gatorSetCtx` is for live context (channel/thread
the user is viewing). `__gatorPinCtx` is for what the user clicked to pin
(specific message, channel, or thread). They serve different purposes.

---

## Implementation Details

### 1. Single Injection (dom-ready + sentinel)

```js
slackView.webContents.on('dom-ready', () => {
  slackView.webContents.executeJavaScript(`
    (function() {
      if (window.__gatorPinModule) return;  // sentinel — prevents double-inject
      window.__gatorPinModule = true;
      // ... module code ...
    })();
  `);
});
```

- Fires on initial load AND hard reloads (page context wiped → sentinel gone)
- Does NOT fire on SPA navigation (URL changes via `history.pushState`)
- The in-page `MutationObserver` handles SPA navigation naturally

### 2. Idempotent Header Scan

```js
function scanHeader() {
  var actionsEl = document.querySelector('.p-view_header__actions, .p-flexpane_header__primary');
  if (!actionsEl) return;
  var existing = document.getElementById('__gator_pin_header');
  // Already correctly placed? Done — don't touch (prevents flicker/hover loss).
  if (existing && existing.parentNode === actionsEl) return;
  // Missing or stale — clean duplicates, create one.
  document.querySelectorAll('#__gator_pin_header').forEach((el) => el.remove());
  // ... create + insert ...
}
```

Key: **only touch the DOM when the button is missing or misplaced.** This
prevents:

- Flicker (remove+recreate every cycle)
- Hover state loss
- Focus loss
- Click animation interruption

### 3. Debounced MutationObserver

```js
var scanQueued = false;
var obs = new MutationObserver(function () {
  if (scanQueued) return;
  scanQueued = true;
  requestAnimationFrame(function () {
    scanQueued = false;
    scanAll();
  });
});
obs.observe(document.body, { childList: true, subtree: true });
```

- Coalesces burst mutations (Slack's DOM mutates constantly) into one scan per frame
- Prevents scroll jank on large channels
- `setInterval(scanAll, 2000)` as a safety net for anything the observer misses

### 4. Live Context at Click Time

```js
function headerClick(b) {
  var ctx = window.__gatorCurrentCtx || currentCtx;  // LIVE, not closure
  var isInThread = !!document.querySelector('.p-flexpane_header__primary');
  // ... extract thread_ts from URL if in thread view ...
  window.__gatorPinCtx = { channel: ctx.channel, thread_ts: threadTs, ... };
}
```

The click handler reads `window.__gatorCurrentCtx` (kept updated by
`__gatorSetCtx`) at click time — NOT the closure-captured `ctx` from injection
time. This handles thread side-panels that open without URL changes.

### 5. Pin Forwarding (Shell → Gator)

```js
// Shell polls Slack every 300ms for __gatorPinCtx
setInterval(() => {
  slackView.webContents.executeJavaScript('window.__gatorPinCtx || null').then((ctx) => {
    if (!ctx) return;
    slackView.webContents.executeJavaScript('window.__gatorPinCtx = null;');
    // Insert .pin-ref-chip in Gator's #chat-input
    gatorView.webContents.executeJavaScript(`...chip creation...`);
    // ALSO persist to /api/context/pin so it shows in the pin orb
    // and works with Shift+{ — MUST include context_id (the renderer's
    // live _activeTabId) or the pin lands in a shared "default" bucket
    // and leaks across tabs (see §6, Pin Persistence).
    gatorView.webContents
      .executeJavaScript(
        'typeof _activeTabId !== "undefined" && _activeTabId ? _activeTabId : "default"',
      )
      .then((activeTabId) => {
        http.request('/api/context/pin', {
          method: 'POST',
          body: { source, id, label, context_id: activeTabId },
        });
      });
    // After persist confirms, refresh the pin orb:
    gatorView.webContents.executeJavaScript('_refreshPinOrb(true)');
  });
}, 300);
```

The pin chip uses the existing contract: `dataset.pinSource='slack'`,
`dataset.pinId='channel:thread_ts:msg_ts'`. Gator's send handler reads these
at `app.js:6653`.

### 6. Pin Persistence (Pin Orb + Shift+{)

Pin clicks do TWO things:

1. **Immediate**: insert a `.pin-ref-chip` in the composer (one-shot, for the current message)
2. **Persistent**: POST to `/api/context/pin` (saved to disk, shows in pin orb badge, works with Shift+{)

**Per-tab scoping (fixed — do not regress this):** an earlier version of this
forwarder omitted `context_id` from the POST body, so every shell-mode Slack
pin landed in a shared `context_id="default"` bucket. The renderer then had a
compensating hack in `_refreshPinOrb()` / `openPinDropdown()` that merged the
`"default"` bucket into _every_ open tab's pin list — which is what made a
Slack pin appear "pinned" on every tab instead of just the tab that was active
when it was clicked. Both sides of that bug are fixed:

- `shell/main.js`'s pin forwarder now reads the renderer's live active tab id
  before persisting, via `gatorView.webContents.executeJavaScript('typeof
_activeTabId !== "undefined" && _activeTabId ? _activeTabId : "default"')`,
  and includes it as `context_id` in the POST body.
- The `"default"`-bucket merge hack was removed from `web/static/app.js`
  (`openPinDropdown()` and `_refreshPinOrb()`) — pins are now looked up only
  for the actual active tab, exactly like every other pin source (OneNote,
  Teams, OneDrive, etc.).

If you add pin support for a new app, **always thread the active tab's
`context_id` through the POST** — do not fall back to a shared `"default"`
bucket, and do not reintroduce a cross-tab merge in the renderer to paper over
a missing `context_id`.

**Endpoint** (added in `web/routes/onenote.py`, model `ContextPinRequest`):

```
POST /api/context/pin
Body: { "source": "slack", "id": "C06R5U37KBK:1783978133.468829", "label": "ext-amd-cohere (thread)", "context_id": "39ole7b0" }
```

Note: this route is defined twice in `onenote.py` (once with the
`ContextPinRequest` Pydantic model, once as `context_add_pin` taking a raw
`dict`) — Starlette matches by registration order, so the **first** definition
(the Pydantic one, which already has a `context_id: str = "default"` field)
is the one that actually runs. Both behave the same for our purposes, but if
you touch this route, be aware the second definition is dead code for this
path today.

### 7. URL Fallback for Context

The click handlers read `window.__gatorCurrentCtx` (set by `__gatorSetCtx`) as
primary context. But if the module was injected before `updateSlackCtx` ran
(race condition), `__gatorCurrentCtx` is null. The click handlers fall back to
parsing `location.href` directly:

```js
var ctx = window.__gatorCurrentCtx || currentCtx;
if (!ctx || !ctx.channel) {
  // Fallback: parse URL directly.
  var parts = location.href.split('/').filter(function (p) {
    return p;
  });
  if (parts.length >= 3 && parts[0] === 'client') {
    ctx = { team: parts[1], channel: parts[2], thread_ts: null };
  }
}
```

### 8. Thread Context Extraction

Thread side-panels open WITHOUT changing the URL. The `thread_ts` is extracted
from the DOM via `[data-thread-ts]` attribute:

```js
if (isInThread && !threadTs) {
  var threadEl = document.querySelector('[data-thread-ts]');
  if (threadEl) threadTs = threadEl.getAttribute('data-thread-ts');
}
```

### 9. User ID Resolution

Slack API returns user IDs (e.g., `U0AB29R621L`) in message data. The backend
resolves these to display names before returning to the agent:

- `_resolve_user(user_id)` in `web/skills/slack/tools.py` — cached, calls `users.info`
- `_resolve_users_in_messages(messages)` — applies resolution to a list of messages
- Applied in `slack_read_channel`, `slack_read_thread`, and `slack_search_public_and_private`

### 10. HITL Compose Flow

When the agent drafts a Slack message:

1. `slack_send_message` tool creates a draft via `_drafts.create_draft()`
2. Gator's `_injectDraftApprovalCard()` shows a draft card with an editable `<textarea>`
3. User edits text, clicks "I approve to send"
4. Frontend POSTs to `/api/drafts/{id}/approve` with `{ edited_message: "..." }`
5. Backend applies edits, calls `_slack_web_api("chat.postMessage", ...)`
6. In shell mode, the Slack tile stays open (no `closeThirdPane()`)
7. Duplicate draft cards prevented (notification stream checks for existing `draft_id`)
8. "Edit in Slack" link hidden for Slack drafts (no classic third pane in shell mode)

### 11. Pin Chip Text Format

When a pin chip is submitted (user sends a message), the text representation
includes the source and ID so the agent can resolve it:

```
[Pin: slack:C06R5U37KBK:1783978133.468829]
```

The display HTML shows a nice chip (Slack icon + label), but the agent receives
the machine-readable `[Pin: source:id]` format. This is handled in
`_getNodeInputText()` at `app.js:4861`.

### 12. Canonical Chip Insertion — ONE builder for ALL pin paths

There are THREE code paths that insert a `.pin-ref-chip` into the composer, and
they MUST produce identical chips or users notice the difference (we shipped a
bug where shell-inserted chips had an extra `×` remove-button and forced a new
line, while Shift+{ chips did not):

1. **Shift+{ dropdown** → `commitPinMention()` in `app.js`.
2. **Shell pin forwarder** (Slack/Teams pin button) → the shell calls a Gator
   page function via `executeJavaScript`.
3. **Pin orb "Insert into chat" (✦) button** → the orb card handler.

**Single source of truth:** `buildPinChipEl(pin)` builds the chip element
(icon via `_pinSourceIcon` + label, **no X button**), and
`window.insertPinChipAtCaret(pin)` inserts it at the caret **without** a
trailing `&nbsp;`/text node (which pushes a new line) and places the caret
right after the chip. `commitPinMention`, the shell forwarder, and the orb
✦ button ALL call these. Never hand-build chip markup in a new insertion path
— call `window.insertPinChipAtCaret({ source, id, label })`.

Pitfalls that caused the divergence bug (do not reintroduce):

- Appending `document.createTextNode('\u00A0')` after the chip → forces a
  visible line/space break in the contenteditable.
- Adding a custom `<button>×</button>` inside the chip → the shell path had
  this; the canonical chip has no X (removal is via editing/backspace).
- Using an emoji icon instead of `_pinSourceIcon(source)` → inconsistent glyph.

---

## Slack-Specific Selectors

| Target                          | Selector                                                                   | Notes                            |
| ------------------------------- | -------------------------------------------------------------------------- | -------------------------------- |
| Channel header actions          | `.p-view_header__actions`                                                  | Channels + DMs                   |
| Thread header actions           | `.p-flexpane_header__primary`                                              | Thread side-panel                |
| "More channel actions" button   | `aria-label` matches `/^more (channel\|conversation\|thread) actions/i`    | Header pin inserts before this   |
| "More actions" button (message) | `aria-label` matches `/^more actions/i`                                    | Message pin inserts before this  |
| Message timestamp               | `[data-ts]` or `[data-item-key]` on message container                      | Used for message pin ID          |
| Message text                    | `[data-testid="message_text"]`, `.c-message__body`, `.p-rich_text_section` | Used for pin label               |
| Sidebar (to exclude)            | `.p-channel_sidebar`, `.p-workspace__sidebar`                              | Skip "More actions" buttons here |

## Teams Selectors (originally confirmed via a Teams feasibility spike; now live in shell/main.js)

Teams uses Microsoft's own `data-tid` test-id vocabulary — more stable than Slack's
mutating CSS class names. All content is in the top-level document (no iframes).
Teams **never updates `location.href`** on chat/channel navigation — all context must
come from the DOM via `MutationObserver`, not a URL watcher.

| Target                        | Selector                                                                | Notes                                                                                                                                    |
| ----------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Header pin insertion point    | `button[data-tid="chat-header-more-menu-trigger"]`                      | Pin inserts before this button; its `parentNode` is the actions container                                                                |
| Chat/channel title            | `h2[data-tid="chat-title"]`                                             | `textContent` used as pin label                                                                                                          |
| Gator hide/show insertion     | Same container as header pin                                            | Inserted after pin button                                                                                                                |
| Message container             | `div[data-tid="chat-pane-item"]`                                        | One per rendered message                                                                                                                 |
| Message "more actions"        | `button[data-tid="message-actions-menu-hidden-button"]`                 | Message pin inserts before this                                                                                                          |
| Message ID                    | `[data-mid]` on descendant of `chat-pane-item`                          | 13-digit epoch-ms, matches Skype/chatsvc backend format exactly                                                                          |
| Message timestamp             | `[datetime]` on descendant of `chat-pane-item`                          | ISO datetime string                                                                                                                      |
| Message list scroll container | `div[data-tid="message-pane-list-viewport"]`                            | Scope `querySelectorAll` here for message scan                                                                                           |
| Thread/chat ID                | `[data-track-thread-id]` on header/participant elements                 | Format: `19:{guid}@unq.gbl.spaces` — maps directly to existing backend chat IDs                                                          |
| Participant MRI               | `[data-person-mri]`                                                     | Format: `8:orgid:{guid}` — maps directly to existing backend MRI format                                                                  |
| Message action bar (hover)    | `div[role="toolbar"]` containing `button[data-tid^="message-actions-"]` | The floating per-message react/reply/more bar. **Pin appends here** (Slack-parity placement), not next to the hidden more-actions button |
| Message text (for pin label)  | `div[id="content-<mid>"]`                                               | `innerText` → pin label, like Slack. Falls back to chat title for attachment-only/system messages                                        |
| Compose box                   | `div[data-tid="ckeditor"]`                                              | Teams uses CKEditor — do not inject into or simulate clicks on this                                                                      |
| Notifications permission      | Requested automatically on load                                         | Grant in `setPermissionRequestHandler` (`notifications`)                                                                                 |

## OneDrive Selectors (confirmed via live DOM inspection — shell/main.js)

OneDrive for Business renders three distinct list/tile layouts. `scanRows()`
in the OneDrive pin module handles all three; each has its own row selector,
name-cell selector, and filename extraction path. The same `filesRow` row
class and `field-LinkFilename` name cell are shared by My Files, shared-library
folder drill-downs (`sharepoint.com/shared?id=...`), and subfolders within
them — Layout 1 covers all three.

| Target | Selector | Notes |
|---|---|---|
| **Layout 1** row (My Files, shared-folder drill-down, subfolder) | `div[class*="filesRow"]` (skip rows with `header` in class) | Same class across all three surfaces |
| Layout 1 name cell | `[data-automationid="field-LinkFilename"]` | Inside the row |
| Layout 1 filename element | `[data-id="heroField"]` (read `title` attr) | **NOT** `a`/`button`/`[role="link"]` — those match an unrelated "More Actions" hero button with empty text. See M24. |
| **Layout 2** row (Home "Recent" list) | `[data-automationid="field-name"]` | Different structure from Layout 1 |
| Layout 2 filename element | `[class*="nameCellTop"]` | Read direct text nodes only (not child-element text) to avoid timestamp/author noise |
| **Layout 3** tile (Home "For you" tiles) | `[class*="itemTile_"]` | Tile grid, not a list row |
| Layout 3 filename element | `[class*="itemTileTitle"]` | Direct text nodes, fallback to `textContent` |
| Item ID (Graph-resolvable) | `data-actions` JSON `"itemKey":"<token>"` OR `data-automationid="row-SPO@{guid},{itemKey}"` (take part after comma) | Must pass `_isGraphItemId` (base32-ish, starts with `01`, >=22 chars). Bare `SPO@{guid}` is a site id, NOT a file id — Graph rejects with 400. |
| Header row (to skip) | `[data-automationid="row-header"]` or class contains `header` | Skipped via `/header/i.test(row.className)` |
| Folder SPA navigation (stays in-pane) | `/my`, `/personal/.../Documents/...` | Does NOT match `fileOpenPattern` (M19) — folder browsing stays in the pane |
| File open (child window) | `Doc.aspx`, `WopiFrame.aspx`, `onenoteframe.aspx`, `?action=edit\|view\|embedview` | Matches `fileOpenPattern` (M19) — opens in a closeable child window, pane stays on the list |

**Filename extraction order (Layout 1):**
1. `[data-id="heroField"]` → `title` attribute (cleanest — the raw filename)
2. `a, button, [role="link"]` → `textContent` (legacy fallback)
3. `nameCell.textContent` → stripped by timestamp regex (last resort)

The heroField `title` is the load-bearing source — without it, every row on My
Files and folder drill-downs is skipped because the link/button selector finds
the wrong element. See M24 for the full bug writeup.

---

## Microsoft 365 Apps — Hard-Won Learnings (READ FIRST for Outlook/next MS app)

Teams was the first Microsoft app embedded in the shell. It violated almost
every assumption the Slack implementation was built on. Everything below is
already handled in `shell/main.js` / `shell/navigation-policy.js` /
`shell/media-permissions.js` for Teams — reuse those helpers rather than
re-deriving. Expect Outlook (`outlook.office.com`) to hit the same wall on
each point.

### M1. Entry URL: bare domain may hard-redirect to an error wall

`https://teams.microsoft.com` (bare) now redirects to
`https://teams.microsoft.com/error/eoa` ("Classic Teams is no longer
available"). The real client is at **`/v2`**. Always test the bare domain
first and follow where it sends a real browser — do not assume the bare
domain is the app entry point. (`TEAMS_URL = 'https://teams.microsoft.com/v2'`.)

### M2. User-Agent: MS apps BLOCK "Electron" — strip it, don't append

This is the **opposite** of Slack. Slack needed a `Slack/<ver>` desktop token
_appended_ (though even that turned out to be an inert no-op that was actually
load-bearing — see M2a). Teams' `/v2` client **hard-blocks any UA containing
the literal substring `"Electron"`** and redirects to `/error/eoa`. Confirmed
via A/B testing on clean session partitions:

- Default Electron UA (has `gator-shell/x.x.x ... Electron/43.2.0`) → blocked.
- Remove only the app-name token, keep `Electron/<ver>` → still blocked.
- Remove BOTH the app-name and `Electron/<ver>` tokens (so it matches the
  bundled Chromium's plain `Chrome/<ver>` UA) → loads correctly.

Fix: `buildNonElectronUA(session)` in `shell/main.js` strips the app-name and
`Electron/<ver>` tokens from the session's own `getUserAgent()` at runtime
(self-adjusting across Electron/Chromium bumps — never hardcode a Chrome
version). This is undocumented and could tighten further (Client Hints,
`navigator.webdriver`) — re-verify on each Teams-pane regression pass.

### M2a. `session.userAgent = x` is a silent no-op — use `setUserAgent()`

`Session` has **no `userAgent` property setter** — only `getUserAgent()` /
`setUserAgent()`. `slackSession.userAgent = ...` silently sets an inert JS
property and never changes the network header. The original Slack code did
this, so Slack always ran with the default (browser-mode) UA — which is what
actually worked. When "fixed" to really apply `Slack/<ver>`, Slack rendered
blank (see M6). Lesson: always use `setUserAgent()`, and be suspicious of any
UA "spoof" that was silently doing nothing.

### M3. No URL routing — context is DOM-only

Slack updates `location.href` on channel/thread navigation, so Slack has a
750ms URL watcher + `parseSlackUrl()`. **Teams `/v2` never changes
`location.href`** when you switch chats/channels (confirmed via both
`webContents.getURL()` polling and an in-page `location.href` probe — both stay
at `/v2/` forever). Consequences for any MS app:

- There is **no `parseTeamsUrl()`** and the shell URL watcher does nothing for
  Teams. All context must come from the DOM via the `MutationObserver`.
- `readTeamsCtx()` reads `[data-track-thread-id]` (chat/thread id) and
  `h2[data-tid="chat-title"]` (label) from the DOM on every header scan.
- Verify this for Outlook before writing any URL parser — OWA may or may not
  use hash/path routing.

### M4. Trusted Types CSP blocks `innerHTML` AND `DOMParser` AND custom policies

Teams enforces `require-trusted-types-for 'script'` so strictly that **every
string→DOM path is rejected**:

- `el.innerHTML = '<svg>...'` → `This document requires 'TrustedHTML' assignment`.
- `new DOMParser().parseFromString(html, ...)` → same error (yes, even
  DOMParser).
- `trustedTypes.createPolicy('gatorPins', ...)` → blocked by Teams' policy
  allowlist; the policy's output is still rejected.

This silently killed the **entire scan loop** (the throw in `buildGatorBtn`
propagated up through `scanAll`, so no pins appeared and `currentCtx` never
updated) — and it threw on every interval tick, so it looked like the observer
was dead. **Symptom to recognize:** buttons are empty green circles / never
appear, and `window.__gatorCurrentCtx` stays at its initial empty value.

Fix: build every icon as real SVG DOM nodes via `document.createElementNS`
(SVG namespace) — no HTML string ever touches the DOM, so Trusted Types never
applies. See `buildSvg()` / `setIcon()` and the `*_ICON` node specs in
`shell/main.js`. Slack still uses plain `innerHTML` (no CSP there); the icon
node-spec approach works everywhere, so prefer it for any new app.

### M5. Corporate SSO / Okta FastPass — navigation + local-network + permissions

MS apps federate to the tenant's own IdP, which means three separate things
must all be permissive, and none of them can be hardcoded per tenant:

- **Navigation:** SSO redirect chains hop through arbitrary tenant-owned
  domains (Okta, ADFS, Ping, custom STS, Duo). `will-navigate` must **allow all
  https hops** (only block non-https custom-protocol handoffs). See
  `shell/navigation-policy.js` `applyNavigationPolicy()` — generic, reused by
  Slack and Teams, driven by an app's `homeHosts` only to decide
  external-link-vs-in-app for `window.open`.
- **Local Network Access:** Okta FastPass (and Duo/Ping variants) talk to an
  on-device helper over loopback. Chromium 130+ blocks this by default →
  "The browser is blocking communication with Okta Verify" and sign-in hangs.
  Fix: `app.commandLine.appendSwitch('disable-features',
'LocalNetworkAccessChecks,LocalNetworkAccessPermissionPrompt,...')` **before**
  app-ready, AND grant `local-network-access` in the permission handlers.
- **Permissions:** grant `local-network-access`, `notifications`, `clipboard-*`,
  `idle-detection` for the app's session (see `AUTH_FLOW_PERMISSIONS` in
  `shell/media-permissions.js`). Denying any of these can silently break MFA.

**Session persistence:** once signed in, `persist:teams` remembers it forever
(like `persist:slack`) — no re-auth on restart. Use a distinct partition per
app (`persist:outlook`, etc.).

### M6. Inactive-view hiding: use `View.setVisible(false)`, never off-screen/1px

With one external view (Slack-only) the shell parked the hidden view at
`x:0 width:1`. With two views this broke: parking a `WebContentsView`
off-screen (`x > windowWidth`) or at a 1px sliver makes Chromium set
`visibilityState:hidden` and **stop compositing** — the view renders blank
white when brought back. Fix: hide the inactive external view with
`view.setVisible(false)` (real API on `View`, which `WebContentsView` extends)
and `setBackgroundThrottling(false)` on each view. See `layout()`.

### M7. Media (calls/meetings) works — permissions are shared infra

Mic/camera/screen-share for Teams calls (and Slack huddles) go through
`shell/media-permissions.js`, origin-allowlisted per session. Screen share uses
`setDisplayMediaRequestHandler` + `desktopCapturer` with the OS system picker
(never auto-select a source). This was verified live (a real Teams call
worked). Outlook has no call surface, so it won't need the media grants — but
it will still need the M5 SSO/permission grants.

### M8. Native-mode HITL replaces the classic compose pane

In shell mode the classic third-pane compose UI is hidden (the native app
fills that space). The `<app>-compose` pane signal must instead render an
editable `_injectDraftApprovalCard()` in Gator chat, and the backend
`approve_draft` must route the `<app>-message` dtype to the app's real send
API. For Teams: `_tool_teams_open_compose` always creates a draft; `app.js`
branches on `window.gatorShell.isShell` to pick card-vs-classic-pane; the
approve handler keeps the native pane open (does not `closeThirdPane`). Mirror
this exactly for Outlook.

### M9. Button sizing: match the host app's chrome

Slack's default is a 28px circle. Teams' Fluent-UI header/action buttons are
smaller/denser, so Teams uses `TEAMS_BTN_SIZE = 24` (header) and
`TEAMS_MSG_BTN_SIZE = 28` (message bar), with explicit `marginLeft` between the
pin and hide/show buttons. Size the injected buttons to the host app's native
buttons rather than reusing Slack's constants blind.

### M10. Message-pin placement: append into the hover ACTION TOOLBAR

For Teams, the visible per-message action bar is a lazily-rendered
`div[role="toolbar"]` containing `button[data-tid^="message-actions-"]`
(like/heart/laugh/reply/more). Append the pin there (Slack-parity placement) —
NOT next to the hidden `message-actions-menu-hidden-button` (which is an
off-screen a11y trigger, so the pin ends up misplaced). Scope `scanMessages()`
to that toolbar and use its `data-mid` for the message id + `div[id=content-<mid>]`
innerText for the label.

### M11. Message-pin CONTEXT must capture the ACTIVE conversation id

Bug we hit: `document.querySelector('[data-track-thread-id]')` grabbed the FIRST
match in the DOM (often a stale sidebar element), so pinning a DM produced a
"channel" pin with the wrong id, and message pins sometimes got an empty
channel (`:1785…`). Fix: scope the thread-id read to the active conversation
region (header / message-pane), and classify id shape explicitly:

- `19:{guid}_{guid}@unq.gbl.spaces` → **1:1 DM**
- `19:{guid}@thread.v2` (or `.tacv2`) → **group chat / channel**
  `@thread.v2` is NOT necessarily a channel — check the id shape, don't assume.

### M12. Deep-link "Open" navigation: anchor-CLICK, not location.assign

To make the pin-orb "Open" button jump the native pane to the pinned item:

- **Slack** uses real URL routing — `webContents.loadURL(deepLink)` works. The
  pin id is `channel[:thread_ts]`; the workspace/team id is read from the Slack
  view's own live `/client/<TEAM>/…` URL (pins don't store it) to build
  `https://app.slack.com/client/<team>/<channel>[/thread/<channel>-<ts>]`.
  See `slack-pane:navigate-pin`.
- **Teams** does NOT navigate via `location.assign`/`loadURL` on the `/l/message`
  deep link — those are ignored by the already-running `/v2` SPA. The ONLY way
  that works: inject an `<a href="/l/message/<threadId>/<msgId>?context=…">` into
  the Teams page and dispatch a real click sequence
  (`pointerdown/mousedown/mouseup/click`). That routes through Teams' launcher
  handoff (`teams.microsoft.com/dl/launcher/…`), which then navigates the app.
  The launcher may show a "Use the web app instead" interstitial (esp. for DMs)
  — a `did-finish-load` handler on the Teams webContents detects the
  `/dl/launcher/` URL and auto-clicks it. The deep-link format matches the
  classic forward-message link (`web/routes/teams.py _extract_forward_context`):
  `/l/message/<threadId>/<msgId>?context={"contextType":"chat","oid":"8:orgid:<me>"}`.
  Works for group chats, channels, AND DMs; takes ~12-16s due to the handoff.
  See `teams-pane:navigate-pin`.
- **Outlook / OneDrive / OneNote** all use real URL routing (like Slack), so
  deep-link Open is a simple `webContents.loadURL(webUrl)`. The pin's web URL is
  read from `p.meta.web_url` (OneDrive) or `p.meta.web_url`/`p.meta.url`
  (OneNote). If the pin lacks a web URL (some OneDrive folder-browse pins and
  all OneNote classic pins store only the Graph item id + notebook/section),
  the renderer resolves it first via `GET /api/onedrive/items/<id>` (returns
  `web_url` from Graph's `webUrl`) or `GET /api/onenote/pages/<id>` (returns
  `url` from Graph's `links.oneNoteWebUrl.href`), then passes it to
  `navigateOutlookPin` / `navigateOneDrivePin` / `navigateOneNotePin`. See the
  `onedrive-pane:navigate-pin` and `onenote-pane:navigate-pin` IPC handlers.

### M13. In-body mention resolution (not just the sender)

Resolving only the message SENDER leaves raw ids in the body (agent surfaced
`Hi @U0ARYKYUC67 …`). Resolve `<@UID>` / `<@UID|handle>` mentions inside the
message TEXT too. For Slack: `_resolve_mentions_in_text()` in
`web/skills/slack/tools.py`, applied inside `_resolve_users_in_messages` for
read_channel/read_thread/search. For Outlook/Teams, apply the equivalent to any
message body the agent tools return.

### M14. Dev server hang ≠ pin bug (`--reload` watcher)

Symptom: pins stop persisting (chip inserts, `GATOR [app]: ok`, but no
`PIN PERSIST OK` — the POST times out). Cause is usually NOT the pin code — the
uvicorn `--reload` file watcher gets stuck mid hot-reload (esp. with duplicate
server instances on the same port), so the backend stops responding. `dev.ps1`
has a watchdog (kills+restarts uvicorn if a reload stalls >45s). If pins break:
first check the backend is alive (`GET /api/config`), and kill stale python
processes (`Get-Process python | Stop-Process -Force`) before restarting so you
don't stack two servers on one port.

### M15. Slack "opens in a new tab" — use the INVERSE popup allowlist, not an entry-URL allowlist

Symptom: after signing into Slack (esp. on an **Enterprise Grid** org like AMD),
the workspace opens in a stray second window/tab instead of loading in the
Slack pane.

Root cause: Slack enters a workspace via a `window.open()` whose URL is
**per-workspace and unpredictable** — we observed, at different steps:
`app.slack.com/client/<team>`, `<team>.slack.com/messages` (e.g.
`xilinxexternal.slack.com/messages`), `<org>.enterprise.slack.com/`,
`slack.com/get-started`, `/ssb/`. The original fix used
`sameHostNavPattern: /\/client\//` — an **allowlist of navigation URLs** — which
only caught `/client/` and missed every other entry URL. You cannot enumerate
these: every workspace has its own subdomain, and the entry path varies by grid
config. (Confirmed via a `setWindowOpenHandler` debug log: the escaping open was
`https://xilinxexternal.slack.com/messages`, `auth=false home=true`, but the
`/client/` pattern didn't match it.)

Fix — **invert the rule**: instead of an allowlist of _navigation_ URLs (open-ended,
grows with every workspace), use an allowlist of _genuine pop-outs_ (small,
stable). `applyNavigationPolicy` gains `sameHostPopupPattern`: when set, **all**
same-host, non-auth, non-blank `window.open()`s load INTO the pane by default,
and only URLs matching the popup pattern get their own window. Slack sets:

```js
applyNavigationPolicy(slackView, {
  name: 'slack',
  homeHosts: ['slack.com'],
  sameHostPopupPattern: /\/huddle\/|\/call\/|\/files\/|\/archives\/.*\/files\/|\/print\//,
});
```

So any workspace-entry navigation — current or future, any subdomain — stays in
the pane, while huddles, calls, and file/image previews still pop out. The old
`sameHostNavPattern` (narrow allowlist) is still supported for apps that only
need to catch a couple of known nav URLs; Slack now uses the inverse model.

Guardrails still apply in both models: `AUTH_RE` URLs (`/signin`, `/login`,
Okta/SAML/SSO hops) always get their own window (part of the auth flow), and
non-same-host links go to the system browser.

**Debugging tip:** if a stray tab appears, temporarily log every
`setWindowOpenHandler` decision (`url`, `isBlank`, `AUTH_RE.test(url)`,
`_hostMatches`, pattern result) to a file — the escaping URL + which flag let it
through pinpoints the fix in one repro. Remove the log after.

### M16. Hide/show is GLOBAL (dock logo), but gated by `GATOR_NATIVE_PANE_TYPES`

Hide/show Gator is NOT an injected per-app button anymore — it's the 3-state
dock-home logo (`GatorChat` in `web/static/app.js`), shared across ALL native
panes. Click = hide (squeeze Gator's view to the dock sliver), click = show.

**Gotcha that bit us on OneDrive (and would have on OneNote):** `GatorChat`
picks its mechanism via `_isNativePane()`, which checks `GATOR_NATIVE_PANE_TYPES`
— an **allowlist array** in `app.js`:

```js
const GATOR_NATIVE_PANE_TYPES = ['slack', 'teams', 'email', 'onedrive', 'onenote'];
```

If a new native app's `tpState.type` is NOT in this array, `_isNativePane()`
returns false → `GatorChat._applyForCurrentPane()` falls back to the CSS-expand
mechanism (growing `#third-pane`), which is a **no-op for native panes** (their
`#third-pane` is `.hidden` — the real app renders in its own `WebContentsView`).
Symptom: the dock logo's hide/show click does nothing with that app open, even
though tiling/switching/SSO all work.

**Fix:** when you add a native pane, add its `tpState.type` to
`GATOR_NATIVE_PANE_TYPES` in `app.js`. (The type is the string passed to
`openThirdPane('<type>')` — e.g. `'onedrive'`, `'onenote'`.) This is the single
load-bearing line; without it hide/show silently no-ops for that app. The
`<app>` must also be added to the `openDrawer`/`closeDrawer` hide+restore
branches in `app.js` (Settings drawer) so opening Settings while that app is
tiled correctly hides and restores it.

The classic compose-pane header button (`#tp-detail-header` maximize, rebranded
to Gator awake/sleeping via `_tpSyncExpandButton()`) is a SEPARATE affordance
for classic (non-native) panes only — native panes never render that header.

### M17. M365 app launcher (waffle) cross-app navigation guard

Outlook, OneDrive, and OneNote all share the M365 app launcher (waffle icon).
Clicking it navigates to a DIFFERENT app's URL **within the current
`WebContentsView`** — e.g. clicking "Outlook" from OneNote loads
`outlook.office.com/mail/` inside the OneNote view. This breaks pinning (wrong
source/forwarder), deep-link Open (wrong pane), and HITL, because the shell
still thinks `activeExternalApp === 'onenote'`.

**Fix:** `applyNavigationPolicy` gains an `onCrossAppNav(url) => boolean`
callback. It is called from **both** `will-navigate` AND `setWindowOpenHandler`
— BEFORE any navigation/loadURL/child-window happens, so there's no race. If
the callback returns `true`, the navigation is **blocked** (preventDefault /
deny) and the caller loads the URL in the correct app's view instead. Each M365
view passes `_makeCrossAppNavGuard(homeApp)` as `onCrossAppNav`, which:

1. `classifyM365App(url)` → which app does this URL belong to?
2. If same app or unknown → return `false` (allow the nav)
3. If different app → `correctView.webContents.loadURL(url)`, set
   `activeExternalApp = target`, `layout()`, sync renderer `tpState.type` via
   `openThirdPane(M365_PANE_TYPE[target])`, return `true` (block in this view)

**Why `will-navigate`/`setWindowOpenHandler`, NOT `did-navigate`:** the earlier
implementation used `did-navigate` (fires AFTER navigation already happened),
which was racy — the view had already navigated to the wrong app before the
redirect could fire, causing double-loads, child windows, and the classic pane
flashing through. `will-navigate` + `setWindowOpenHandler` block BEFORE the
nav, so the current view never leaves its home — the URL goes straight to the
correct view. `setWindowOpenHandler` is needed because the waffle often uses
`window.open` (not in-page navigation), which bypasses `will-navigate` entirely.

Teams is NOT affected (it never changes `location.href` — M3).

**`M365_PANE_TYPE` map (important):** the renderer's `tpState.type` for Outlook
is `'email'` (the skill id), NOT `'outlook'`. The cross-nav guard must use
`M365_PANE_TYPE[target]` when calling `openThirdPane()`, or the renderer falls
through to the classic email pane instead of the native Outlook tile.

**Classification rules** (`classifyM365App`):

- `outlook.office.com`/`outlook.cloud.microsoft` + `/mail` → `outlook`
- `teams.microsoft.com` → `teams`
- `onenote.com`/`onenote.cloud.microsoft` → `onenote`
- `onedrive.live.com`/`onedrive.cloud.microsoft` → `onedrive`
- `sharepoint.com` + `onedrive.aspx`/`/my` → `onedrive`; + `onenote` → `onenote`
- `office.com/launch/<app>` → that app
- `officeapps.live.com` (Office file editor) → `null` (NOT a cross-app switch —
  stays in whichever view opened the file)
- Ambiguous sharepoint paths (`Doc.aspx`, `SitePages`) → `null` (don't redirect
  — let it stay in the current view; false-redirecting a OneNote page opened
  from OneDrive is worse than not redirecting)

**Important:** do NOT classify `sharepoint.com` + `?source=waffle` as OneDrive —
both OneDrive AND OneNote land on a sharepoint waffle page, so that causes false
cross-app redirects (OneNote view redirected to OneDrive on every load). Only
classify by explicit path markers (`/my`, `onedrive.aspx`, `onenote`).

### M18. Dock-click "reload home" rescues users stuck on a foreign page

Because native panes are real browsers, users can navigate away from the app
(e.g. click an org logo in Outlook that goes to a corporate intranet). External
links (non-`homeHosts`) open in the system browser via `shell.openExternal`
(navigation-policy.js line 117) — that's correct behavior. But if the user
navigated the pane itself away (same-host link, SPA route), clicking the app's
dock icon used to be a **no-op** (the app was already `activeExternalApp`),
leaving the user stuck with no way back.

**Fix:** `external-pane:show` IPC handler (`shell/main.js`) now checks: if the
app is **already active**, reload its home URL (`view.webContents.loadURL(home)`
from `APP_HOME_URL[appName]`) instead of no-op-ing. So dock-click on an
already-active app = "take me home." This works for all 5 native apps. The
`openThirdPane('<type>')` native branch calls `show<App>()` unconditionally
(even when already active), so the dock-click path naturally hits this rescue.

### M19. File-open interception: files open in child windows, pane stays on list

**Problem:** `sameHostPopupPattern` (M15) loads file clicks in-pane — good for
folder navigation, but clicking a file (Word, Excel, PPT, PDF, OneNote) navigates
the pane to the Office viewer with no back button. Users get stuck.

**Fix:** `applyNavigationPolicy` gains a `fileOpenPattern` option — a RegExp
checked in **both** `will-navigate` AND `setWindowOpenHandler`. When a URL
matches (e.g. `Doc.aspx`, `WopiFrame.aspx`, `onenoteframe.aspx`,
`?action=edit`), the navigation is intercepted (`preventDefault` / `deny`) and
the URL opens in a new `BrowserWindow` sharing the same session partition
instead of navigating the pane. The pane stays on the folder/file list; the file
opens in a closeable child window — exactly how browsers handle file opens.

Folder SPA navigation (`/my`, `/personal/.../Documents/SubFolder`) does NOT match
the pattern, so browsing folders stays in-pane. Scalable: any app just passes
the pattern, zero per-app code needed.

OneDrive and OneNote pass:

```
fileOpenPattern: /Doc\.aspx|WopiFrame\.aspx|onenoteframe\.aspx|[\?&]action=(edit|view|embedview)/i
```

### M20. OneNote editor is a cross-origin OOPIF — inject via `webFrameMain`

**Problem:** OneNote's page list (where pin buttons go) lives inside a
**cross-origin iframe** (`onenote.officeapps.live.com/o/onenoteframe.aspx`)
embedded in the SharePoint `Doc.aspx` wrapper. Top-frame `executeJavaScript`
**cannot reach it** — the browser's same-origin policy blocks access. CDP's
`Target.setAutoAttach` confirmed the OOPIF exists as a separate target, but
that's a debugging tool, not an injection mechanism.

**Fix:** Electron's `webFrameMain` API (`webContents.mainFrame.framesInSubtree`)
exposes ALL frames including cross-origin OOPIFs from the **main process**
(privileged context, bypasses same-origin policy). Each `WebFrameMain` has its
own `executeJavaScript()` that runs in that frame's renderer context.

```js
const frames = onenoteView.webContents.mainFrame.framesInSubtree;
for (const fr of frames) {
  if (fr.url && /onenoteframe\.aspx/i.test(fr.url)) {
    fr.executeJavaScript(ONENOTE_PIN_MODULE);
  }
}
```

The pin module runs inside the OOPIF, targets `div.pageNode` (pages) and
`[role="treeitem"]` (sections), and sets `window.__gatorPinCtx` in the OOPIF's
context. The pin forwarder reads from the OOPIF frame via the same
`framesInSubtree` walk (not the top frame's `__gatorPinCtx`).

When OneNote notebooks open in child windows (M19), the same injection runs on
the child `BrowserWindow`'s `webContents` via the `onChildWindow` callback
(see M21).

### M21. `onChildWindow` callback — inject into child windows generically

When `fileOpenPattern` opens a child `BrowserWindow`, modules (pins, nav buttons)
need to run there too. `applyNavigationPolicy` gains an `onChildWindow(child, url)`
callback — called after a child window is created (both from `will-navigate`
fileOpenPattern and `setWindowOpenHandler` allow). The caller wires pin injection

- any other modules to the child window's `dom-ready` / `did-frame-navigate` /
  `frame-created` + a periodic sweep.

For OneNote: `onChildWindow` tracks the child in a `Set`, injects
`ONENOTE_PIN_MODULE` + `M365_NAV_BTN_MODULE` into the child's `onenoteframe.aspx`
OOPIF, and the pin forwarder polls all tracked child windows' OOPIFs
(independently of `activeExternalApp` — child windows stay open while the user
switches to other panes).

### M22. OneNote SharePoint team notebooks — `/sites/{id}/onenote/*` API

**Problem:** OneNote pins from the native editor carry page **titles** (the DOM
doesn't expose Graph page IDs). The agent's `list_onenote_notebooks` only called
`/me/onenote/notebooks` (personal notebooks). Team notebooks on SharePoint
sites were "not found" → agent gave up.

**Root cause was wrong:** the token has both `Notes.ReadWrite.All` AND
`Sites.ReadWrite.All`. Graph exposes `/sites/{site-id}/onenote/*` — a full
parallel API for team notebooks. OneDrive already used the `/sites?search=` →
`/sites/{id}` pattern to resolve SharePoint files.

**Fix:** `web/skills/onenote/tools.py`:

- `_onenote_root(site_id)`: returns `/sites/{id}/onenote` or `/me/onenote`.
- `list_onenote_sections` / `list_onenote_pages` / `read_onenote_page`: accept
  optional `site_id` and route through the site-scoped root.
- **New `find_onenote_notebook(name)`**: searches BOTH personal and SharePoint
  site notebooks by name (targeted `/sites?search=<name>`, parallelized). Tries
  progressively looser search terms (drops trailing "Notebook", tries first words)
  because the SharePoint **site** name often differs from the **notebook** name.
  Returns `site_id` per notebook.
- `list_onenote_notebooks`: personal-only by default (fast); `include_sites=True`
  does a parallelized full sweep of up to 50 sites.

### M23. Navigate menu — Back/Forward via Electron menu

Native panes that navigate in-pane (M15) need back/forward. The Electron menu
bar (File | Edit | Navigate | View | Window) has Back (Alt+Left) and Forward
(Alt+Right) items wired to `webContents.goBack()` / `goForward()` on the active
external view. Items are disabled when no history exists; state updates every
500ms via direct `MenuItem.enabled` mutation (no menu rebuild). Works for all
native apps automatically.

### M24. OneDrive filename lives in `[data-id="heroField"]`, not a link/button

**Problem:** Layout 1 (My Files list, shared-library drill-downs, subfolders)
extracted the filename via `nameCell.querySelector('a, button, [role="link"]')`.
In the current OneDrive DOM the filename lives in a
`<span data-id="heroField" title="<filename>">` with **no** `<a>`/`<button>`/
`[role="link"]` wrapper. The selector matched an unrelated button inside the
name cell (the "More Actions" hero button, which has empty text), so
`nameLink.textContent` came back empty. The fallback `nameCell.textContent`
included metadata ("`_course13 items`") which the timestamp-stripping regex
then reduced to empty. Every row was skipped → zero pins injected on My Files,
shared-folder drill-downs, and subfolders.

The same `[data-id="heroField"]` structure is used across all three surfaces
(My Files, `sharepoint.com/shared?id=...` drill-downs, and subfolders within
them), so a single fix covers all three.

**Fix:** prefer `[data-id="heroField"]` (or any element with a `title` attr)
and read its `title` attribute — the cleanest source of the filename — before
falling back to link/button text and `textContent`:

```js
var heroField = nameCell.querySelector('[data-id="heroField"], [title]');
if (heroField && heroField.getAttribute('title')) {
  nameText = heroField.getAttribute('title').trim();
}
if (!nameText) {
  var nameLink = nameCell.querySelector('a, button, [role="link"]');
  nameText = ((nameLink ? nameLink.textContent : nameCell.textContent) || '').trim();
  nameText = nameText.split(/\s{2,}|\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s/i)[0].trim();
}
```

**Symptom to recognize:** pins appear on the Home "Recent" list (Layout 2,
which uses `nameCellTop` — a different structure) but NOT on My Files or any
folder drill-down. The pin module IS loaded (`window.__gatorPinModule === true`)
and rows ARE matched (`filesRow` class present), but `dataset.gatorPin` is
never set to `'1'` because every row is skipped at the `if (!nameText) continue`
gate.

---

## Shell Tiling Layout (current positions — do not assume the original left/right sides)

The shell tiles two real, non-overlapping `WebContentsView`s (`gatorView`,
`slackView`) via `shell/main.js`'s `layout()` function — see the file header
comment for why tiling (not overlapping) and why `WebContentsView` (not
`<webview>`). **The original left/right assignment has since been flipped
end-to-end.** Current state:

| Element                                             | Position                                                   | Notes                                                          |
| --------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------- |
| Slack (`slackView`)                                 | **Left**                                                   | Anchored at `x:0` when the tile is shown                       |
| Gator (`gatorView`)                                 | **Right**                                                  | Fills the remaining width to the right of Slack                |
| Smart Dock (`.dock`, inside Gator's own page)       | **Far right** (CSS flex `order: 6`, last)                  | Sticky — stays visible even when Gator is "hidden" (see below) |
| Third-pane (`.third-pane`, inside Gator's own page) | **Left of chat** (CSS flex `order: 0`, first)              | Teams/Outlook/OneNote/OneDrive/etc. native view                |
| Chat (`.main`)                                      | Between third-pane and the app panes (CSS flex `order: 1`) |                                                                |

Because the visual side of Slack/dock/third-pane all flipped, several
**paired, mirrored pieces of code** had to move together. If you touch any one
of these, check the others:

1. **`shell/main.js` `layout()`** — Slack at `x:0`, Gator at `x:slackW`
   (mirror of the old Gator-left/Slack-right math).
2. **`shell/main.js` `slack-pane:adjust-width` IPC handler** — delta sign is
   `slackTileWidth + delta` (was `- delta`) since the resize boundary is now
   at Gator's _left_ edge instead of its right edge.
3. **`web/static/third-pane.js` `_mountDragHandle()`** (native Slack tile
   resize) — handle CSS moved from `right:0` to `left:0`.
   **Uses `e.screenX`, not `e.clientX`, for the delta calculation** — this is
   load-bearing, not stylistic. Gator's own `WebContentsView` now moves its
   `x` origin on every drag step (it sits to the right of a resizing Slack
   tile), so a coordinate measured relative to Gator's own (shifting)
   viewport drifts against the cursor as soon as there's any async lag
   between the IPC-driven `setBounds()` call and the next mouse event —
   perceived as jitter. `screenX` is an absolute desktop coordinate and is
   immune to that. If dragging the Slack/Gator boundary ever feels jittery
   again, check this first before assuming it's a performance problem.
4. **`web/static/style.css` `.layout > .dock/.main/.third-pane/...` order
   rules** — see the layout-order comment block near the top of the file.
5. **`web/static/style.css` `.third-pane` / `.dock` / `.main-resize` /
   `.third-pane-resize` borders and resize-handle positions** — all mirrored
   (`border-left` ↔ `border-right`, `left` ↔ `right`) to match the new sides.
   `web/static/app.js` `initChatResize()` and `web/static/third-pane.js`
   `initThirdPaneResize()` have matching mirrored drag-direction math.
6. **`web/static/style.css` `.gator-terminal-panel.vertical` / `.gtp-resize-handle`**
   — the vertical integrated terminal sits right before the dock in flex
   order; its border/handle also had to move from the dock's old (left) side
   to its new (right) side. See `web/static/terminal.js`'s `axis === 'x'`
   resize math (mirrored: `startSize - dx` instead of `+ dx`).
7. **Sticky right rail** (`STICKY_RIGHT_RAIL` / `DOCK_W` config constants in
   `shell/main.js`) — when Gator is hidden (app-full mode), it's squeezed to
   `DOCK_W` (56px, matching `--dock-w` in `style.css`) instead of 1px, so the
   dock stays visible/clickable. See §12 (Gator Hide/Show Button) for the
   related dock-click-restore fix and hide/show button sync.
8. **Topbar logo** (`#app-logo-btn`) — moved from `.topbar-left` (top-left)
   into `.topbar-right`, which is now sized to `var(--dock-w)` and flush
   against the true window edge (`margin-right: -.5rem` cancels `.topbar`'s
   own padding) so the logo sits directly above the dock column.

---

## Adding Pin Support for a New App

To add Gator pin buttons to another app (e.g., Gmail, Teams):

### 1. Create a new injection block

In `shell/main.js`, add a new `dom-ready` listener for the new app's
`WebContentsView`:

```js
gmailView.webContents.on('dom-ready', () => {
  gmailView.webContents.executeJavaScript(`
    (function() {
      if (window.__gatorPinModule) return;
      window.__gatorPinModule = true;
      // ... same module structure, with Gmail-specific selectors ...
    })();
  `);
});
```

### 2. Find the app's selectors

Use CDP (Chrome DevTools Protocol) to inspect the app's DOM:

```
# Find "More actions" buttons
[...document.querySelectorAll('button[aria-label]')].filter(b => /more/i.test(b.getAttribute('aria-label')))

# Find header action areas
document.querySelectorAll('[class*=header], [class*=actions]')

# Find message containers with timestamps
document.querySelectorAll('[data-ts], [data-id], [data-message-id]')
```

### 3. Update `scanHeader()` and `scanMessages()` with app-specific selectors

Each app has different class names. Add them to the selector queries.

### 4. Context extraction: URL parser OR DOM-only

**First check whether the app updates `location.href` on navigation.** Slack
does → write a `parseAppUrl()` that extracts `{channel, thread_ts}` and run it
from a URL watcher. Microsoft apps (Teams, likely Outlook) do NOT → skip the
URL parser entirely and read context from the DOM inside the injected module's
scan loop (see M3, and `readTeamsCtx()`). Do not assume URL routing exists.

### 5. Update `updateSlackCtx()` → add `updateAppCtx()` for the new app

The shell needs to dispatch context updates to the new app's page. (For
DOM-only apps like Teams this carries less weight since the in-page scan loop
owns context, but keep the channel separation — see Critical Separations.)

### 6. Update the pin forwarder

The pin forwarder currently reads `window.__gatorPinCtx` from Slack's page.
Add a parallel poller for the new app, or use a shared `__gatorPinCtx`
convention across all apps.

### 7. Update the pin chip's `dataset.pinSource`

Set it to the app name (e.g., `'gmail'`, `'teams'`) so Gator's agent knows
which API to call for message history.

### Checklist for new apps

Core injection:

- [ ] `dom-ready` listener with `__gatorPinModule` sentinel
- [ ] IIFE wrapper (top-level `return` is illegal without it)
- [ ] Idempotent `scanHeader()` — only act if missing/misplaced
- [ ] Idempotent `scanMessages()` — only inject if missing
- [ ] Debounced `MutationObserver` (rAF coalescing)
- [ ] 2s `setInterval` safety net
- [ ] Click handlers read `window.__gatorCurrentCtx` (live, not closure)
- [ ] Click handlers set `window.__gatorPinCtx` (NOT `__gatorSetCtx`)
- [ ] `dispatchCtx()` preserved (cross-page to Gator)
- [ ] `updateAppCtx()` separate from `dispatchCtx()`
- [ ] Sidebar elements excluded from message scan

Icons & sizing:

- [ ] Icons built via `createElementNS` node-specs + `setIcon()` (NOT
      `innerHTML`) — required for any Trusted-Types app, safe everywhere (M4)
- [ ] Button size matched to the host app's native buttons, not Slack's
      defaults blind (M9)
- [ ] Space between pin and hide/show buttons (`marginLeft`)

Pin plumbing:

- [ ] Chip inserted via `window.insertPinChipAtCaret({source,id,label})` — the
      CANONICAL helper (§12). NEVER hand-build chip markup (no X button, no
      trailing `&nbsp;`, use `_pinSourceIcon`)
- [ ] Pin chip uses `dataset.pinSource` + `dataset.pinId` contract
- [ ] Pin persisted to `/api/context/pin` **with `context_id` set to the
      renderer's live active tab id** (never a hardcoded `"default"`) — so it
      shows in the pin orb + Shift+{ scoped to the correct tab only
- [ ] Pin orb refreshed after persist (`_refreshPinOrb(true)`)
- [ ] Pin label uses the MESSAGE TEXT (not a generic chat title) so pins are
      distinguishable — for Teams, `div[id="content-<mid>"]` innerText (M-selectors)
- [ ] Message pin appended into the hover ACTION TOOLBAR, not the hidden
      a11y trigger (M10)
- [ ] Message pin captures the ACTIVE conversation id, scoped to header/message
      region — classify DM vs group/channel by id shape (M11)
- [ ] Pin chip text format: `[Pin: source:id]` (machine-readable for agent)

Pin orb "Open" (deep-link navigation, M12):

- [ ] Slack: `<app>-pane:navigate-pin` → `loadURL` the client deep link (real
      URL routing); derive team id from the live view URL
- [ ] Teams/MS SPA: inject `<a href>` + dispatch click (NOT location.assign);
      auto-dismiss the launcher interstitial via a `did-finish-load` handler
- [ ] Outlook/OneDrive/OneNote (real URL routing): `<app>-pane:navigate-pin` →
      `loadURL(webUrl)`; if the pin lacks a web URL, resolve it first via
      `/api/<app>/items/<id>` (OneDrive) or `/api/onenote/pages/<id>` (OneNote),
      then pass to `navigate<App>Pin`
- [ ] Wire `navigate<App>Pin` in preload + the orb `pin-card-open` handler

Context:

- [ ] Context via URL parser IF the app updates `location.href`; otherwise
      DOM-only from the scan loop (M3) — verify which before writing a parser
- [ ] Click handlers have a fallback when `__gatorCurrentCtx` is null
- [ ] User IDs / MRIs resolved to display names in backend, INCLUDING in-body
      `<@UID>` mentions, not just the sender (M13)

HITL:

- [ ] HITL draft card has editable `<textarea>` for user edits
- [ ] Draft approve endpoint accepts `{ edited_message }` and overrides draft params
- [ ] `<app>-message` dtype routed to the app's real send API in `approve_draft`
- [ ] Native-mode: `<app>-compose` signal renders the approval card (branch on
      `window.gatorShell.isShell`), not the classic compose pane (M8)
- [ ] Duplicate draft cards prevented (deduplicate by `draft_id`)
- [ ] App tile stays open after send (skip `closeThirdPane` in shell mode)

Hide/Show (GLOBAL dock logo — see §12 + M16, NOT an injected button):

- [ ] Add the app's `tpState.type` to `GATOR_NATIVE_PANE_TYPES` in `app.js`
      (without this, hide/show silently no-ops for that app — M16)
- [ ] Add hide+restore branches to `openDrawer`/`closeDrawer` in `app.js`
      (Settings drawer) so the app hides when Settings opens and restores on close
- [ ] Classic apps (when `*_pane_mode="classic"`): maximize button in
      `#tp-detail-header` rebranded with Gator awake/sleeping icons via
      `_tpSyncExpandButton()`; collapse panel button removed (edge handle + Esc)

Shell / Electron (per-app, mostly shared helpers now):

- [ ] Distinct persistent session partition (`persist:<app>`)
- [ ] `buildNonElectronUA()` if the app blocks "Electron" in the UA (all MS
      apps so far — M2); use `setUserAgent()` not `.userAgent =` (M2a)
- [ ] Correct entry URL (test bare domain for redirects — M1)
- [ ] `applyNavigationPolicy()` with the app's `homeHosts` (M5)
- [ ] `applyMediaPermissions()` on the session (SSO/local-network grants even
      if the app has no calls — M5/M7)
- [ ] Inactive view hidden via `setVisible(false)`, never off-screen/1px (M6)
- [ ] Generic drag handle mounted for resize (`_shellDrag.mount()`)
- [ ] `<app>_pane_mode` config key (`classic` | `native`) for safe rollback
- [ ] `sameHostPopupPattern` if file/item clicks should load in-pane instead of
      spawning child windows (M15 — OneDrive/OneNote use this for share/print/
      download pop-outs only)
- [ ] `fileOpenPattern` if file opens (Word/Excel/PPT/PDF/OneNote) should open
      in a child window while the pane stays on the file list (M19 — OneDrive/
      OneNote use `Doc.aspx|WopiFrame|onenoteframe|action=edit/view`)
- [ ] `onChildWindow` callback if pins/modules need to run in child windows
      (M21 — OneNote uses it to inject pins into the editor OOPIF in child
      windows; the callback tracks the child in a Set, wires dom-ready +
      frame-created + periodic sweep, and the pin forwarder polls it)
- [ ] For M365 apps: `onCrossAppNav: _makeCrossAppNavGuard('<app>')` passed to
      `applyNavigationPolicy` so waffle cross-app navs redirect to the correct
      view (M17). Add the app to `classifyM365App()` + `M365_PANE_TYPE` +
      `M365_HOME_URL` + `APP_HOME_URL`.
- [ ] `closeThirdPane()` + switch-away block handle the new app's type (hide
      the view + unmount `_shellDrag`) — otherwise once opened, can't close
- [ ] If the app's content is in a cross-origin iframe: inject via
      `webContents.mainFrame.framesInSubtree` (M20 — find the frame by URL,
      call `fr.executeJavaScript()`). The pin forwarder must also read
      `__gatorPinCtx` from that frame, not the top frame.

### 12. Gator Hide/Show Button

Hide/show Gator is now handled by the **3-state spin logo in the dock**
(`#dock-home`, `GatorChat` in `web/static/app.js`) — see M16. It is GLOBAL
across all native panes: click toggles Gator's `WebContentsView` between split
(visible) and squeezed-to-the-dock-sliver (hidden). The old injected per-app
hide/show button (`scanHideShow`, `gatorHidden`, `updateHideShowBtn`,
`__gatorSyncHideShow`, the `__gatorHideShow` poller, and the `_syncSlackHideShowBtn`
push) has been **removed from all three injected blocks** (Slack/Teams/Outlook).
The `lastHideShow` dedup variable and the `gator-pane:show`/`gator-pane:hide`
IPC handlers remain (the dock logo routes through them), but there is no longer
an in-app button in the native app's own chrome.

**Visual states (dock-home logo):**
| State | Icon | Tooltip |
|---|---|---|
| Split (Gator visible) | Gator awake (filled green, eyes open) | "Gator — Split · click to hide · double-click for chat" |
| Hidden (app-full) | Gator sleeping (outline, curved eyes) | "Gator — Hidden · click to show · double-click for chat" |

**Mechanism (`GatorChat` in `app.js`):**

- `_isNativePane()` → true if `tpState.type` is in `GATOR_NATIVE_PANE_TYPES`
  (M16 — MUST include every native app's type)
- `_applySqueeze(true)` → `window.gatorShell.hideGator()` (shell squeezes
  Gator's view to `DOCK_W`)
- `_applySqueeze(false)` → `window.gatorShell.showGator()` (shell restores)
- For classic (in-Gator) panes, falls back to `_applyExpand()` (CSS-grow
  `#third-pane`)

**Sticky right rail (`STICKY_RIGHT_RAIL` in `shell/main.js`):** when Gator is
"hidden" (app-full mode), Gator's `WebContentsView` used to be squeezed to 1px
(fully invisible, including the dock). It's now squeezed to `DOCK_W` (56px,
must match `--dock-w` in `web/static/style.css`) instead, so the Smart Dock
stays visible and clickable even while Gator's chat/third-pane content is
hidden. This works because `.dock` has `flex-shrink: 0` and a fixed width —
when `.layout`'s flex container is squeezed down to exactly `DOCK_W`, the dock
claims that entire sliver and everything else (`.main`, `.third-pane`, etc.,
all shrinkable/`min-width:0`) collapses to nothing. Flip `STICKY_RIGHT_RAIL`
to `false` to restore the old fully-hidden (1px) behavior.

**Dock-click-while-hidden fix (important, do not regress):** clicking a dock
item (e.g. a favorite skill, Agents) while Gator is hidden used to open a
third-pane / agents-pane _inside_ the still-56px-squeezed viewport, which
overflowed for a moment before the native resize caught up — visually this
looked like the dock/logo "jumping". Fixed by `web/static/app.js`'s `_initDock()`
attaching a **capture-phase** click listener on `#dock` that calls
`window.gatorShell?.showGator()` before any specific button's own (bubble-phase)
handler runs, so the resize request goes out immediately regardless of which
dock item was clicked.

**For classic apps (Teams, Outlook, OneDrive, OneNote, etc. when
`*_pane_mode="classic"`):**

- The maximize button in `#tp-detail-header` uses the same Gator branding
- `_tpSyncExpandButton()` swaps between `GATOR_AWAKE_SVG` and `GATOR_SLEEP_SVG`
- Title: "Hide Gator" / "Show Gator" (was "Maximize middle panel" / "Open Gator")
- This is a SEPARATE affordance from the dock logo — it only appears for classic
  (in-Gator) panes, never for native panes.

**Chat toolbar / three-state toggle — REMOVED.** Gator used to have a
`#chat-toolbar` bar above the chat area with a duplicate pin button
(`#chat-toolbar-pin`) and a double-chevron collapse button
(`#chat-toolbar-collapse`, driving a `≫`/`≪` split ↔ gator-full ↔ app-full
toggle via `_dividerBtns` in `third-pane.js`). This whole bar was removed for
UI simplification — the floating `#pin-orb` is now the only pin control, and
there is no in-app affordance for the old three-state toggle (Slack's own
in-page hide/show button, described above, is the only way to hide/show Gator
now). `_dividerBtns` and its `_gatorFull()`/`_appFull()`/`_restore()` methods
are still present in `third-pane.js` but are dead code — every DOM lookup they
do (`getElementById('chat-toolbar-collapse')`) now returns `null` and each
method safely no-ops (guarded by `if (!btn) return;`). Safe to delete outright
in a future cleanup pass if `_dividerBtns.show()`/`.hide()` call sites (in
`openThirdPane`/`closeThirdPane`) are also removed.

### 13. Classic App Header Changes

- **Collapse panel button removed** — the `#tp-detail-close` button (square
  icon) was removed from both `_resetDetailHeader()` and `tpBuildDetailToolbar()`.
  The pane is closed via the edge collapse handle (`#tp-collapse-handle`) or Esc.
- **Maximize button rebranded** — changed from Material Symbols `combine_columns`/
  `add_column_left` to Gator-branded awake/sleeping icons
- **Title changed** — "Maximize middle panel" → "Hide Gator", "Open Gator" → "Show Gator"

1. **SPA navigation without URL change**: Thread side-panels open without
   changing the URL. The `MutationObserver` handles this (detects new header
   DOM), but there's a ~1 frame delay.

2. **App DOM is not a stable API**: Slack class names
   (`p-view_header__actions`, `c-message_kit__actions`) and Teams `data-tid`
   values can change with app updates. Teams' `data-tid` vocabulary is more
   stable than Slack's generated classes, but both may break on major
   redesigns. Selectors use multiple fallbacks where possible.

3. **Message hover toolbars are ephemeral**: They appear on hover and are
   removed when the mouse leaves. The `MutationObserver` catches them
   appearing, but the pin button is destroyed with the toolbar. This is
   expected — the pin is per-hover, not persistent. (Teams: the pin is appended
   into the `role="toolbar"` reaction/action bar; same ephemeral behavior.)

4. **Performance**: The `MutationObserver` on `document.body` with
   `subtree:true` is expensive on large DOMs. The rAF debounce mitigates this,
   but very fast scrolling may cause minor jank.

5. **Trusted Types (Teams and likely other MS apps)**: the scan loop must use
   `createElementNS` node-building, never `innerHTML`/`DOMParser` — a throw
   there kills the whole loop silently. See M4.

6. **UA-block fragility (MS apps)**: the "strip Electron from the UA" fix (M2)
   relies on an undocumented server-side check and could tighten to Client
   Hints or `navigator.webdriver`. Re-verify sign-in on each regression pass.

---

## Pane mode defaults (native vs classic)

Resolved client-side in `web/static/third-pane.js` from `/api/config` (a pure
passthrough of `config.json` — no server-side default). **Native is the default
in the shell**; classic is the explicit opt-out.

| App            | How native is gated                                                                                                                                                                                                                              | Unset `*_pane_mode` resolves to       |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------- |
| **Slack**      | `isNative()` = in shell **OR** `slack_pane_mode==='native'`. `refreshMode()` defaults unset→native **only when in the shell** (a plain browser has no native Slack tile, and going native there would trigger the adjacent-window helper bridge) | native (in shell) / classic (browser) |
| **Teams**      | Shell presence only — `teams_pane_mode` is NOT read anywhere in JS                                                                                                                                                                               | native (in shell) / classic (browser) |
| **Outlook**    | in shell **AND** `_outlookNativeEnabled()`; resolver defaults unset→native, but the open site is `isShell`-gated so a browser stays classic                                                                                                      | native (in shell) / classic (browser) |
| **OneDrive**   | in shell **AND** `_onedriveNativeEnabled()`; resolver defaults unset→native, `openThirdPane('onedrive')` open site is `isShell`-gated                                                                                                            | native (in shell) / classic (browser) |
| **OneNote**    | in shell **AND** `_onenoteNativeEnabled()`; resolver defaults unset→native, `openThirdPane('onenote')` open site is `isShell`-gated                                                                                                              | native (in shell) / classic (browser) |
| **Confluence** | in shell **AND** `_confluenceNativeEnabled()`; `openThirdPane('confluence')` is `isShell`-gated                                                                                                                                                  | native (in shell) / classic (browser) |
| **Jira**       | in shell **AND** `_jiraNativeEnabled()`; `openThirdPane('jira')` is `isShell`-gated                                                                                                                                                              | native (in shell) / classic (browser) |
| **GitHub**     | in shell **AND** `_githubNativeEnabled()`; `openThirdPane('github')` is `isShell`-gated. Pin injection not yet implemented.                                                                                                                      | native (in shell) / classic (browser) |

Only an explicit `"classic"` forces the old UI. Native panes **require the
shell** — every open path is `isShell`-guarded, so defaulting to native never
enables it outside Electron.

## File Reference

| File                                                            | Role                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shell/main.js`                                                 | Shell main process: Slack + Teams + Outlook + OneDrive + OneNote + Confluence + Jira + GitHub `WebContentsView`s, per-app injection modules (pin module for Slack/Teams/Outlook/OneDrive/Confluence/Jira — OneNote uses `webFrameMain.framesInSubtree` for OOPIF injection M20; GitHub pin injection not yet implemented), pin forwarding via `_forwardPinFromView` for all 8 apps (OneNote polls child window OOPIFs via `_onenoteChildWindows` Set M21), `layout()` tiling + `setVisible` hiding with coalesced `setImmediate` debounce (eliminates app-switch flicker), `activeExternalApp` switching, `buildNonElectronUA()`, `buildSvg()`/`setIcon()` (Trusted-Types-safe icons), `LocalNetworkAccessChecks` disable-features switch, `app.setName('AI Gator')`, generic `external-pane:*` IPC (+ `slack-pane:*` aliases) with dock-click reload-home (M18, `APP_HOME_URL`), deep-link nav IPCs for all apps (`*-pane:navigate-pin`) — M12, M365 app launcher cross-app nav guard `classifyM365App()`/`_makeCrossAppNavGuard()` (M17), `sameHostPopupPattern` on OneDrive/OneNote/Jira/Confluence (M15), `fileOpenPattern` for child-window file opens (M19), `onChildWindow` callback (M21), Navigate menu back/forward via `navigationHistory.*` (M23) |
| `shell/navigation-policy.js`                                    | Generic `applyNavigationPolicy(view, {homeHosts, sameHostNavPattern, sameHostPopupPattern, onCrossAppNav, fileOpenPattern, onChildWindow})` — allows all-https SSO hops, auth/same-domain popups; reused by all native apps (M5). `onCrossAppNav` (M17): pre-nav block in `will-navigate` + `setWindowOpenHandler`. `fileOpenPattern` (M19): intercepts file-open URLs, opens in child `BrowserWindow`. `onChildWindow` (M21): callback after child window creation. `sameHostPopupPattern` (M15): inverse popup model for in-pane file/page navigation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `shell/media-permissions.js`                                    | Generic `applyMediaPermissions(session)` — origin-allowlisted mic/cam/screen-share + `AUTH_FLOW_PERMISSIONS` (local-network-access/notifications/clipboard/idle) for SSO (M5/M7)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `shell/preload.js`                                              | `window.gatorShell` IPC bridge: show/hide + width getters/setters for all 8 apps (Slack/Teams/Outlook/OneDrive/OneNote/Confluence/Jira/GitHub) + `showGator`/`hideGator` + `navigate*Pin` deep-link Open for all apps + `getActiveApp`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `shell/menu.js`                                                 | Per-OS menu with Back/Forward (Alt+Left/Alt+Right) in Navigate submenu. `MenuItem.enabled` mutated live every 500ms from `canGoBack()`/`canGoForward()` on the active external view — no menu rebuild. Returns `{menu, backItem, forwardItem}` so main.js can update enabled state directly.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `web/skills/onenote/tools.py`                                   | OneNote tools with SharePoint team notebook support (M22): `find_onenote_notebook(name)` searches personal + site notebooks; `_onenote_root(site_id)` routes to `/sites/{id}/onenote` or `/me/onenote`; `list_onenote_sections`/`list_onenote_pages`/`read_onenote_page` accept optional `site_id`; `list_onenote_notebooks` personal-only by default, parallelized full site sweep with `include_sites=True`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `web/static/third-pane.js`                                      | `_nativeSlack` module; `_shellDrag` generic drag handle (all native apps); `_outlookNativeEnabled()`/`_onedriveNativeEnabled()`/`_onenoteNativeEnabled()`/`_confluenceNativeEnabled()`/`_jiraNativeEnabled()`/`_githubNativeEnabled()` resolvers; native early-return branches in `openThirdPane()` for all native apps; `closeThirdPane()` hides the active native view + unmounts `_shellDrag` for all apps; `_dividerBtns` (dead — see §12)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `web/static/app.js`                                             | Pin chip contract (`dataset.pinSource`/`pinId`); **`buildPinChipEl()` + `window.insertPinChipAtCaret()` — canonical chip helper used by ALL insertion paths (§12)**; `_handlePaneSignal()` native-vs-classic branch for `teams-compose`; `_injectDraftApprovalCard()` (`teams-message` dtype); pin-orb card `Open` handler for all apps (`navigate*Pin` — M12); `_initDock()` dock-click→`showGator()`; per-tab pin persistence; **`GATOR_NATIVE_PANE_TYPES` allowlist (M16) — includes all 8 native app types; MUST update when adding a new app or hide/show silently no-ops**; `openDrawer`/`closeDrawer` hide+restore for all native apps; `GatorChat._clearAll()` only resets CSS-expand (does NOT call `showGator()`) — prevents the 56→full→56 width bounce on app switch                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `web/static/index.html`                                         | `.dock` (Smart Dock, far right), `.third-pane` (left of chat), `.topbar-right` (logo) — `#chat-toolbar` removed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `web/static/style.css`                                          | `.layout` flex `order` rules, mirrored borders/handles for the flipped layout, `--dock-w`, `body.gator-split .main-resize { display: none }` (hide stale classic resize handle when a native pane is tiled)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `web/config.py`                                                 | `slack_pane_mode` + `teams_pane_mode` + `outlook_pane_mode` + `onedrive_pane_mode` + `onenote_pane_mode` config keys (`classic` \| `native`). Native is the DEFAULT in the shell; only an explicit `"classic"` opts out (Teams has no read — always native in shell)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `web/routes/slack.py`                                           | Slack HITL endpoints: `/api/slack/channels/{id}/post` + `/send`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `web/routes/teams.py`                                           | Teams Skype/chatsvc API incl. `/api/teams/send-message` (used by native-mode HITL approve)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `web/routes/onenote.py`                                         | Pin persistence: `POST /api/context/pin` (`ContextPinRequest`, `context_id`), `GET /api/context/pins`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `web/routes/email.py`                                           | Draft approval: `POST /api/drafts/{id}/approve` (handles `slack-*` + `teams-message` dtypes)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `web/skills/slack/tools.py`                                     | Slack tool handlers + user ID resolution (`_resolve_user`) + in-body `<@UID>` mention resolution (`_resolve_mentions_in_text`, M13)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `web/skills/teams/tools.py`                                     | Teams tool handlers; `_tool_teams_open_compose` creates a `teams-message` draft                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `web/skills/_drafts.py`                                         | In-memory draft store for HITL                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `web/skills/context/state.py`                                   | Persistent pin storage, keyed by `context_id` (tab id)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `docs/superpowers/specs/2026-07-28-native-teams-pane-design.md` | Teams design doc                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `docs/superpowers/plans/2026-07-28-native-teams-pane.md`        | Teams task-by-task plan                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

> Note: the `spike/` folders (`native-teams-pane`, `native-outlook-pane`, etc.)
> where M1–M4 were originally discovered have been removed from the repo now that
> the behavior is proven and lives in `shell/main.js`. See git history if you need
> the original spike findings.
