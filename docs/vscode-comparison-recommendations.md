# What AI Gator Should Borrow From VS Code

**Date:** 2026-06-01
**Status:** In progress — see ✅ markers below for shipped items.

**Markdown renderer fixes shipped 2026-06-04** (not from vscode specifically, found via audit):
- Bold/italic color: `.bubble strong` was overriding `.prose strong` with accent green — scoped to non-prose bubbles
- Bold/italic in streaming: tightened regex to prevent `**partial` mid-stream rendering as `<em></em>`
- Bold/italic inside backticks: moved processing before code-stash restore so `` `**x**` `` stays literal
- Link patterns: added `mailto:`, `#fragment`, root-relative `/path` to markdown link regex
- Ordered list start numbers: `<ol start="N">` now emitted for lists not starting at 1
- h4 (`####`) headings: added to single-line and mixed-content rendering paths

This document compares AI Gator's current product surface against patterns in the [microsoft/vscode](https://github.com/microsoft/vscode) repo and the Copilot Chat experience. Only patterns judged **beneficial without regressing existing Gator UX** are included. The "do not bring over" list at the end is just as important — most of VS Code's internals are Electron-specific and would be a net negative.

Each recommendation is tagged:
- **Value:** Low / Med / High (UX or capability impact)
- **Effort:** S (≤1 day) / M (1–5 days) / L (1–3 wks) / XL (>3 wks)
- **Regression risk:** Low / Med / High
- **Strategic:** does it unlock future work, or is it a one-off improvement?

---

## Tier S — High-leverage, low risk, do these first

### S1. Typed chat "content parts" pipeline
**Value: High · Effort: M · Regression risk: Low · Strategic: very**

VS Code's chat stream isn't a markdown blob — it's a list of typed parts (`{type, payload}`), with one renderer file per type: markdown, code, diff, file-tree, references, tool-confirmation, error, progress, MCP-server-status, hooks, sub-agent calls, plan reviews, citations, elicitation, follow-ups. See `src/vs/workbench/contrib/chat/browser/widget/chatContentParts/` (40+ files).

**Gator today** (`web/static/app.js` lines 5600-6063): tool calls, streaming tokens, and messages are rendered inline but the dispatch is ad-hoc switch logic. Adding a new render type (e.g. inline diff, plan review) requires editing the renderer.

**Proposal**
- Define a discriminated-union schema on the wire: `{type: "markdown"|"code"|"tool_call"|"tool_result"|"diff"|"plan_review"|"confirmation"|"progress"|"error"|"followups"|..., payload: {...}}`.
- One JS module per type under `web/static/chat-parts/`. Renderer is a dumb dispatch.
- Migrate existing renderers behind this; ship one new type (`copy_button_code`, see S2) as the first user-visible win.

**Why this first?** Almost every other chat improvement (S4, A1, A6, B1) becomes additive instead of invasive once parts are typed.

---

### S2. Code-block actions: copy, insert, apply
**Value: High · Effort: S · Regression risk: None**
**✅ DONE (2026-06-04) — Copy button shipped. Insert/Apply deferred (no active editor target in web context).**

VS Code code blocks have Copy / Insert at Cursor / Apply in Editor on hover. Gator code blocks render via Quill CSS (`web/static/vendor/quill.snow.css`) but have **no copy button** — users must manually select.

**Proposal**
- On hover of any `<pre><code>`, show a top-right toolbar with: Copy, Insert (when an editable target is focused), and a copy-as-quoted-reply for code review flows.
- Use `navigator.clipboard.writeText`. Toast confirmation via S6.
- ~50 lines of JS, zero backend.

**What shipped:** `.code-block-wrap` hover reveals a Copy button (top-right). Clicking copies the raw code text, button flips to "Copied!" for 1.8s. Optional lang label shown top-left. Insert/Apply left for when an in-app editor exists (B1 / A4 scope).

---

### S3. Universal command palette with content prefixes
**Value: High · Effort: M · Regression risk: Low (additive)**

VS Code uses one Ctrl+Shift+P widget for everything: commands (`>`), files (no prefix), symbols (`@`), lines (`:`), help (`?`). One muscle memory, infinite extensibility.

