# Marketplace skill controls (finding `H_Malicious_marketplace_or_MCP_skill_execu_03`)

## Goal

Meet the five acceptance criteria of the report's finding `_03` with the smallest change that reuses what already exists (the OS sandbox launcher, the install consent modal, `installed-skills.json`, the CSRF guard). Scope is limited to the criteria. No new policy engine, no admin switch, no persistent-process launcher.

Acceptance criteria (from the report):

1. OS-level sandboxing is implemented and active for all marketplace skills.
2. Skills are restricted to declared filesystem and network permissions.
3. Permission declarations are surfaced to users during installation and require explicit approval.
4. Runtime monitoring logs outbound network destinations for all skills.
5. Suspicious skills can be disabled or quarantined via a kill switch.

"Marketplace skill" means a skill installed through the marketplace (catalog, URL, ZIP or folder install). Native skills and skills the user wrote (`Mine`, `~/.agents/skills`) are not covered.

## What exists today

A marketplace skill is a folder with `SKILL.md` and optionally `tools.py`, `hooks.json`, `bin/`, scripts and `.mcp.json`. It is recorded in `installed-skills.json`. What each part does when loaded:

| Part | How it runs today | Sandboxed today |
|---|---|---|
| `SKILL.md` | Text added to the prompt | Not code |
| Scripts, `bin/` shims | Run only when the model calls `run_python` or `run_shell` | Yes (default-deny, a card per request) |
| `hooks.json` commands | `subprocess.run(shell=True)` as the user before every email and Teams send (`hooks/executor.py`) | **No** |
| `tools.py` | Imported in-process (`marketplace/loader.py`), full app privileges and secrets in memory | **No, and it cannot be** |
| `.mcp.json` | Never started: `mcp.manager.register_plugin_servers` does not exist, so the loader skips it | Not applicable |

Other gaps: no skill declares permissions; only plugin bundles get a consent step (`consent`), plain skill, ZIP and folder installs install directly; there is no disabled state (only uninstall); there is no outbound-destination logging; the marketplace routes have no CSRF guard.

## Design

### 1. Declared permissions (criterion 2 and 3)

An optional `permissions` block in the `SKILL.md` frontmatter or `plugin.json`:

```yaml
permissions:
  filesystem: ["~/Documents/reports"]   # paths the skill's hooks may read
  network: ["api.example.com"]          # hosts the skill says it needs
```

A missing block means no filesystem access and no network. A malformed block (not a list of strings, an entry over 200 characters, more than 20 entries) is treated as "no permissions" and the install card says the declaration was invalid. The declaration is data, not a grant: it is shown to the user and enforced as in section 3.

### 2. Install approval on every install path (criterion 3)

Every marketplace install path returns `consent_required` until the client resubmits with `consent=True`, and nothing is written to the skills folder before then. The paths are catalog plugin, GitHub URL (plugin and plain skill), raw `SKILL.md` or ZIP URL, and local ZIP or folder. The existing plugin consent (`consent`, `resolved_ref`) is reused and extended; plain installs gain the same step. One function, `summarize_package(files)`, reads the fetched content and returns what the card shows:

- the declared filesystem paths and network hosts (or "none declared");
- whether it contains `tools.py`: "Runs inside AI Gator with full access to this app, including your saved credentials. It is not sandboxed.";
- whether it contains hook commands, each command shown: "Runs these commands on your computer before an email or Teams message is sent, in a restricted sandbox";
- whether it ships `bin/` programs or MCP server entries (shown as a line each).

The existing consent modal (`static/marketplace-pane.js`) shows this summary with Approve and Cancel. The approved declaration is stored on the skill's `installed-skills.json` entry (`permissions`, `approved_at`). A reinstall or update goes through the card again, so a changed declaration is seen again.

### 3. Enforcement (criteria 1 and 2)

