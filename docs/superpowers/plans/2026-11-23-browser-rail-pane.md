# Browser rail pane implementation plan

Spec: `docs/superpowers/specs/2026-11-23-browser-rail-pane-design.md`. Branch `feat/browser-rail-pane`.

1. **Search engines.** Add `shell/search-engine.js` with tests (`tests/search-engine.test.js`): table,
   default Bing, `createStore(file)` get/set/persist, rejects unknown ids, tolerates a corrupt file.
2. **Address input.** Add an optional search-URL argument to `resolveAddressInput` and
   `loadAddressInput`; extend `tests/address-input.test.js`.
3. **Links stay in pane.** Add `openLinksInPane` to `applyNavigationPolicy`; test it with a stub view
   in `tests/navigation-policy-browser.test.js`.
4. **Shell wiring.** `main.js`: engine store, IPC handlers, `browser` pane creation in
   `external-pane:show`, engine passed to the address bar. `preload.js`: two bridge calls.
5. **Rail and pane routing.** `app.js`: `_browserPane` flag, `_TP_SKILL_IDS`, `DEFAULT_DOCK_FAVS`,
   `_isShellWebPaneSkill` helper at the seven call sites; `third-pane.js` branch. Test with a vm
   harness in `tests/rail_browser.test.js`.
6. **Settings.** Search-engine select in the Web Apps section, wired to the bridge.
7. **Verify in the real shell** on a test instance (port 8002, debug 9223): click, navigate, search,
   engine change, links, light and dark. Fix what it shows.
8. **Commit** in logical commits, no Co-Authored-By. Tell MergeBrain the branch and SHA.