**Gator today** (`web/static/index.html` 823-840, `app.js` ~373): Ctrl+K opens a launcher **for skills only**. There are no global actions, no conversation-jump, no settings-jump.

**Proposal**
- Promote Ctrl+K to a universal palette:
  - no prefix → recent conversations + new conversation
  - `>` → commands (send, clear, retry, switch model, switch persona, open settings, restart server)
  - `@` → skills (current behavior)
  - `#` → pinned items
  - `?` → keyboard shortcuts help
- Keep current Ctrl+K → skill behavior as the default when query starts with `@` or first-time-empty for back-compat.
- Recent items pinned at top per scope.

**Prerequisite:** S5 (stable command-IDs).

---

### S4. Port VS Code's fuzzy scorer
**Value: Med · Effort: S · Regression risk: Low**
**✅ DONE (2026-06-04) — `_fuzzyScore` / `_fuzzyFilterSkills` added to app.js, wired into skill `@` picker.**

`src/vs/base/common/fuzzyScorer.ts` is ~200 lines of well-tuned scoring (prefix 8pts, consecutive 6→3 pts, separator boundary 4-5 pts, camel-case boundary 2 pts, exact-case +1, base match +1, requires sequential char order). Matches what people intuitively mean by "fuzzy".

**Gator today** (`app.js` skill-mention fuzzy filter ~line 750+): basic substring/prefix.

