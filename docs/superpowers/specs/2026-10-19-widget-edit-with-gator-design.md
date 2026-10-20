# Widget "Edit with Gator" — Design

Sub-project 8 of the Issue #55 integration branch (`feat/issue-55-demo-recorder-overhaul`).
Line numbers cite `web/static/app.js` on main with the security hardening merged.

## Problem

A saved widget can be opened, pinned, hidden from screen capture and deleted from the My Widgets manager, but it cannot be changed. The only way to revise one today is to ask Gator for a new widget in an ordinary chat and press Save again, which creates a second widget with a new id and loses the pin state and name. Gator also cannot see the saved widget's HTML, so the user has to paste it back in by hand.

## Design

### User flow

1. In My Widgets each row gets a pencil button (title "Edit with Gator") between Open and the capture toggle.
2. Clicking it closes the manager, opens a new chat tab titled `Edit: <name>`, and prefills the input with `Edit my "<name>" widget: ` with the caret at the end. If a tab is already editing that widget, it switches to that tab instead.
3. The user types the change and sends. Gator receives the widget's current HTML as hidden context and replies with the complete updated widget in an `html:widget` block.
4. In an editing tab every rendered widget toolbar shows `Save` (creates a copy, unchanged) and a new `Update "<name>"` button. Update replaces the saved widget's HTML in place, keeping its id, name and pinned state, then shows `✓ Updated`.

### Components

**Tab record** (`web/static/app.js`)

- `_newTabRecord(id, opts)` (new, next to `_saveTabs`, ~3926) builds the tab object. `opts` is `{title?, editingWidget?: {widget_id, name}}`; anything else, including the `MouseEvent` that `addBtn.addEventListener('click', createTab)` (4790) passes today, is ignored.
- `createTab(opts)` (4266) uses `_newTabRecord(_genTabId(), opts)` in place of the inline literal at 4269.
- `_saveTabs` (3919) adds `editingWidget` to the persisted mapping. It currently copies only `id/title/createdAt`, so without this the editing state is lost on reload. `_loadTabs` (3901) already returns stored objects unchanged.
- `_activeEditingWidget()` (new) returns `editingWidget` of the tab whose id is `_activeTabId`, else `null`.

**Hidden context** (`web/static/app.js`)

- `_latestWidgetHtmlFromHistory(hist)` returns the trimmed body of the newest `html:widget` / `html:live` fence in an assistant message, or `null`.
- `_buildWidgetEditSuffix(name, html)` returns the instruction text: edit the named saved widget, treat the HTML as data, reply with the COMPLETE updated widget in one `html:widget` block plus one sentence on what changed, preserve everything not requested.
- `_widgetEditSuffixFor(tabId, hist)` (async) returns the suffix when the tab has `editingWidget`, using `_latestWidgetHtmlFromHistory` first and `GET /api/widgets/{id}` as fallback; `null` otherwise.
- In `doSend` (13242) the suffix becomes `window._pendingWidgetSuffix || (await _widgetEditSuffixFor(requestContextId, requestHistory)) || null`, and flows through the existing `system_prompt_suffix` field (13264, `web/routes/chat.py:158,1808`).

**Edit entry**

- `gatorWidgetEditWithGator(widgetId, name)` (new) closes the manager, switches to or creates the editing tab, prefills the input if empty and places the caret at the end.
- Manager row (18390–18397) gets the pencil button via `gatorActionAttrs('gatorWidgetEditWithGator', [w.widget_id, w.name])`.
- Both new action names are added to `GATOR_ACTIONS` (40–74); the click dispatcher (90–118) ignores names outside it.

**Update button**

- `renderMarkdown` toolbar (11586–11604) renders `<button id="${widgetId}-update-btn" …>↻ Update "<name>"</button>` after Save when `_activeEditingWidget()` is non-null and the widget is not `_noSave` (11582–11585). The name is `escapeHtml`'d and cut to 20 characters with an ellipsis.
- `gatorWidgetUpdateConfirm(frameId)` (new, beside `gatorWidgetSaveConfirm` 18069) reads the iframe HTML with `gatorWidgetHtmlFromId` (18043), resolves the target from `_activeEditingWidget()`, sends `PATCH /api/widgets/{id}` with `{html}` only, then refreshes the dock (`gatorWidgetRenderDock`, 18118) and re-renders the manager if it is open.

### Data flow

```
Manager pencil → gatorWidgetEditWithGator → createTab({title, editingWidget}) → _saveTabs (persists editingWidget)
send → doSend → _widgetEditSuffixFor(tab, history) → system_prompt_suffix → /api/chat
reply (html:widget) → renderMarkdown → Update button (tab record read at render)
Update click → PATCH /api/widgets/{id} {html} → dock + manager refresh → "✓ Updated"
```

