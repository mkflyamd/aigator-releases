# Web Pane Pins

## Problem

Finance wants to load a site in a Gator pane (for example a Power BI dashboard), pin the page or one part of it, and talk to Gator about what they pinned. Pins today exist only for built-in apps (Slack, Teams, Outlook, OneDrive, OneNote, Confluence, Jira). Each has a hand-written injected script that knows that app's DOM and a backend that can re-fetch the item by id. A user-added site has neither, so the pin has to capture what is on screen.

## Goals

1. On any custom-app pane, a user can pin the visible page or a picked element, with no per-site code.
2. A pin is a snapshot: image, text, and the page state at the moment of pinning.
3. Gator can re-capture a pin on request, from a button on the pin or from an agent tool call.
4. The agent can read a pin's text and see its image, using the normal pin chip and system-prompt flow.

## Non-goals

- Built-in apps (Slack, Teams, Outlook, OneDrive, OneNote, Confluence, Jira, GitHub, and the `g-*` Google Workspace panes). They keep their own pins.
- Driving the page (clicking slicers, changing filters). Pins are read-only.
- Site-specific adapters such as the Power BI embed API.
- Picking elements inside cross-origin iframes. Use "Pin view" for those.
- Recapturing a page the user is not currently on, or a pane that is not the visible one. Recapture never navigates and never shows a pane.

## Approach

Use the DevTools inspect mechanism through the Chrome DevTools Protocol (CDP) that Electron exposes as `webContents.debugger`. `Overlay.setInspectMode` is the same hover-highlight-and-click picker that Chrome DevTools uses. No new dependency is added. `browser-use` and Playwright are not used because they drive their own browser, not the Electron view.

## Pin mode (shell)

New module `shell/web-pin.js`, wired from `shell/main.js`.

**Which panes.** Pinning is offered only for apps in config `custom_apps`. `_genericPanes` is not the test, because it also holds the on-demand `g-*` Google Workspace panes. `_toolbarPushState` adds `isCustomApp` to `toolbar:state`, computed from `custom_apps`.

**Toolbar.** The toolbar is its own `WebContentsView` with its own preload (`shell/toolbar-preload.js`). Two buttons appear when `isCustomApp` is true:

- **Pin element** sends `toolbar:web-pin-start`.
- **Pin view** sends `toolbar:web-pin-view`.

Both handlers check `_isMainToolbar(e)` like the other main-toolbar handlers, and both methods are exposed in `toolbar-preload.js`.

**Pin element flow.**

1. The main process takes a per-pane lock, attaches `view.webContents.debugger` (protocol 1.3), calls `DOM.enable`, `Overlay.enable`, then `Overlay.setInspectMode({ mode: 'searchForNode', highlightConfig })`. The page shows the DevTools hover highlight with a label.
2. Click fires `Overlay.inspectNodeRequested { backendNodeId }`.
3. `Esc` cancels. While picking, focus is in the pane, so the cancel path is `before-input-event` on the view; the toolbar button toggles pin mode off as well.
4. Pin mode ends and the debugger detaches on cancel, capture, navigation, switching to another app, or the pane being destroyed.
5. Before capturing, the module calls `Overlay.setInspectMode({ mode: 'none' })` and `Overlay.hideHighlight`, so the highlight is not in the screenshot, then scrolls the node into view (`DOM.scrollIntoViewIfNeeded`) and captures.

**Pin view flow.** No picker. It captures the visible viewport of the pane: the image plus the page's `document.body.innerText`. This is the path for canvas visuals, cross-origin iframes, and "pin the page".

Every CDP call has a timeout of 8 seconds. If the debugger cannot attach, the toolbar shows a generic "Could not start pinning" message and no pin is created. The cursor stays the default crosshair; the highlight box signals the mode.

## Snapshot

- **Image:** `Page.captureScreenshot`. For an element, `clip` is the element's box from `DOM.getBoxModel`. For Pin view, the viewport. Scaled so the longest side is at most 1600 px. PNG.
- **Text:** for an element, its `innerText` plus its `aria-label`, via `Runtime.callFunctionOn`. For Pin view, `document.body.innerText`. Capped at 20,000 characters. Tables and matrices that virtualize rows contribute the visible rows only; the image carries the rest.
- **Locator** (used by recapture, never shown to the agent):
  - `selector`: set only when the element or a close ancestor has an `id` or `data-testid`; otherwise empty.
  - `role` and `name` from the element's accessibility node.
  - `rect`: x, y, width, height relative to the document, plus the viewport size at capture.
