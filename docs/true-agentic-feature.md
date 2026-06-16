# True Agentic Architecture - Feature Specification

## What the User Gets

### Before (Current)

```
User sends message
     |
     v
[Dead air - blinking cursor, 2-8 seconds]     <-- nothing visible
     |
     v
[Status lines appear all at once]              <-- tool names flash by
  * Checking email...
  * Reading calendar...
     |
     v
[Full response appears as one block]           <-- 80-char chunks, fast but chunky
```

- No visibility into what the AI is doing during the API call
- No streaming - response appears as a wall of text
- No reasoning visibility - the user never sees WHY the AI chose a tool
- Tools run one at a time (email, then calendar, then Jira...)
- "Is it stuck?" feeling during long API calls

### After (This Feature)

```
User sends message
     |
     v
[Immediately] "Gator is on it..."             <-- instant feedback
     |
     v
[Reasoning block appears - collapsible]        <-- thinking tokens stream live
  > Reasoning (click to expand)
  | The user wants their email and calendar.
  | I'll check both simultaneously...
     |
     v
[Response streams token-by-token]              <-- like ChatGPT/Cursor
  "Let me check your email and cale..."
  "Let me check your email and calendar for today..."
     |
     v
[If tools needed - status lines stream as each finishes]
  * Checking email...          (appears when email tool completes)
  * Reading calendar...        (appears when calendar tool completes - ran in parallel!)
     |
     v
[Response continues streaming]
  "You have 3 unread emails and a meeting at 2pm..."
```

---

## UI Changes Inventory

### 1. Immediate Status on Send (app.js)

**What:** Show "Gator is on it..." immediately when the user presses send.

**Where:** `app.js`, after line 4654 (`let statusLines = []`)

**How:** Push an initial status line before the fetch begins:
```
statusLines.push('Gator is on it...');
prose.textContent = '';   // clear, then render status
// render status lines into prose
```

**Visual:**
```
+------------------------------------------+
| Gator                                     |
|   * Gator is on it...                    |
|   [blinking cursor]                      |
+------------------------------------------+
```

**CSS:** Uses existing `.status-line` styles. No new CSS needed.

---

### 2. Token-by-Token Streaming (app.js)

**What:** Display the AI response as it generates, one token at a time (like ChatGPT).

**Where:** `app.js`, inside the SSE event dispatch block (~line 4726)

**New event type:** `msg.token`

**How:** Add a new branch in the SSE reader loop:
```
// New: streaming tokens (replaces chunked msg.text for streamed responses)
if (msg.token) {
    full += msg.token;
    const statusHtml = renderStatusHtml();
    const prefix = statusHtml ? statusHtml + '<hr class="status-divider"/>' : '';
    // render prefix + markdown of full text into prose
}
```

**Backward compatibility:** The existing `msg.text` handler stays unchanged as a fallback for non-streaming responses. Both can coexist -- `msg.token` is per-token, `msg.text` is the old 80-char-chunk path.

**Visual progression:**
```
Frame 1:  "Let"
Frame 2:  "Let me"
Frame 3:  "Let me check"
Frame 4:  "Let me check your"
...
Frame N:  "Let me check your email and calendar. You have 3 unread..."
```

**Performance note:** The existing `renderMarkdown()` function is called on every token with the full accumulated text. This works because:
- It's synchronous and fast (hand-rolled, no library)
- The `.prose` subtree is small and bounded
- Partial markdown (e.g., unclosed code fences) safely falls through as plain text
- This is the same approach used today with 80-char chunks, just more granular

**CSS:** No new CSS. Uses existing `.typing .prose::after` blinking cursor which trails the live content.

---

### 3. Extended Thinking / Reasoning Block (app.js + style.css)

**What:** Show the AI's chain-of-thought reasoning in a collapsible block above the response.

**Where:** 
- `app.js`: new `msg.thinking` handler in SSE dispatch
- `style.css`: new `.thinking-block` styles

**New event type:** `msg.thinking` (with optional `msg.agent` field for multi-agent future)

**SSE wire format:**
```
// Single-agent (current):
data: {"thinking": "I should check email...", "agent": null}

// Multi-agent (future -- no protocol change needed):
data: {"thinking": "Breaking into steps...", "agent": "planner"}
data: {"thinking": "Calling read_email...",   "agent": "executor"}
data: {"thinking": "Verified all items...",   "agent": "verifier"}
```

**How (app.js):** Add a `thinkingText` accumulator and stash agent for future use:
```
let thinkingText = '';
let lastThinkingAgent = null;

// In SSE dispatch:
if (msg.thinking) {
    thinkingText += msg.thinking;
    lastThinkingAgent = msg.agent || null;  // stashed for future multi-agent UI
    // re-render with thinking block + status + response
}
```

**Rendering:** The thinking block appears above the status lines and response:
```
+------------------------------------------+
| Gator                                     |
|                                          |
| [v] Reasoning                            |  <-- collapsible, default closed
| | The user is asking about their email    |
| | and calendar. I should check both at    |
| | the same time since they're independent |
| | queries...                             |
|                                          |
|   * Checking email...                    |  <-- status lines
|   * Reading calendar...                  |
|  ----------------------------------------|  <-- divider
|                                          |
|  You have 3 unread emails:              |  <-- streamed response
|  1. Meeting invite from Sarah (2pm)     |
|  2. ...                                 |
+------------------------------------------+
```