**Proposal**
- Port the algorithm verbatim to JS (it's tiny). Use it in the universal palette (S3), the skill chip selector, and the marketplace search.
- Single source of truth so filtering feels consistent.

**What shipped:** `_fuzzyScore(query, target)` scores with prefix/boundary/consecutive/exact bonuses + target-length penalty. `_fuzzyFilterSkills` filters and sorts. Wired into `_openSkillPickerDropdown` — typing partial strings like `jir` now surfaces Jira, `conf` surfaces Confluence, etc.

---

### S5. Stable command-ID namespace + `when`-clause evaluator
**Value: High (strategic) · Effort: M · Regression risk: None**

In VS Code, every action has a string ID (`workbench.action.foo`, `editor.action.bar`). Keybindings, menus, palette entries, programmatic callers all route through `executeCommand(id, args)`. `when`-clauses (`editorFocus`, `inDebugMode`, `resourceExtname == .ts`) gate visibility/enablement declaratively.

**Gator today**: keyboard shortcuts are hardcoded in `app.js` (Ctrl+O at line 537, Ctrl+K ~2815, Ctrl+J via index.html 704, Shift+{ via 701). No central registry, no way to enumerate or rebind.

**Proposal**
- Build a `web/static/commands.js` registry: `register("gator.chat.send", handler, {when: "chatFocus"})`.
- Migrate existing shortcuts into it. A tiny when-clause evaluator (~100 lines) covering `&&`, `||`, `!`, `==`, `in`, context-key lookups.
- Context keys (`chatFocus`, `hasPinnedItems`, `mcpServerSelected`, `streaming`) maintained centrally.
- **Unlocks:** customizable keybindings (later), discoverable shortcut help (S3 `?`), skills contributing commands without touching core JS.

---

### S6. Toast + progress system based on `withProgress`
**Value: High · Effort: M · Regression risk: Low**

VS Code's `window.withProgress({location, title, cancellable}, task)` decouples the *what* (long task) from the *where* (notification area, status bar, view title). Cancellation is part of the contract.

**Gator today** (`web/notifications.py`, status text in chat bubbles, `index.html` 804-810 reconnect overlay): only desktop OS notifications + inline "Thinking..." text. No toasts, no cancellable progress, no error-with-retry toast. Common gap noted by Explore agent.

**Proposal**
- A `runWithProgress({location: "toast"|"statusbar"|"chatturn", cancellable: bool}, async fn)` helper on the frontend.
- Toast widget at bottom-right: severity (info/warn/error), optional action buttons, dismissable.
- Cancel button surfaces to backend via existing task-stop infra (`web/task_queue.py`).
- Status bar already exists (server dot at index.html 505-516); generalize it to host items with `{alignment, priority, tooltip, command}` so skills can contribute indicators.

---

### S7. MCP: auto-import servers from Claude Desktop / Cursor on first run
**Value: High · Effort: S–M · Regression risk: None**

VS Code reads other clients' MCP configs (`chat.mcp.discovery.enabled`, `mcpMigration.ts`, `mcpDiscovery.ts`) and offers to import. Removes "configure your servers three times" friction.

**Gator today** (`web/mcp/manager.py`, `web/mcp/github_fetcher.py`): users add MCP servers manually or pull from a GitHub repo. No discovery from sibling apps.

**Proposal**
- On first launch, scan known locations:
  - `~/AppData/Roaming/Claude/claude_desktop_config.json` (Claude Desktop)
  - `~/.cursor/mcp.json` (Cursor)
  - `~/.config/Code/User/mcp.json` (VS Code)
- Show a one-time "Import N MCP servers from your other tools?" wizard (use Phase 4 wizard infra per memory `project_phase4_wizard`).
- Each imported server still goes through Gator's trust dialog (S8) before first spawn.

---

### S8. MCP: explicit trust dialog + per-tool toggles + log link
**Value: High (safety + debug) · Effort: M · Regression risk: Low**

Three related MCP patterns:
- **Trust ceremony** — VS Code confirms before first spawn; `MCP: Reset Trust` is an explicit command. Critical because `npx -y` configs can execute arbitrary code.
- **Per-tool disable** — a 30-tool server can be pruned to 3 active tools, reducing token spend and risk surface.
- **Error → log deep link** — failed tool calls have a "Show Output" button that opens the per-server output channel.

**Gator today** (Explore agent): no health-check button, no per-tool toggles, no inline log access. Connection errors surface as text. `logs/server.log` exists (per memory `reference_server_log`) but isn't linked from the UI.

**Proposal**
- Trust dialog modal on first server enable; record `trusted: true` in `~/.gator/config.json` per server. Add "Reset trust for this server" command (S5 registry).
- In MCP server settings (`web/static/mcp_add_modal.js`), add a tool list with on/off checkboxes; persist disabled tool IDs; filter them out where MCP tools are injected (`routes/chat.py` 73-98).
- When any tool errors, render an Error content part (S1) with a "View server log" button that opens a per-server log pane (next item).

---

### S9. Per-skill / per-MCP-server output channels
**Value: Med · Effort: M · Regression risk: None**

VS Code gives every extension a named output channel; users pick which to view. Debugging unknown failures becomes possible.

**Gator today**: one `logs/server.log` for everything. To debug a single skill or MCP server, users grep.

**Proposal**
- Tag each log line with a channel (`skill:email`, `mcp:atlassian`, `agent_loop`).
- Add a Logs panel (use S6 status bar contribution) with channel picker and live tail.
- Backend: a `ChannelLogger` wrapper around `logging.Logger` that prefixes channel; sink to per-channel files under `logs/channels/`.

---

## Tier A — Strategic, bigger investment, very high value

### A1. JSON-Schema-driven skill manifest + auto-generated settings UI
**Value: High · Effort: L · Regression risk: Med (requires migration)**

VS Code's `package.json` `contributes.*` is the most under-appreciated discipline in the codebase. Every command, menu, view, configuration key, keybinding, theme is declared up-front in JSON Schema. The workbench renders the entire UI surface — including the settings UI — **without loading the extension**.

**Gator today**: skills declare via Python (`tools.py` exporting `TOOL_DEFS`, `TOOL_HANDLERS`, `DIRECT_INTENTS`, `TOOL_DEPENDENCIES`). The Plugins settings tab says "coming soon" (`index.html` 437) precisely because there's no schema to render from.

**Proposal**
- Add a `manifest.json` (or extend `SKILL.md` frontmatter) per skill declaring:
  - `commands: [{id, title, when}]`
  - `configuration: {properties: {<key>: {type, default, scope: "user"|"conversation", description, enum?}}}`
  - `activationEvents: ["onCommand:<id>", "onSkillMention:<id>", "onPinType:<type>"]`
  - `keybindings: [{command, key, when}]`
  - `dependencies: ["plugin:capability"]`
- Auto-generate the per-skill settings panel from the configuration schema (one generic form component).
- Auto-generate the Plugins settings tab (kills the "coming soon" gap).
- Publish the schema as `docs/schemas/gator-skill-manifest.schema.json` and put `"$schema"` in templates so skill authors get IntelliSense.

**Migration**: existing skills keep working; manifest is optional initially. Marketplace can promote skills that have one.

---

### A2. Profiles (settings + skill set + integrations, switchable & shareable)
**Value: High · Effort: M–L · Regression risk: Low**

VS Code profiles bundle settings + keybindings + extensions + UI state + MCP servers, switch from the palette, share as a URL or `.code-profile` file, with a "Temporary profile" auto-deleted on exit.

**Gator today**: personas exist (`index.html` 200-225) but only swap the system prompt. There's no way to say "Sales profile = M365 skills + sales-CRM MCP + sales persona; Dev profile = code-runner + GitHub + dev persona."

**Proposal**
- Extend the persona concept into a **profile**: `{name, persona, enabled_skills[], enabled_mcp_servers[], default_model, custom_settings{}}`.
- Profile switcher in the topbar or palette (S3 `> Switch Profile`).
- Export as JSON, share via URL or file.
- Default templates: "M365 productivity", "Developer", "Sales", "Empty / Minimal".

---

### A3. Tool-call confirmation as an inline chat part with Allow-once / Allow-always / Deny
**Value: High (safety) · Effort: M · Regression risk: Low**

VS Code's `chatConfirmationWidget.ts` renders consent prompts as part of the chat stream — title + body + button group with dropdown options (Allow once, Allow always, Deny). The consent record is permanent in the conversation.

**Gator today** (`routes/chat.py` line 44, `web/hooks/executor.py` 21-70): shell_runner and code_runner are gated; user approves mid-conversation. Approval is binary per turn, not remembered, and lives in transient state. The CRITICAL human-in-the-loop rule (per memory `feedback_human_in_loop_messaging`) requires Email/Teams/Slack to be draft-only — this needs first-class UX, not ad-hoc.

**Proposal**
- A `confirmation` content part type (built on S1).
- Three buttons + dropdown for "Allow always for this server", "Allow always for this tool".
- Persist allow-always grants per `(profile, skill_id|mcp_server, tool_name)` tuple.
- Email/Teams/Slack-send tools wired to require confirmation EVERY time (no allow-always option for send actions) — enforces the human-in-the-loop policy at the framework level instead of relying on each skill.

---

### A4. Checkpoints / per-turn snapshot + restore-to-here
**Value: High · Effort: L · Regression risk: Med**

VS Code Copilot Chat snapshots workspace files before every chat request; restoring rewinds files **and removes the request from history** (forcing re-prompt instead of re-run of a known-bad turn).

**Gator today**: no snapshot/rewind. Browser/file-side-effecting tools (browser-use, code_runner, file ops) make this especially risky.

**Proposal**
- Define a `Snapshotable` interface skills can implement (`snapshot() -> token`, `restore(token)`).
- For browser-use: capture the active page URL + form state. For file ops: a temp copy of touched files. For MCP tools: no-op unless server declares snapshot support.
- "Restore to here" button on hover over each user message in the conversation.
- Removes everything after the restored turn from the visible conversation (kept in audit log).

**Risk note**: not all tools are snapshotable (sending an email isn't reversible). A4 only works *because* of A3 — non-reversible actions never auto-fire, so checkpoint-restore is meaningful for the rest.

---

### A5. Walkthroughs / multi-step onboarding contributable by skills
**Value: Med · Effort: M · Regression risk: None**

VS Code walkthroughs are dismissable, resumable checklists contributed by extensions with links into commands/settings. They beat tooltips for onboarding.

**Gator today**: Phase 4 wizard exists per memory `project_phase4_wizard` but is bespoke. M365/Slack/Jira each have ad-hoc setup flows in the settings drawer.

**Proposal**
- Generalize the Phase 4 wizard into a walkthrough engine: `[{title, description, completion_check, action_command, action_label}]`.
- Each skill can contribute walkthroughs via its manifest (A1).
- "Getting started" panel surfaces walkthroughs for skills whose `completion_check` returns false (e.g., M365 not signed in → show M365 walkthrough).

---

### A6. Disambiguation routing: declare example utterances per skill
**Value: Med · Effort: M · Regression risk: Med (changes routing behavior)**

VS Code chat participants declare a `disambiguation` property — categories and example queries — so the router can pick the right participant without an `@mention`.

**Gator today** (`routes/chat.py` 49-52, 240-260): keyword regex + Haiku fallback classifier. Works but is opaque (users can't tell why a skill activated) and tuning means editing keywords.

**Proposal**
- Add `disambiguation: {category, examples: [...]}` to skill manifests (A1).
- Replace the keyword scan with embedding similarity over the example utterances (cached at startup).
- Keep the Haiku fallback for low-confidence cases.
- **Add transparency**: when a skill auto-activates, the chat shows a small chip "via skill X (matched: '...')" with a one-click "this was wrong" feedback button. Important per the planner-scope-creep feedback in memory.

---

## Tier B — Quality of life, lower urgency

### B1. Inline diff content part
**Value: Med · Effort: M · Regression risk: None.** A unified-diff renderer (not Monaco) for any tool that mutates files/text — Keep, Undo, Copy buttons. Built on S1.

### B2. Followups / suggested next prompts after each turn
**Value: Med · Effort: S · Regression risk: None.**
**✅ DONE (2026-06-04) — `_addSuggestedActions` extended with 4 extraction patterns + explicit server-push via SSE `followups` message type.**

VS Code's `chatFollowups.ts` shows 2-3 clickable next-step prompts after the assistant turn. Cheap to add; high engagement uplift.

**What shipped:** Added patterns for "Would you like to X?" (→ "Yes, X" chip), list-option bullets near end of response, and an `explicitLabels` parameter so the backend can push `{type:"followups", labels:[...]}` via SSE without heuristics.

### B3. Activation events (lazy-load skills)
**Value: Med · Effort: M · Regression risk: Med.** Today all skills load at startup (`app.py` 145-210). With manifests (A1), declare activation events and defer module import until triggered. Startup time win as skill count grows.

### B4. Extension packs ("M365 pack", "Developer pack")
**Value: Med · Effort: S · Regression risk: None.** Bundle 3-5 related skills installable as a unit. Pure marketplace metadata; reuse existing installer.

### B5. Recently-used surfaced in palette
**Value: Med · Effort: S · Regression risk: None.** Pin recent commands/skills/conversations to the top of the palette (S3). Per-scope MRU list in localStorage.

### B6. Settings JSON view alongside UI
**Value: Med · Effort: M · Regression risk: Low.** Add a "View as JSON" tab to the settings drawer showing the live `~/.gator/config.json` with edit. Power users move 10× faster; casual users keep the GUI. Pairs with A1's schema-driven approach.

### B7. Four-tier telemetry opt-in (`off | crash | error | all`)
**Value: Med · Effort: M · Regression risk: None.** Currently no telemetry at all per Explore agent. Defensible privacy posture defaults to `crash` or `error`. Required for any future "improve the product with data" loop.

### B8. Light theme + named color tokens
**Value: Med · Effort: M · Regression risk: Low.** Move hardcoded hex values (`style.css` 50-76) into named tokens (`--gator-chat-userBubble`, etc.). Add a light variant. Switch on `prefers-color-scheme` + explicit setting.

### B9. Accessible View / aria-live announcements
**Value: Med (a11y compliance) · Effort: S · Regression risk: None.**
- "Show as plain text" command that dumps the focused chat turn into a focusable `<pre>` aria-live region.
- `aria-live="polite"` on response-complete, `assertive` on tool-error.
- Focus trap in all modals (current gap per Explore agent).

### B10. `gator new-skill` scaffolder CLI
**Value: Med · Effort: M · Regression risk: None.** One command generates manifest.json + tools.py + SKILL.md + a sample test. Critical once A1 ships — schema discipline only works if scaffolding produces correct manifests.

### B11. Scheduler "Create schedule" modal
**Value: Med · Effort: S · Regression risk: None.**
**✅ DONE (2026-06-04) — Full create modal in agents-pane.js, POSTing to existing `/api/scheduler/jobs`.**

**What shipped:** `_apOpenNewScheduleModal()` — modal with Name, Prompt, trigger type switcher (Recurring/Every N min/One-time), dynamic cron fields (day-of-week, hour, minute, timezone), optional end-date with preset chips, validation, and error display. Replaces the old chat-prefill behavior from the "+ New" button.

---

## Explicitly do NOT bring over

These exist in VS Code for reasons that don't apply to a Python web-app chat product. Adopting them would be net-negative.

| Pattern | Why not |
|---|---|
| **Extension host process model** | Tied to Electron + Node IPC. Steal the *threat model* (untrusted code isolated) via per-skill subprocess or MCP-server boundary if needed, not the architecture. |
| **Monaco-based diff rendering** | Massive dependency for marginal gain. A unified diff renderer (B1) is enough for chat. |
| **MCP sandbox / gateway broker channel** | Multi-process complexity that doesn't fit a single-process Python server. |
| **Web vs. desktop split (`browser/` vs. `electron-browser/`)** | Gator is web-only; complexity is irrelevant. |
| **TextMate / semantic-token coloring** | Source-code-editor-specific. |
| **Settings sync conflict-resolution UI** | Premature until sync exists; last-write-wins + backup covers 95%. |
| **Activity Bar as a primary nav metaphor** | Gator's chat-first surface shouldn't grow an IDE-style activity bar. The status bar + topbar + palette (S3) carry the load. |

---

## Suggested rollout sequence

To avoid regression and compound the wins:

1. **Foundations (Tier S, 2-3 weeks)**: S5 (command IDs) → S1 (typed parts) → S2/S4/S6 in parallel. Everything downstream gets cheaper.
2. **MCP polish (1-2 weeks)**: S7 → S8 → S9. Big debuggability + safety wins; targeted scope.
3. **Palette + universal nav (1 week)**: S3 once S1/S4/S5 are in.
4. **Tier A strategic (4-6 weeks)**: A1 first (unlocks A2, A5, B3, B6, B10). Then A3 (safety priority). A4 only after A3.
5. **Tier B (opportunistic)**: B2/B4/B5/B11 are S-effort each; ship as gaps appear.

## Regression-risk callouts

These items carry the highest risk of breaking existing UX and need careful gating:
- **A1 manifest migration** — existing skills must keep working without a manifest; treat manifest as additive.
- **A4 checkpoints** — must not silently rewind irreversible actions; gate by A3.
- **A6 disambiguation routing** — changes which skill activates for ambiguous prompts; ship behind a setting + add the "this was wrong" feedback chip from day one.
- **B3 lazy load** — easy to regress startup ordering; needs an integration test that exercises every skill activation path.

## References

Most-useful VS Code source paths if implementing:

- `src/vs/workbench/contrib/chat/browser/widget/chatContentParts/` — the 40+ renderer pattern (S1)
- `src/vs/workbench/contrib/chat/browser/widget/input/` — picker chips
- `src/vs/workbench/contrib/chat/browser/widget/chatConfirmationWidget.ts` — A3 reference
- `src/vs/workbench/contrib/mcp/browser/mcpToolCallUI.ts` — MCP UX
- `src/vs/workbench/contrib/mcp/common/mcpDiscovery.ts`, `mcpMigration.ts` — S7 reference
- `src/vs/base/common/fuzzyScorer.ts` — S4 reference, ~200 lines, directly portable
- `src/vs/workbench/contrib/chat/common/chatModes.ts` — A2/persona model
- Public docs: [Chat extension guide](https://code.visualstudio.com/api/extension-guides/chat), [Extension manifest](https://code.visualstudio.com/api/references/extension-manifest), [Profiles](https://code.visualstudio.com/docs/configure/profiles), [Checkpoints](https://code.visualstudio.com/docs/copilot/chat/chat-checkpoints), [MCP](https://code.visualstudio.com/docs/copilot/customization/mcp-servers).