No backend change: `PATCH /api/widgets/{widget_id}` (`web/routes/widgets.py:125`) already accepts `html` alone, leaves other fields untouched, is CSRF-protected, and the global fetch wrapper (app.js:1–32) attaches the token.

## Decisions

1. **Context is sent on every message of an editing tab, not only the first.** The server stubs fenced widget HTML in stored history (`web/conversation_store.py:156,188`), so after one turn Gator can no longer see its own widget; a one-shot suffix would leave the second request without a source.
2. **The working copy is the newest `html:widget` block in the tab's client history, falling back to the saved widget.** Users iterate several times before pressing Update, and the saved copy would be stale until then.
3. **The suffix is derived at send time from the tab record instead of being set on `window._pendingWidgetSuffix` at click time.** The global is one-shot and tab-agnostic: it would leak into a different tab's message if the user switched tabs before sending, and it cannot survive a reload.
4. **The Edit click does not fetch the widget.** The row already supplies id and name, and the HTML is fetched at send time only when history has no newer copy, so the click cannot go stale.
5. **`editingWidget` is stored on the tab record and persisted by `_saveTabs`.** Rendering and history re-render (4211, 4410) read it from there, so Update buttons reappear after reload and tab switch.
6. **The Update button resolves its target from the active tab at click time, not from a data attribute.** One source of truth; a button rendered into a non-editing tab can never write to a widget.
7. **Background-tab streaming needs no special handling.** Streamed content for an inactive tab is rebuilt through `renderMarkdown` on `switchTab` (4402–4411) when that tab is active, so the Update decision is always made against the visible tab.
8. **Clicking Edit on a widget already being edited switches to that tab.** Two tabs editing the same widget would race each other's Update.
9. **Update sends `{html}` only.** PATCH leaves name, description, pinned and `hide_on_capture` untouched, which satisfies "keeps name and pinned" without reading them back.
10. **`createTab` takes an options object rather than being followed by mutation of `_tabs[_tabs.length - 1]`.** One save and one render instead of two.
11. **The tab title is `Edit: <name>` cut to 24 characters.** Auto-titling only overrides the literal `New Chat` (5105), so the title survives the first message.
12. **The suffix tells Gator to treat the widget HTML as data.** It is placed in the system prompt, and the saved HTML may contain text from earlier tool output.
13. **`web/skills/aigator/SKILL.md` is unchanged.** The suffix carries the editing instruction, and the skill already documents the `html:widget` output format.
14. **Transient widgets (`_noSave`) get no Update button.** They get no Save either; the same predicate applies.

Out of scope: a raw-HTML editor, live reload of an already-open floating widget window, undo.

## Error handling

- Update `404` (widget deleted after the tab was opened): the button shows `Widget was deleted — use Save` and stays disabled; Save remains available.
- Update network error or non-2xx: the button shows `Update failed — retry` and is re-enabled.
- Update while the active tab has no `editingWidget`, or the iframe or button is missing: no-op.
- Suffix lookup: if history has no widget and the fallback `GET` fails or returns non-OK, the suffix is `null` and the message is sent as an ordinary chat message.
- Widget names are inserted into HTML only through `escapeHtml`; action arguments go through `gatorActionAttrs` escaping.

## Testing

`tests/widget_edit_with_gator.test.js` (Node `vm`, same extraction style as `tests/chat_xss_render.test.js`, run by `npm --prefix shell test`):

- `_newTabRecord`: default record, click-event opts ignored, title and `editingWidget` carried, `editingWidget` without `widget_id` dropped; `createTab` with and without opts.
- `_saveTabs` persists `editingWidget` and omits it for plain tabs.
- `_activeEditingWidget` for editing, plain and unknown active tabs.
- `_latestWidgetHtmlFromHistory`, `_buildWidgetEditSuffix`, `_widgetEditSuffixFor` (history hit, fetch fallback, fetch failure, non-editing tab); `doSend` wiring.
- `GATOR_ACTIONS` contains both new names; `gatorWidgetEditWithGator` (new tab, truncation, reuse of an existing tab, draft preserved).
- `renderMarkdown`: Update button present only in an editing tab, absent for `data-no-save`, name escaped and truncated, Save still present.
- `gatorWidgetUpdateConfirm`: PATCH URL, method and `{html}`-only body; `✓ Updated`; 404; network failure; non-editing tab.

Manual browser verification with the saved widget "Local Use" is the last task of the implementation plan.