**New CSS (style.css):**
```css
.thinking-block {
    border-left: 2px solid var(--border);
    padding: 0.3rem 0 0.3rem 0.8rem;
    margin-bottom: 0.6rem;
    font-size: 0.82rem;
    color: var(--text-dim);
}
.thinking-block summary {
    cursor: pointer;
    font-weight: 500;
    color: var(--text-sub);
    user-select: none;
}
.thinking-block summary:hover {
    color: var(--text);
}
.thinking-block .thinking-content {
    margin-top: 0.3rem;
    white-space: pre-wrap;
    line-height: 1.5;
}
```

**Behavior:**
- Default: collapsed (closed) -- users who want details can expand
- Streams live while open -- if the user opens it mid-generation, they see tokens appearing
- Disappears entirely if the model returns no thinking tokens (non-thinking models, Haiku)

**Multi-agent future (wire format ready, UI deferred):**

When multi-agent orchestration ships (Planner/Executor/Verifier), `msg.agent` will be non-null. The future UI change (frontend-only) would split the single thinking block into per-agent collapsible blocks:

```
+------------------------------------------+
| [v] Planner                              |
| | Breaking this into: 1) check email     |
| | 2) check calendar 3) summarize         |
|                                          |
| [v] Executor                             |
| | Calling read_email with count=5...     |
| | Calling read_calendar for today...     |
|                                          |
| [v] Verifier                             |
| | Response covers all 3 requested items  |
+------------------------------------------+
```

No wire protocol change needed -- the `agent` field is already in the SSE events.

---

### 4. Parallel Tool Execution (Visual Effect)

**What:** When the AI calls multiple tools simultaneously, status lines appear as each tool finishes rather than all at once.

**Where:** No frontend code change needed -- this is a backend change. The existing `msg.status` handler already appends and re-renders.

**Visual difference:**

Before (sequential):
```
[3 second pause]
  * Checking email...          \
  * Reading calendar...         |-- all appear at once
  * Searching Jira...          /
```

After (parallel):
```
  * Checking email...          <-- appears at T+1s (email finished first)
  * Searching Jira...          <-- appears at T+1.2s (Jira finished second)  
  * Reading calendar...        <-- appears at T+2s (calendar finished last)
```

**Note:** Status events now arrive in *completion order*, not declaration order. The fastest tool's status appears first. This is more informative -- users see progress as it happens.

---

### 5. Usage Stats Event Change

**What:** The `msg.usage` event timing changes slightly.

**Before:** `msg.usage` arrived with `msg.text` at the end.
**After:** `msg.usage` arrives as a separate final event after all tokens have streamed.

**Where:** No frontend change needed -- the existing `msg.usage` handler works unchanged.

---

## Complete Message Anatomy (After)

```
+------------------------------------------+
|                                          |
| [v] Reasoning                            |  <-- NEW: thinking block (collapsible)
| | (AI's chain-of-thought)               |
|                                          |
|   * Gator is on it...                   |  <-- NEW: immediate status
|   * Checking email...                    |  <-- existing: tool status
|   * Reading calendar...                  |  <-- existing: tool status (parallel)
|  ----------------------------------------|  <-- existing: divider
|                                          |
|  Response text streams here token by     |  <-- CHANGED: token streaming
|  token instead of appearing all at once. |
|                                          |
|  +------------------------------------+ |
|  | Draft: Reply to Sarah's email       | |  <-- existing: draft card
|  | [Approve] [Edit]                    | |
|  +------------------------------------+ |
|                                          |
+------------------------------------------+
```

---

## What Does NOT Change in the UI

| Element | Status |
|---------|--------|
| Message bubbles (user/assistant) | Unchanged |
| Draft approval cards | Unchanged |
| Compose pane (email/Teams) | Unchanged |
| Third pane (Jira/Confluence) | Unchanged |
| Gator loading animation | Unchanged |
| Toast notifications | Unchanged |
| Model selector dropdown | Unchanged (data-driven from server) |
| Context meter on send button | Unchanged |
| Stop button (abort) | Unchanged |
| Suggested actions | Unchanged |
| Copy/action bar | Unchanged |
| Tab switching | Unchanged |
| Pin management | Unchanged |
| Markdown rendering | Unchanged |

---

## Summary of File Changes

### `web/static/app.js`

| Line Area | Change | Size |
|-----------|--------|------|
| ~4654 (after statusLines init) | Add initial "Gator is on it..." status push | 2 lines |
| ~4653 (variable declarations) | Add `let thinkingText = ''`, `let lastThinkingAgent = null` | 2 lines |
| ~4726 (SSE dispatch) | Add `msg.token` handler | ~5 lines |
| ~4726 (SSE dispatch) | Add `msg.thinking` handler (stashes `msg.agent` for future multi-agent) | ~10 lines |
| ~4740 (render logic) | Update prose rendering to include thinking block above status | ~6 lines |

**Total: ~22 lines of JS changes**

### `web/static/style.css`

| Addition | Size |
|----------|------|
| `.thinking-block` styles | ~15 lines |

**Total: ~15 lines of CSS**

### Files NOT modified

- `index.html` -- no new DOM elements needed (thinking block is generated dynamically)
- `third-pane.js` -- no changes
- Any skill's `tools.py` -- zero changes
