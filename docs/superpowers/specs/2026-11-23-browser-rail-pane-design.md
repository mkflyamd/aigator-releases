# Browser on the right rail

Stacked on #161 (`feat/address-bar-star`).

## Goal

The Browser item on the right rail opens a general-purpose browser pane beside Gator. Clicking it
today does nothing because `browser` is only an agent chip, not a pane. Users can open any site,
which covers apps Gator has no dedicated pane for.

## Behavior

- **Default rail.** `browser` joins `DEFAULT_DOCK_FAVS` after `code_agent`. It stays favoritable and
  unfavoritable from the launcher popover. Users with a saved rail keep their own set.
- **Click.** Opens the shell pane `browser` in the same split layout as every other native pane
  (toolbar with back, forward, reload and address bar). Clicking it again while it is open returns to
  the start page. Switching away and back keeps the page and its sign-ins (persistent partition).
- **Start page.** The home page of the chosen search engine.
- **Search.** Text typed in the address bar that is not an address is searched with the chosen
  engine. The choice applies to every pane's address bar. Engines: Bing (default), Google,
  DuckDuckGo. The choice is saved in the shell profile and changed under Settings, Web Apps.
- **Links.** A browser keeps navigation in the pane. In this pane, links, `target=_blank` and
  `window.open` load in the pane instead of the system browser. Sign-in popups keep their existing
  child-window handling.
- **Theme.** Toolbar, rail icon and Settings control follow Gator's light and dark theme.
- **Not included.** Tabs, bookmarks, history UI, starring a page as an app.

## Components

- `shell/search-engine.js` (new): engine table, default, JSON file store. Pure, no Electron imports.
- `shell/address-input.js`: `resolveAddressInput` and `loadAddressInput` take the search URL;
  default stays Bing so other callers and tests are unchanged.
- `shell/navigation-policy.js`: new option `openLinksInPane`.
- `shell/main.js`: `createGenericPane` accepts `openLinksInPane`; `external-pane:show` creates the
  `browser` pane on demand; IPC `search-engine:get` and `search-engine:set` (id validated against
  the table; changing it updates the browser pane's start page); the address bar passes the engine.
- `shell/preload.js`: `getSearchEngine`, `setSearchEngine`.
- `web/static/app.js`: `browser` skill gets `_browserPane`, joins `_TP_SKILL_IDS` and
  `DEFAULT_DOCK_FAVS`; one helper `_isShellWebPaneSkill` replaces the repeated
  `_customApp || _googleService` checks.
- `web/static/third-pane.js`: the custom-app branch of `openThirdPaneImpl` also serves `browser`.
- `web/static/index.html` and `app.js`: search-engine select in Settings.

No new backend routes, so no CSRF changes.

## Testing

- Unit: engine table and store, address input with a custom search URL, navigation policy
  `openLinksInPane`, dock default and helper.
- Real shell: click Browser on the rail, confirm the pane opens, navigate by URL and by search,
  change engine, confirm links stay in the pane, check light and dark.