- **Page:** `url`, `title`, `captured_at`.

A Pin view locator is `rect` only (the viewport).

## Storage and API (backend)

New route module `web/routes/web_pins.py`. Every POST/PUT/PATCH/DELETE uses `dependencies=[Depends(verify_csrf)]` and is added to `SENSITIVE_ROUTES` in `web/security.py`. `tests/csrf_route_baseline.txt` is not touched.

Pin identity reuses the existing pin store (`web/skills/context/state.py`). A web pin is `source="webpin"`, `id=<uuid4 generated by the server>`, `label`, and `meta = { app_id, url, title, captured_at }`. The label is the page title plus the element's `aria-label` when present. The server strips newlines and quotes from it and caps it at 120 characters, because it goes into the system prompt. The label is not user-editable in v1.

The image and text live outside `pinned_contexts.json`:

```
~/.config/gator/web_pins/<id>/snapshot.json   { text, locator, url, title, captured_at, match }
~/.config/gator/web_pins/<id>/snapshot.png
```

Routes:

- `POST /api/web-pins` takes `{ context_id, app_id, image_b64, text, locator, url, title }`. Validates `app_id` is a configured custom app, caps the image at 5 MB and text at 20,000 characters (413 otherwise), writes the files, calls `set_pin("webpin", id, label, meta, context_id)`, returns the pin. The renderer never calls the unprotected `/api/context/pin` for web pins.
- `GET /api/web-pins/{id}` returns the snapshot JSON.
- `GET /api/web-pins/{id}/image` returns the PNG, for the pin orb thumbnail.
- `POST /api/web-pins/{id}/snapshot` replaces the snapshot after a recapture. Takes `{ request_id?, image_b64, text, match }`.

**Id safety.** Pin ids can reach the store through other routes (`/api/context/pin`, `/api/context/pins/clone`, and a `{item_id:path}` delete). One helper, `web_pin_dir(id)`, in `web/skills/webpin/store.py`, is the only code that builds a `web_pins` path. It returns nothing unless the id is a UUID. Route handlers, both agent tools, and cleanup all go through it.