- **Hooks run in the OS sandbox.** `fire_event` runs each hook command through `launch_sandboxed` instead of `shell=True`: working folder is the skill's own folder, read access to that folder and to the declared filesystem paths (the never-grantable deny list in `web/sandbox/paths.py` still applies and removes any declared path under it), no write access, and network only if the user approved a non-empty `network` declaration (the launcher is all-or-nothing, so the declared hosts are shown, not enforced, as with `run_python`). The existing 30-second timeout and the exit-code rule (non-zero blocks the send) are unchanged. If the sandbox cannot start the hook fails closed (blocked, with the reason), as the hook gate already does for errors. A hook that needs more than this is refused rather than widened.
- **Scripts and `bin/` shims** already run only through `run_python` and `run_shell`, which are default-deny with a card per request and are stricter than any declaration. Declared paths do not widen them.
- **`tools.py` is not sandboxed.** The criterion cannot be met for it: it runs in the app's own process. The install card says so plainly (section 2), the report says so, and logging (section 5) covers it. This is the one stated shortfall of criterion 1.

### 4. Kill switch (criterion 5)

A per-skill `disabled` flag in `installed-skills.json`, set by `POST /api/marketplace/disable/{skill_id}` and cleared by `POST /api/marketplace/enable/{skill_id}`. While disabled the skill's prompt is not loaded, its tools are unloaded and `load_skill_tools` refuses to load them, its `bin/` is off the PATH, its MCP servers are stopped, and its hooks do not run. It survives restart. The flag keeps the files on disk (a quarantine in practice) so the user can inspect it. The marketplace pane shows a Disable / Enable control on each installed marketplace skill. Uninstall is unchanged.

The install, local install, disable and enable routes get the existing `verify_csrf` guard. This is not a separate finding here: without it a web page could forge the install approval and defeat criterion 3.

### 5. Outbound monitoring (criterion 4)

A small audit hook (`sys.addaudithook`, event `socket.connect` and `socket.getaddrinfo`) logs `skill-outbound skill=<id> dest=<host>:<port>` when the connection is made by a marketplace skill's `tools.py` handler. `load_skill_tools` wraps each handler so the skill id is set (a context variable) for the duration of the call; the hook reads it. Hook commands run in the sandbox log a line with the skill id, the command and whether network was allowed. This is logging, not blocking.

## Out of scope

- A persistent sandboxed launcher for stdio MCP servers (no marketplace MCP server starts today; a future start must go through the sandbox, noted in the report).
- An admin policy switch for `tools.py`, a separate extra consent for it, enforcing declared network hosts, signature checks, per-host egress filtering.
- Quarantine states beyond disabled, a central audit log store, alerting.
- CSRF on marketplace routes other than install, local install, disable and enable.

## Testing

- Server: manifest parsing (valid, missing, malformed, over limits); `summarize_package` for each content kind; every install path returns `consent_required` and writes nothing before consent, and installs after; stored `permissions` and `approved_at`; hooks run through the launcher with the right read paths and network flag, deny-listed declared path removed, sandbox failure blocks, non-zero exit still blocks; `disabled` skill: prompt absent, tools unloaded and refused on load, hooks skipped, survives reload, enable restores; destination logged for a `tools.py` handler that connects out and not logged for a native tool; the four routes reject a missing CSRF token.
- UI: the consent modal shows the summary lines, and Approve sends `consent=True`; the Disable / Enable control calls the routes.
- Run the full suite, since existing install tests that expect a direct install of a plain skill will need the consent step.

## Known limits to state in the report

- `tools.py` runs unsandboxed with the app's full privileges. A malicious `tools.py` can read the app's credentials. The install card warns, the user approves, and outbound connections it makes in-process are logged. Criterion 1 is partially met for this reason.
- Declared network hosts are shown and logged, not enforced; a hook with an approved network declaration can reach any host.
- Declared filesystem paths apply to hooks only; scripts are governed by the code runner sandbox cards, and `tools.py` has no restriction.
- Outbound logging covers connections made in the app's own process by a marketplace handler. It does not cover subprocesses started by a handler, nor native code, and it records, not blocks.
- Marketplace MCP servers do not start today; this is unchanged, and no control was built for them.
- Not exercised on macOS or Linux.
