# Skill Sharing: Share and Install UI (Plan 1B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Mine skill's Share button offers "Share through OneDrive" (people, link, message text to copy) and keeps "Download file" for anyone who needs it. A recipient pastes a share link in Marketplace, reviews the skill, and installs it.

**Architecture:** One new browser module, `web/static/skill-sharing.js`, owns the Share modal and the link review modal. `marketplace-pane.js` loads it, passes in its own helpers (`_postJson`, `_showAlert`, `_errorMessage`, `_appendPermissionList`, the download function, `refresh`), and calls it from the Mine row's Share button and the Import tab. The only backend change is that the publish route also returns the message text.

**Tech Stack:** FastAPI, pytest, vanilla JS, node `assert` + `vm` tests with the lightweight DOM shim used by `tests/marketplace_p0_dom_render.test.js` (jsdom is not available). JS tests run with `cd shell && node --test ../tests/<file>.test.js`.

**Stacked PR:** This plan lives on branch `feat/skill-sharing-ui`, created from `feat/skill-sharing` (PR 124, which is stacked on `feat/file-transfer`, PR 103). Open the PR with base `feat/skill-sharing`. When PR 124 retargets, this branch is rebased the same way (`git rebase --onto <new base> feat/skill-sharing feat/skill-sharing-ui`).

## Global Constraints

- All LLM and Graph access stays behind the existing routes; this plan adds no new route.
- Email, Teams and Slack messages are never sent automatically. The UI only shows message text for the user to copy. Drafts come in plan 2.
- Fake credentials in tests: only `aigator-fake-api-key`.
- The project is called "AI Gator", never "POC".
- No `Co-Authored-By` lines in commit messages.
- The existing download behaviour (`GET /api/marketplace/export/{skill_id}` saved as `<skill-id>.skill`) must keep working, reachable from the Share modal.
- Build DOM with `createElement` and `textContent`. Never put server text into `innerHTML`.
- People are entered as work email addresses, comma or whitespace separated. Directory search is not part of this plan.

---

## Task 1: Publish also returns the message text

**Files:**
- Modify: `web/skills/_sharing/publisher.py` (the `publish` return value)
- Test: `tests/skill_sharing/test_publisher.py`, `tests/skill_sharing/test_routes.py` (whichever already asserts the publish response shape)

**Interfaces:**
- Consumes: `messages.share_message(title, author, description, link, web_url="") -> str`.
- Produces: `publish(...)` result gains `"message": str`, built with `share_message(title, author, description, link, web_url)`. `title` and `description` come from the new `manifest` when a version was just written, or from `doc` (`doc.get("title")`, `doc.get("description")`, falling back to `skill_id` and `""`) when `reused` is true.

- [ ] **Step 1: Failing tests.** In `test_publisher.py`: a first publish returns a `message` that contains the link, the author name and the skill title; a reused publish (same files twice) returns a message with the same link. In the routes test: the publish response JSON has a non-empty `message`.
- [ ] **Step 2: Run them, confirm they fail** (`.venv/Scripts/python -m pytest tests/skill_sharing -q -p no:cacheprovider`).
- [ ] **Step 3: Implement** the `message` key. Keep `link` and `web_url` in the result.
- [ ] **Step 4: Run `tests/skill_sharing` and `tests/test_csrf_route_inventory.py`; all pass.**
- [ ] **Step 5: Commit** `Return the share message text from publish so the UI can show it`.

---

## Task 2: Share modal (OneDrive and download)

**Files:**
- Create: `web/static/skill-sharing.js`
- Modify: `web/static/index.html` (add `<script src="/static/skill-sharing.js"></script>` immediately before the `marketplace-pane.js` tag at line ~2043)
- Modify: `web/static/marketplace-pane.js` (Share button handler at `_shareMineSkill`, ~line 2427; Mine row chip near line 1078)
- Modify: `web/static/style.css` (small additions next to the `.mp-modal*` rules)
- Modify: `tests/marketplace_share.test.js` (the existing test asserts the Share button downloads directly; update it to the new flow)
- Test: `tests/skill_sharing_ui.test.js` (new)

