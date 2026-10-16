# Draft Card Formatting — Design

## Goal

Draft approval cards carry, edit, and send formatted text for email, Teams, and Slack. Adding a future service requires one adapter and no card changes.

Formatting must survive three hops:

1. LLM drafts the message (may use `body_html`, markdown, or plain text).
2. User edits it in the card (bold, italic, underline, lists, links, code).
3. User clicks Send or Open in Outlook, and the service receives its native format.

## Today's gaps

- The card renders and edits plain text only. `body_html` from the LLM is never shown.
- Approve always sends the card's plain text as `edited_message`. For `email-send` this overrides `body_html` and does not convert newlines to `<br>`, so formatting and line breaks are lost.
- Slack and Teams conversions are unrelated to what the card displays.

## Design

### Canonical model: sanitized HTML subset

Every draft has one canonical rich body: HTML limited to
`p br b strong i em u s a ul ol li code pre blockquote` plus mention spans
(`<span data-mention-id data-mention-name>`). Anything else is stripped.

### New module `web/skills/_rich_text.py`

Pure functions, no I/O, one place for all conversion rules:

- `sanitize(html) -> html` — allow-list tags and attributes; `href` limited to `http`, `https`, `mailto`; drop scripts, styles, event attributes.
- `normalize(body=None, body_html=None) -> html` — `body_html` if present; otherwise plain text or markdown converted to the subset (paragraphs, `**bold**`, `*italic*`, `` `code` ``, lists, links).
- `to_text(html) -> str` — plain fallback and `message_snippet`.
- Adapter registry: `ADAPTERS[service] = Adapter(capabilities, render)`.
  - `email` — HTML passthrough, wrapped in `<html><body>`.
  - `teams` — HTML subset with Skype mention spans and nested lists.
  - `slack` — mrkdwn (`*bold*`, `_italic_`, `~strike~`, backtick code, `<url|label>`, `<@Uxxx>`); underline dropped.
- `capabilities` is a set of allowed formats (for example Slack has no `u`). The card toolbar is built from it, so users cannot apply formatting the target cannot carry.

### Draft creation

`create_draft` normalizes at creation and stores `body_html` (canonical) in the draft params next to the existing fields. Email, Teams, and Slack tools pass their `body` / `body_html` / `message` through `normalize`. Existing tool schemas stay valid.

### Card (`web/static/app.js`)

- Replace the textarea and plain contenteditable bodies with one rich editor (contenteditable) seeded from canonical HTML.
- Toolbar (bold, italic, underline, bullet list, numbered list, link, code) is filtered by the service's capabilities, which the draft payload carries.
- Mention chips keep today's behavior and serialize as mention spans.
- Approve posts `edited_html` (the editor's HTML). `edited_message` stays accepted and means plain text.

### Server send paths (`web/routes/drafts.py`)

- Approve and Open-in-Outlook resolve one body: `sanitize(edited_html)` if given, else `normalize(edited_message)` if given, else the stored `body_html`.
- The resolved HTML goes through the service adapter. The per-route escaping and `<br>` logic in `email-send`, `email-reply`, `email-forward`, and `open_draft_in_outlook` is replaced by the adapter.
- Slack `chat.postMessage` receives the mrkdwn text; Teams receives HTML with `html=True`.
- No new routes; the existing CSRF dependencies stay.

### Human-in-the-loop

Unchanged. Nothing sends without the user clicking Send or Open.

## Testing

Python unit tests (`tests/test_rich_text.py`):

- `sanitize` strips scripts, event attributes, and `javascript:` links; keeps the allowed subset.
- `normalize` converts plain text and markdown; prefers `body_html`.
- Each adapter: bold, italic, lists, links, code, mentions, and newline handling.

Route tests (extend `tests/test_hitl_draft_unification.py`):

- `email-send` approve with `edited_html` sends HTML with formatting intact.
- `email-send` approve with plain `edited_message` keeps line breaks.
- `slack-post` approve sends mrkdwn; `teams-message` approve sends HTML.
- Open-in-Outlook uses the same resolved body.

Manual browser check of the card: LLM-formatted draft renders, toolbar edits apply, and the sent payload matches for each service.