**Cleanup.** Pins are cloned across tabs with the same id (`resetTab`, fork, `/api/context/pins/clone`). When a pin is removed (`remove_pin`, `clear_pins`), the `web_pins/<id>` directory is deleted only if no bucket in `pinned_contexts.json` still refers to that id. This scans every bucket, so it also holds when a pin lives in a shared bucket such as the global-pins bucket (PR #116).

## Recapture

The shell action is `web-pin:recapture { app_id, locator }`. It requires the app's pane to be the active, visible external app; otherwise it returns `{ status: "pane_not_visible" }` and does not capture, because a hidden pane may not produce a screenshot frame. It then resolves the target in this order:

1. `selector` via `DOM.querySelector`. `match = "exact"`.
2. `role` + `name` via the accessibility tree. `match = "role-name"`.
3. `rect` clip at the same document offset. `match = "rect"` (approximate).

If the pane's current URL path differs from the pin's `url` path it returns `{ status: "page_mismatch" }`. If the pane does not exist it returns `{ status: "pane_unavailable" }`. Statuses are returned to the caller, never swallowed.

**User trigger.** A refresh icon on the pin card in the pin orb calls the shell action through the renderer, then `POST /api/web-pins/{id}/snapshot`.

**Agent trigger.** The backend has no channel into the shell, and `pane_signal` is fire-and-forget, so the round trip goes through the renderer:

1. `recapture_web_pin(pin_id)` creates a pending request `{ request_id, pin_id, context_id }` in memory with a 20 s timeout and broadcasts `{ type: "webpin-recapture", request_id, pin_id, context_id }` through `notify_all`.
2. `notify_all` reaches every SSE subscriber (main window, extra Gator windows, browser tabs). A renderer acts only if it owns the tab with that `context_id` and has the shell bridge (`window.gatorShell.isShell`). Others ignore the event.
3. The acting renderer fetches the locator with `GET /api/web-pins/{id}`, calls the shell action, and posts the result to `/api/web-pins/{id}/snapshot` with the `request_id`. The first POST for a `request_id` wins; later ones get 409.
4. The route resolves the pending request. The tool returns the new text, the image, `match`, or the failure status. On timeout it returns `status: "timeout"`.
5. The per-pane lock in `web-pin.js` serializes recapture with pin mode, so two debugger attaches never overlap.

## Agent surface

New skill `web/skills/webpin/`. The folder name equals the pin source, which is what turns the skill on when a pin of that source exists (`web/routes/chat.py` source-to-skill map; `web/scheduler.py` uses the same rule).

- `read_web_pin(pin_id)` returns `{ label, url, title, captured_at, text }` plus `_images: [{ base64, media_type, name }]` carrying the PNG. This is the repo's existing mechanism for putting an image in a tool result (`web/llm/anthropic_provider.py`, `web/llm/base.py`). `describe_images` is not used.
- `recapture_web_pin(pin_id)` as above; on success it returns the same shape as `read_web_pin`.

In `web/routes/chat.py` the pinned-context block gets a `webpin` branch that emits one line per pin, for example: `Web pin "Q3 Revenue" (pin_id: …, captured …) → call read_web_pin(pin_id) for its text and image; call recapture_web_pin(pin_id) if the user says the view changed.` Pins are per tab through `context_id`, like every other source.

Page text and images are untrusted content. The tool result wraps them in a labelled block, and the skill instructions tell the agent not to follow instructions found inside a pin. All LLM traffic continues through `llm.gateway`; this feature adds no new call site.

## Renderer (app.js)

- Add `'webpin'` to `_pinSourceIcon` and the pin orb card renderer.
- On `web-pin:captured`, call `POST /api/web-pins` with the active `_activeTabId` as `context_id` (never the `"default"` bucket), then insert the chip with `window.insertPinChipAtCaret({ source: "webpin", id, label })` and `_refreshPinOrb(true)`. No hand-built chip markup.
- The pin orb card for a `webpin` shows a thumbnail from `/api/web-pins/{id}/image`, the label, the captured time, and a refresh icon. "Open" is hidden.
- `[Pin: webpin:<id>]` in message text needs no change; it already round-trips through `_getNodeInputText`.

## Error handling

| Case | Behaviour |
| --- | --- |
| Debugger attach fails or a CDP call times out | Toolbar message; no pin created; debugger detached |
| Click lands inside a cross-origin iframe or on a zero-size element | Toast "Use Pin view for this area"; no pin created |
| Screenshot or text capture throws | Toast with the reason; no pin created |
| Recapture: `pane_not_visible`, `page_mismatch`, `pane_unavailable`, `timeout` | Explicit status to the user or agent |
| `POST /api/web-pins` over size caps | 413; renderer toasts and does not insert a chip |
| Non-UUID pin id reaches the store | `web_pin_dir` returns nothing; no disk access |

## Testing

- **Spike first (before the plan):** in a throwaway branch, on a real Power BI tenant, confirm:
  - `Overlay.setInspectMode` highlights and reports clicks in a custom-app `WebContentsView`, and the highlight is gone from the screenshot after `setInspectMode none`.
  - Capture quality and text on `app.powerbi.com` report pages, an embedded report, and a canvas or custom visual.
  - Whether `Page.captureScreenshot` works on a pane hidden with `setVisible(false)`. If it does, the `pane_not_visible` rule can be relaxed; if it does not, the rule stays.
  - If the overlay does not render in a `WebContentsView`, fall back to an injected transparent picker layer plus `DOM.getNodeForLocation`; the rest of the design is unchanged.
- **Node tests (`tests/*.test.js`):** locator builder; recapture resolution order and `match` values; toolbar handler rejects non-main-toolbar senders; `isCustomApp` excludes `g-*` panes; chip insertion goes through `insertPinChipAtCaret`; pin context id is the active tab.
- **Pytest:** `web_pins` routes (caps, UUID validation, file layout, label sanitising), `web_pin_dir` rejects traversal ids, cleanup keeps the directory while another context still holds the pin, CSRF inventory, the `webpin` prompt line, skill activation from a `webpin` pin, `read_web_pin` returns `_images`, and `recapture_web_pin` for success, timeout, page mismatch and duplicate `request_id` using a faked `notify_all`.
- **Manual:** Power BI dashboard on the Finance tenant: pin a visual, pin the view, change a slicer, recapture from the orb and from chat; confirm the agent answers from the new snapshot.