**Interfaces:**
- Produces, in `skill-sharing.js`, an IIFE assigning `window.SkillSharing = { openShareModal, parseEmails, shareErrorText }`, also `module.exports` when `typeof module !== 'undefined'` so node tests can load it.
  - `parseEmails(text) -> { emails: string[], bad: string[] }`: split on commas, semicolons, whitespace; lower-case; drop empties and duplicates; an address is valid when it matches `^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$` (the backend rule in `web/routes/skill_sharing.py`).
  - `shareErrorText(resp, body) -> string`: the message from `body.detail.message` when `detail` is an object; the string `detail` when it is a string; for an array `detail` (FastAPI validation) `"Check the email addresses and try again."`; otherwise `"Could not share this skill. Try again."`.
  - `openShareModal(skillId, deps)`, where `deps = { postJson(url, payload) -> Promise<{resp, body}>, downloadSkill(skillId) -> Promise<void>, showAlert(msg, kind), refresh() }`.
- Consumes: `POST /api/skills/share/publish` with `{skill_id, people}`; response `{skill_id, version, reused, digest, folder, link, web_url, message}`.

Behaviour of `openShareModal` (reuse the existing `mp-modal-overlay` / `mp-modal` / `mp-modal-title` / `mp-modal-body` / `mp-modal-actions` classes and `ap-card-btn` buttons; modal has `role="dialog"`, `aria-modal="true"`, labelled by its title, closes on Escape and on Cancel):

1. Form view. Title `Share "<skillId>"`. A labelled text input "Share with (work email addresses)". Hint text: "They can use the skill but not change it. Nobody is emailed; you copy the message and send it yourself." Buttons: Cancel, "Download file instead", "Share" (primary).
2. "Download file instead" closes the modal and calls `deps.downloadSkill(skillId)`.
3. "Share" validates with `parseEmails`: no addresses, or any `bad` entries, shows an inline error naming the first bad entry and does not call the server. Otherwise it disables both buttons, shows "Sharing...", calls `deps.postJson('/api/skills/share/publish', { skill_id, people: emails })`. A non-ok response shows `shareErrorText` inline, re-enables the buttons and keeps the typed text.
4. Result view on success. Heading `Shared as version <N>` (or `Already shared, no changes since version <N>` when `reused`). Line `Access granted to <emails joined by ", ">`. A read-only textarea holding `message`. Buttons: "Copy message" (uses `navigator.clipboard.writeText`, button text changes to "Copied"), "Copy link", "Open in OneDrive" (an `<a target="_blank" rel="noopener">` shown only when `web_url` starts with `https://`), "Done". Done closes the modal and calls `deps.refresh()`.
5. Only one Share modal at a time; opening a second removes the first.

`marketplace-pane.js` changes:

- Rename the download body of `_shareMineSkill` to `_downloadMineSkill(skillId)` unchanged. `_shareMineSkill(skillId)` becomes `window.SkillSharing.openShareModal(skillId, { postJson: _postJson, downloadSkill: _downloadMineSkill, showAlert: _showAlert, refresh })`. If `window.SkillSharing` is missing, fall back to `_downloadMineSkill`.
- Update the Share button tooltip (line ~1081) to "Share with colleagues through OneDrive, or download a file".
- Next to the Edit button on a Mine row, when `skill.published_version` is a positive integer, show a small chip `Shared · v<N>` (class `mp-share-chip`). The installed-list route already returns every state key.

- [ ] **Step 1: Failing tests** in `tests/skill_sharing_ui.test.js`: `parseEmails` (commas, semicolons, whitespace, case, duplicates, a bad entry); `shareErrorText` for the four shapes; `openShareModal` through the DOM shim: Share with no address calls nothing and shows an error, Share with two addresses calls `postJson` once with `{skill_id, people}` and renders the result view with the message and the copy buttons, a failed response shows the message and keeps the input, "Download file instead" calls `downloadSkill` and closes. Update `tests/marketplace_share.test.js`: the Share button still has `data-action = 'share-mine'`, `_downloadMineSkill` still fetches `'/api/marketplace/export/'` and sets `a.download = skillId + '.skill'`, and `_shareMineSkill` opens `SkillSharing.openShareModal`.
- [ ] **Step 2: Run, confirm failure** (`cd shell && node --test ../tests/skill_sharing_ui.test.js ../tests/marketplace_share.test.js`).
- [ ] **Step 3: Implement** `skill-sharing.js`, the `index.html` tag, the `marketplace-pane.js` changes and the CSS.
- [ ] **Step 4: Run the new and existing marketplace JS tests** (`../tests/marketplace_*.test.js` and `../tests/skill_sharing_ui.test.js`); all pass.
- [ ] **Step 5: Commit** `Add a Share modal that publishes to OneDrive and keeps the file download`.

