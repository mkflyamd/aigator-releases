# Rail Pane Transitions — Design

Date: 2026-11-23
Status: approved by user and Design Head; four stacked PRs on `feat/browser-rail-pane`.

## Goal

Clicking a right-rail item should feel smooth, like Apple app switching. Today it feels choppy.

## Findings

- A rail click only toggles `.active` (`_setRailActive`, app.js:1766); `renderDock()` does not run, so CSS transitions work.
- `.dock-item.active::before` is a per-button 3x18px bar with no transition. The active tint is hardcoded dark green (style.css:16295) and wrong in light theme. `.dock-item:hover` scales to 1.05.
- Native panes are external WebContentsViews. CSS cannot animate or cross-fade them.
- `external-pane:hide` ignores any app that is not the active one (main.js:4601), so most of the 10-20 hide IPCs per click do nothing. The likelier causes of choppiness:
  - `body.gator-split` is toggled with async `executeJavaScript` (`_syncGatorSplit`, main.js:4428), so Gator reflows in a different frame than the native view moves.
  - External views have no `backgroundColor`, so a new view paints white in dark theme.
  - Hide and show can land in different event-loop turns; `layout()` coalesces with `setTimeout(0)` only by heuristic (main.js:4241-4264).
  - Lazily created views are added on top of the toolbar view and can cover its dropdown.
- Classic `#third-pane` (Calendar, Code Agent): open already snaps (`no-transition`, third-pane.js:2992-3000). Close animates `width` over 0.52s with an accelerating curve, reflowing chat every frame.
- Styleguide §8 says pane open/close 0.5s, which matches neither behaviour.
- Calendar and Code Agent are the only panes that use the classic view. Every other rail item opens in a native web view.

## Scope

Four stacked PRs, each on its own branch.

### PR 1 — Instrumentation (this branch: `feat/pane-switch-instrumentation`)

Measure before building. Timestamps at the rail click in the renderer, at IPC receipt in main, at the start of `_layoutNow`, and at first paint of the target view. Count layout passes per click and whether any pass ran with no active external app. Add a tracing recipe to the docs. Fix whatever the numbers show in PR 2.

### PR 2 — Native switch

- One main-side `switchPane(to)` handler replaces the per-type hides and shows in `_openThirdPaneImpl` for native panes. It carries a sequence number so rapid clicks A, B, C resolve to C.
- It ensures the view exists, sets the active app, shows the incoming view before hiding the outgoing one, runs one `_layoutNow`, and applies the Gator split in the same pass (skipped when unchanged).
- Every external view gets the current theme background colour.
- A placeholder shows only when the view has not painted yet (cold open), capped at about 400ms. The reveal is a cut.
- Fix stacking so lazily created panes do not cover the toolbar dropdown.
- Keep the same-app home reload, the settings drawer hide/restore, and the Slack and GitHub special cases.

### PR 3 — Rail

- One sliding indicator on `.dock` (`position: relative`): a 40x40 tinted pill with the bar attached. Colour is `rgba(var(--accent-rgb), …)`, replacing the hardcoded green. It moves with `--transition` (200ms, `cubic-bezier(.4,0,.2,1)`).
- It updates on click in the first lines of the handler, before any IPC. Not on pointer-down, because items are draggable.
- It re-syncs after `renderDock`, window resize and reorder. It is placed without a transition on first paint and hidden with opacity when no rail item is active.
- Icon colour change on the active item uses a 120ms transition. `:active` press scale is 0.96 over 100ms. Hover `scale(1.05)` is removed.
- Tokens: `--dur-fast: 120ms`, `--dur-base: 200ms`. Reuse existing `--ease-out` (`cubic-bezier(0,0,.2,1)`) and `--ease-in` (`cubic-bezier(.4,0,1,1)`). Exits use `--ease-in` and `--dur-fast`.
- Update styleguide.md §8 in this PR.
- `prefers-reduced-motion`: the indicator jumps; content gets a short opacity fade only.

### PR 4 — Classic pane motion (Calendar, Code Agent)

- Give the pane its final width immediately (keep the 530px minimum). Remove the width and min-width transitions and the rAF + 50ms `no-transition` race. Keep `transition: none` for resize drags.
- Open: inner content fades in with an 8px `translateX` to 0 over `--dur-base`.
- Close: opacity only, `--dur-fast`, then remove the width in one step.
- Classic isolation: the new motion sits behind an internal constant so the old behaviour can be restored if a regression appears. It is not a user setting. Deprecate and remove the old path later.

## Out of scope

Pre-warming all views, spring physics, `capturePage` snapshot cross-fade, per-frame bounds animation of Gator, removal of classic native-app renderers, browser mode or the `*_pane_mode` rollback flags.

## Testing

Test in the real shell on a separate port and profile, never the user's sessions or the shared `config.json`. Run Electron with the occlusion flags (`--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`). Verify with saved dock history; app.js startup consts stay above the Init block. Existing source-grep tests that touch classic code must keep passing.
