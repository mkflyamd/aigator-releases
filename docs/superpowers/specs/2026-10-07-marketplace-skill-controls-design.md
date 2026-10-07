# Marketplace skill controls (finding `H_Malicious_marketplace_or_MCP_skill_execu_03`)

**Status:** Implemented on branch `security/threatmodel-remediation`. Plan: `docs/superpowers/plans/2026-10-07-marketplace-skill-controls.md`.

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
| Scripts, `bin/` shims | Only inside the sandbox, when the model calls `run_python` or `run_shell` (or inside a skill's tool or hook run), and only if the sandbox can read the folder | Yes (default-deny, a card per request) |
| `hooks.json` commands | `subprocess.run(shell=True)` as the user before every email and Teams send (`hooks/executor.py`) | **No** |
| `tools.py` | Imported in-process (`marketplace/loader.py`), full app privileges and secrets in memory | **No** (this design moves it into the sandbox, section 3) |
| `.mcp.json` (plugin bundles only) | At install, `installer._register_plugin_mcp_servers` registers each server in `mcp.manager` (`register_plugin_mcp_server`). A stdio server is started as a pooled child process (`mcp/stdio_client.py`) with the user's privileges, unless a `{PLACEHOLDER}` secret is missing, in which case it is saved disabled | **No** (stays unsandboxed, see Out of scope) |

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
- whether it contains `tools.py`: "Adds tools the assistant can call. They run in a restricted sandbox, with the folders and network access shown above.";
- whether it contains hook commands, each command shown: "Runs these commands on your computer before an email or Teams message is sent, in a restricted sandbox";
- whether it ships `bin/` programs or MCP server entries (shown as a line each).

The existing consent modal (`static/marketplace-pane.js`) shows this summary with Approve and Cancel. The approved declaration is stored on the skill's `installed-skills.json` entry (`permissions`, `approved_at`). A reinstall or update goes through the card again, so a changed declaration is seen again.

### 3. Enforcement (criteria 1 and 2)

- **Hooks run in the OS sandbox.** `fire_event` runs each hook command through `launch_sandboxed` instead of `shell=True`: working folder is a fresh run folder under the app's outputs folder (the sandbox always makes the working folder writable, so it is never the skill folder), read access to the skill folder and to the declared filesystem paths (the never-grantable deny list in `web/sandbox/paths.py` still applies and removes any declared path under it), no write access beyond the throwaway run folder, and network only if the user approved a non-empty `network` declaration (the launcher is all-or-nothing, so the declared hosts are shown, not enforced, as with `run_python`). The existing 30-second timeout and the exit-code rule (non-zero blocks the send) are unchanged. If the sandbox cannot start the hook fails closed (blocked, with the reason), as the hook gate already does for errors. A hook that needs more than this is refused rather than widened.
- **Scripts and `bin/` shims** already run only through `run_python` and `run_shell`, which are default-deny with a card per request and are stricter than any declaration. Declared paths do not widen them.
- **`tools.py` runs in the sandbox, one call at a time, and is never imported into the app.** The handler contract is plain data (`TOOL_DEFS`, `TOOL_STATUS`) plus callables that take a dict or keyword arguments and return a dict, so it crosses a process boundary as JSON.
  - *Load:* `load_skill_tools` launches a short sandboxed run of a small runner script shipped with the app (copied into the run folder). The runner imports `tools.py`, checks the same contract as `validate_tool_contract`, and prints `TOOL_DEFS`, `TOOL_STATUS` and the handler names as JSON. The app registers the namespaced tool definitions as today, but each registered handler is a stub in the app process.
  - *Call:* the stub writes the arguments to a file in the run folder and launches the runner again with the tool name. The runner calls the handler (awaiting it if async) and prints the JSON result. Non-JSON results, a crash or a timeout come back as a tool error. The sandbox request uses the existing pieces: `build_env` (no API keys), the skill folder and interpreter as runtime paths, read paths from the approved `filesystem` declaration (deny list applied), the run folder as the only writable path, `network` true only for an approved non-empty `network` declaration, and the code runner timeout. If the sandbox is unavailable the call fails closed.
  - *Speed:* a no-op sandboxed call measured about 0.6 s on Windows (0.09 s unsandboxed), plus the handler's own imports. Marketplace tools are loaded only at install and at Enable (never at app start, as today), and each load costs one describe run, so app start spawns no process. A test fails if a no-op handler call takes over 2 s. A persistent runner is out of scope.
  - *Limits of this route:* handlers can no longer reach app state, saved credentials or other app modules; a `tools.py` that imports `shared` or other app code, streams results, or returns non-JSON fails with a clear error at load or call time. Each call costs one process start. Native skills are unchanged.

### 4. Kill switch (criterion 5)

A per-skill `disabled` flag in `installed-skills.json`, set by `POST /api/marketplace/disable/{skill_id}` and cleared by `POST /api/marketplace/enable/{skill_id}`. While disabled the skill's prompt is not loaded, its tools are unloaded and `load_skill_tools` refuses to load them, its `bin/` is dropped from the PATH of sandboxed runs (a skill's `bin/` is never on the app's own PATH), its bundle MCP connections are stopped (`remove_plugin_mcp_servers`, which also ends the pooled process; Enable registers them again from the files on disk), its slash commands are deregistered (and registered again on Enable), and its hooks do not run. It survives restart. The flag keeps the files on disk (a quarantine in practice) so the user can inspect it. The marketplace pane shows a Disable / Enable control on each installed marketplace skill. Uninstall is unchanged.

The install, local install, disable and enable routes get the existing `verify_csrf` guard. This is not a separate finding here: without it a web page could forge the install approval and defeat criterion 3.

### 5. Outbound monitoring (criterion 4)

- *`tools.py`:* the sandboxed runner installs a `sys.addaudithook` (events `socket.connect` and `socket.getaddrinfo`) before importing `tools.py`, and writes each destination to a marker line on stderr. The app reads those lines after the call and logs `skill-outbound skill=<id> dest=<host>:<port>`. This covers every connection Python code makes inside the handler, including libraries.
- *Hooks and scripts:* every sandboxed launch logs `skill-launch skill=<id> kind=<hook|tool> network=<true|false> declared_hosts=<list>`. The real destinations of a shell command's own subprocesses are not observed.
- This is logging, not blocking. A skill that sets its own audit hook cannot be assumed to be logged fully, but the sandbox, not the log, is the control.

## Out of scope

- A persistent sandboxed launcher for stdio MCP servers. Bundle MCP servers keep starting as today, unsandboxed; the install card shows each server's exact command, and the kill switch stops them.
- A persistent runner process per skill (each call starts a fresh sandboxed process), streaming or app-state access for marketplace handlers, a separate extra consent for `tools.py`, enforcing declared network hosts, signature checks, per-host egress filtering.
- Quarantine states beyond disabled, a central audit log store, alerting.
- CSRF on marketplace routes other than install, local install, disable and enable.

## Testing

- Server: manifest parsing (valid, missing, malformed, over limits); `summarize_package` for each content kind; every install path returns `consent_required` and writes nothing before consent, and installs after; stored `permissions` and `approved_at`; hooks run through the launcher with the right read paths and network flag, deny-listed declared path removed, sandbox failure blocks, non-zero exit still blocks; `tools.py`: describe run returns defs and status, a bad contract is refused, a sync and an async handler return JSON through the sandbox, the handler cannot read a secrets path or the app's environment keys, a handler that writes outside the run folder fails, network is off unless approved, a handler that imports `shared` gives a clear error, sandbox unavailable fails closed, a crash or timeout is a tool error; `disabled` skill: prompt absent, tools unloaded and refused on load, hooks skipped, survives reload, enable restores; a connection made inside a `tools.py` handler produces a `skill-outbound` log line and a native tool does not; the four routes reject a missing CSRF token.
- UI: the consent modal shows the summary lines, and Approve sends `consent=True`; the Disable / Enable control calls the routes.
- Run the full suite, since existing install tests that expect a direct install of a plain skill will need the consent step.

## Known limits to state in the report

- `tools.py`, hooks and scripts run in the OS sandbox, and `bin/` shims can only be reached from sandboxed runs, so criterion 1 is met for them. Stdio MCP servers shipped in a plugin bundle are not sandboxed (the launcher is one-shot, not persistent): criterion 1 is partially met overall. The user sees each server's exact command before approving, and the kill switch stops them.
- Network access is all-or-nothing per run: declared hosts are shown and logged, not enforced, so a skill with an approved network declaration can reach any host. Criterion 2 is met for the filesystem and for "no network unless declared and approved", and is partially met for per-host network limits.
- Declared filesystem paths are read-only grants for hooks and `tools.py`; scripts are governed by the code runner sandbox cards.
- Existing marketplace `tools.py` files that import app code (`shared` and similar), stream results or return non-JSON will stop working and report why. Each tool call starts a new process, so it is slower than before.
- Outbound logging records destinations of Python connections made inside a `tools.py` handler; for hooks and scripts it records the launch and the network flag, not the destinations of their subprocesses. It records, not blocks, so criterion 4 is met for `tools.py` and partially met for hooks and scripts.
- Disable on a plugin bundle removes its MCP connections with `remove_plugin_mcp_servers`, which also wipes the credentials saved for them; Enable registers the servers again and the user must re-enter any secrets.
- `tools.py` sandboxing covers standalone marketplace skills. A plugin bundle's `tools.py` is not loaded by the app today, so it never runs; the bundle's hooks and MCP servers are covered as described above.
- A skill installed before this change has no recorded approval, so it gets no filesystem or network grant until it is reinstalled through the card.
- Not exercised on macOS or Linux.