---

## Task 3: Review and install from a share link

**Files:**
- Modify: `web/static/skill-sharing.js` (add `openLinkReview`)
- Modify: `web/static/marketplace-pane.js` (Import tab section, ~line 1296 `_renderImport`)
- Modify: `web/static/style.css`
- Test: `tests/skill_sharing_ui.test.js`

**Interfaces:**
- Produces: `window.SkillSharing.openLinkReview(link, deps)` and `SkillSharing.extractLink(text) -> string` (returns the first `aigator://share?d=...` token found in pasted text, or `""`). `deps = { postJson, showAlert, errorMessage, appendPermissionList(container, summary), onInstalled(result), refresh() }`.
- Consumes: `POST /api/skills/share/review` with `{link}`, returns `{skill_id, title, description, author, version, latest, created_at, digest, has_scripts, requested_tools, summary, collision}`; `POST /api/skills/share/install` with `{link, version, digest}`, returns the installer result (`{ok, skill_id, ...}`) or an error whose `detail` is `{error, message}`.

Behaviour:

1. Import tab: below the local-file section (and also when `gatorShell` is absent), a divider "or open a skill someone shared with you", an input with placeholder `aigator://share?d=...` labelled "Share link", and a "Review" button. Review calls `extractLink(input)`; empty shows "Paste the aigator://share link you were sent." in the existing `#mp-import-error` area; otherwise calls `openLinkReview(link, deps)`.
2. `openLinkReview` posts to `/api/skills/share/review`. On failure shows `shareErrorText` through `showAlert(..., 'error')` and opens nothing.
3. Review modal (dialog semantics as in Task 2). Title `Review "<title>"`. Body: description; `Shared by <author>, version <version>` plus `Newer version <latest> is available` when `latest > version`; "Contains scripts: yes/no" from `has_scripts` (yes is shown with the emphasis class used for warnings in the permission card); the permission lines via `appendPermissionList(body, summary)`; a "Details" toggle revealing the fingerprint (`digest`); the sentence "Nothing is installed until you choose Install." When `collision` is non-empty show the matching sentence (`mine`: "You already have a skill of your own with this name.", `installed`: "A skill with this name is already installed.", `native`: "This name is used by a built-in skill.") and disable Install.
4. Install posts `{link, version, digest}` to `/api/skills/share/install`. On success: `showAlert('Installed "<title>".', 'success')`, call `deps.onInstalled(result)` and `deps.refresh()`, close. On failure keep the modal open and show the message inline (`content_changed` already tells the user to review again).
5. `marketplace-pane.js` wires `onInstalled` the way the local-file install does after success (`window.registerUserSkill(skill.id, skill.name, 'Community')` when that function exists, then `_handleInstallOutcome(true, data, skill)` equivalent). Read `_pickLocalSkill` and `_handleInstallOutcome` and reuse, not duplicate.

- [ ] **Step 1: Failing tests:** `extractLink` (plain link, link inside a sentence, trailing punctuation, none); review modal renders title, scripts yes and no, permission lines through the injected `appendPermissionList`, newer-version line, collision disables Install; Install posts exactly `{link, version, digest}` from the review response; a failed review opens no modal; a failed install keeps the modal open with the message; Cancel posts nothing.
- [ ] **Step 2: Run, confirm failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all marketplace and sharing JS tests; all pass.** Also run `.venv/Scripts/python -m pytest tests/skill_sharing tests/test_csrf_route_inventory.py -q -p no:cacheprovider`.
- [ ] **Step 5: Commit** `Add a link review and install flow for shared skills`.

---

## Final check (controller)

Start the dev server, open Marketplace, and drive both modals in a browser with the three `/api/skills/share/*` responses stubbed: Share with a bad address, Share with two addresses (result view and copy), Download file instead, paste a link and review with and without scripts and with a collision, Install. Real-tenant testing of OneDrive itself stays on the throwaway branch.
