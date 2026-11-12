# Run a dev server outside the sandbox, with approval

## Use case
A user asks AI Gator to edit a local web project (for example a Slidev deck in
`Documents\Gator\gator-source`) and preview it live. Today that cannot work:

- `run_shell(background=true)` is refused while the sandbox is on.
- A server started inside the Windows AppContainer sandbox cannot be reached
  from the browser (loopback isolation).
- Node tools hang in the sandbox when they start child processes with piped
  output, so builds of real projects (Docusaurus, Slidev) fail or need
  tool-specific workarounds.

## Desired experience
1. The user asks "start the deck so I can preview it".
2. AI Gator shows an approval card. It has the exact command, the folder, and
   the line "Runs outside the sandbox with your full access". The buttons are
   **Run** and **Deny**.
3. On Run, the server starts. A status card shows
   "Running at http://localhost:3030" with **Open** and **Stop**.
4. The user edits slides through AI Gator and the page reloads live.
5. Closing AI Gator stops the server.

## Rules
1. **Scope.** The path is used only for `run_shell(background=true)` while the
   sandbox is on. Foreground commands stay sandboxed exactly as today.
   `background=true` combined with `extra_read_paths`, `extra_write_paths` or
   `network_hosts` is refused, because those only apply to sandboxed runs.
2. **Ask every time.** Each start needs a new approval. There is no Always
   allow and no Allow in this tab. The approval is for this tab, one use, and
   this exact command, folder and shell. Gator runs exactly the approved
   command.
3. **Admin policy.** If `policy.require_sandbox` is true (this includes the
   fail-closed policy), the call is refused and no card is shown. The message
   tells the user to start the server in their own terminal.
4. **Folder taint.** The call is refused, with no card, if AI Gator could have
   planted code in the folder that the server would run. Taint is recorded
   when:
   - a sandboxed `run_shell` or `run_python` run had write access to the
     folder, a folder inside it, or a folder that contains it (this includes
     a sandboxed `npm install`); or
   - `write_file` or `edit_file` changed any file in that folder tree other
     than a content file.

   Content files are the only files that do not taint: `.md`, `.txt`, `.css`,
   images (`.png .jpg .jpeg .gif .webp .svg .ico`) and fonts
   (`.woff .woff2 .ttf .otf`). Everything else taints (an allowlist, so a
   new file type fails safe). Editing `slides.md`, CSS and images keeps the
   Slidev flow working.

   Taint is **persistent**. It is stored in a small JSON file in the AI Gator
   data folder (where `bg-pids.json` lives) and survives restarts, so a file
   planted in one session is still refused in the next. A missing file means
   no taint. An unreadable or corrupt file means every folder is treated as
   tainted (fail closed). There is no UI to clear it in v1; deleting the file
   clears it.

   The refusal message tells the user to run the install and the server in
   their own terminal.
5. **Steering.** The `run_shell` description tells the model to inspect a
   project with `list_dir`, `read_file` and `grep_files`, to change project
   files with `write_file`/`edit_file`, and to use `run_shell` with the
   project as cwd only for install and build. Any sandboxed shell run with the
   project as cwd taints it, even a read-only `dir`, because the project is
   always granted write access (`_run_sandboxed`).
6. **Unattended runs.** Scheduled and other unattended runs are refused for
   this path. An approval needs a human in a tab.
7. **Command shown in full.** The card shows the whole command. A command
   longer than the card's limit (2000 characters) is refused instead of
   truncated, so the user never approves text they cannot see.
8. **Lifetime.** All background processes started by AI Gator are stopped
   when AI Gator closes. The existing cap (10), orphan cleanup at startup,
   `check_shell_process` and `stop_shell_process` stay as they are.
9. **Environment.** The background process gets the user's environment minus
   AI Gator's own secrets and tokens.
10. **Telemetry.** Metadata only, through `sandbox.telemetry_record` with
    `level="outside"` and the decision in `approval` (`requested`, `approved`,
    `denied`, `refused`). No command, paths or output are recorded.

Out of scope for v1: sandboxed build plus static preview, port management,
and a UI to clear taint.

## Design

### Taint tracking — `web/sandbox/taint.py` (new)
- `mark_folder(path)`: records a folder that a sandboxed run could write.
- `mark_file(path)`: records the file's parent folder unless the file is a
  content file (rule 4).
- `is_tainted(folder) -> bool`: true if any recorded folder is equal to,
  inside, or contains `folder` (`is_within` both ways, `normcase`), or if the
  store is unreadable.
- Persistence: load on first use, write through on each new entry (atomic
  replace). Entries are normalized absolute folder paths. `_reset()` clears
  the in-memory copy and the file for tests.

Callers:
- `shell_runner/tools.py::_run_sandboxed` marks every path in `write_paths`
  (the project cwd and `extra_write_paths`) right before `launch_sandboxed`.
- `code_runner/tools.py` marks its granted write paths at the same point.
- `file_ops/tools.py::_tool_write_file` and `_tool_edit_file` call
  `mark_file` after a successful write.

### Outside-sandbox gate — `web/skills/shell_runner/tools.py`
`_run_sandboxed` stops refusing `background=True` and calls a new
`_run_outside(cr, command, shell, cwd, policy, context_id)`:

1. Refuse if `policy.require_sandbox` (rule 3), if the run is unattended
   (rule 6), if extra paths or hosts were passed (rule 1), or if the command
   is over 2000 characters (rule 7).
2. Resolve the folder with the existing `_locate_cwd`. An empty cwd is refused
   ("pass the project folder as cwd"). A string error is returned as is.
3. If `taint.is_tainted(folder)`, refuse (rule 4).
4. Look up an approval with `sandbox_approvals.lookup(tab, [], [folder], [],
   tool="run_shell_outside", command=command)`:
   - `approved` → `_spawn_background(command, argv_prefix, shell_used,
     str(folder))` with the scrubbed environment (rule 9). argv_prefix and
     shell_used come from the same shell resolution `_run_unsandboxed` uses.
     The resolution is moved into a small helper and shared.
   - `denied`/`expired` → the existing denied and expired messages.
   - `pending` → return the card again.
   - none → create a request with `tool="run_shell_outside"` and return
     `approval_required` with a `_sandbox_approval` card that has
     `"tool": "run_shell"` and `"outside": true`, so the existing shell
     follow-up text applies.

The taint check in step 3 runs before the approval lookup, so a file written
between the card and the approval still blocks the start.

The request stores the command and the shell separately (a `shell` field on
the request), and `lookup` matches both. The card shows only the command.

### Approval store — `web/sandbox/approvals.py`
- `lookup` matches the exact command (and shell) for `run_shell_outside` too,
  as it does for `run_shell`.
- `decide` forces `scope="once"` for `run_shell_outside`, whatever scope the
  client sent. Without this, a `task` scope would make `_decide` add the
  folder to `task_grants`, which would silently widen later sandboxed runs.

`/api/sandbox/requests/{id}/approve` and `/deny` are reused unchanged
(CSRF-guarded already). No new routes.

### Stop and shutdown — `web/skills/shell_runner/tools.py`, `web/app.py`, `shell/main.js`
- `stop_all_background()` runs the same tree-kill `_tool_stop_shell_process`
  uses on every running entry in `_BG_REGISTRY`. Best effort, never raises.
- `web/app.py` lifespan shutdown calls it after `stop_worker()`.
- Electron stops the backend with `pyProc.kill()` (`shell/main.js`), which on
  Windows is a hard kill, so the lifespan hook does not run. Before that
  call, the quit path reads the pid file in the data folder and runs
  `taskkill /PID <pid> /T /F` for each entry that still matches its recorded
  command, using the same match check as `cleanup_orphan_bg_procs`.
- The startup orphan sweep stays as the last backstop.

### Stop route hardening — `web/routes/tasks.py`
`POST /api/shell/background-processes/{pid}/stop`:
- gets `dependencies=[Depends(verify_csrf)]` and is removed from
  `tests/csrf_route_baseline.txt`;
- refuses (404) any pid that is not in `_BG_REGISTRY`. Today
  `_tool_stop_shell_process` will terminate any pid and its children.

`web/static/agents-pane.js` (the existing caller, which posts without a
token) is changed to send the CSRF token the same way the sandbox card does,
including the 403 refresh-and-retry.

### Frontend — `web/static/app.js`
`_showSandboxApproval` checks `card.outside`:
- Title "Run outside the sandbox". It shows the command (monospace), the
  folder, and "Runs outside the sandbox with your full access. AI Gator stops
  it when you close the app."
- The generic "Read and write" rows, the network note and the "Allowed until
  you close this tab" footnote are not shown. After a decision the card says
  "Started" or "Denied".
- Only **Run** (approve, scope once) and **Deny**. No scope choice.

The `run_shell(background=true)` result carries a `url` field. The backend
reads the log for up to 5 s, strips ANSI escape codes, and returns the first
match of `^https?://(localhost|127\.0\.0\.1):\d+` (anchored so a host such as
`localhost.evil.com` cannot match). The result reaches the UI through the
existing tool-result path in the chat stream; the plan names the exact event.

The status card shows "Running at <url>" with **Open** and **Stop**. If there
is no url it says "Running (pid N)" with Stop only. It checks
`GET /api/shell/background-processes` every 5 s while visible and shows
"Stopped" once the pid is gone.

`openExternal` accepts only `https://`, so **Open** uses its own narrow path:
it opens a URL only if it matches the same localhost pattern, in the system
browser through the Electron external-open bridge.

### Docs
`docs/security/threatmodel-remediation.md`, H_06 row: the statement that
background commands are refused is edited to say that a long-running
background command can run outside the sandbox only after a per-run approval
of the exact command and folder, and is refused when the policy requires the
sandbox or when AI Gator has changed or could have changed code in that
folder.

## Tests
- `require_sandbox` → refused, no request created.
- Unattended run → refused. `background=true` with extra paths or hosts →
  refused. A command over 2000 characters → refused.
- Taint: a sandboxed write to the folder, a parent, or a child taints it. A
  `write_file` to `package.json`, `vite.config.ts`, `mkdocs.yml` or `x.mdx`
  taints it. A `write_file` to `slides.md` or `style.css` does not. A
  read-only sandboxed `dir` with the project as cwd taints it.
- Taint persists: after `_reset` of the in-memory copy only, the folder is
  still tainted. A corrupt file → every folder tainted.
- A file written between the card and the approval → the start is refused.
- First call → `approval_required` with `outside: true`. Approve, then a call
  with the same command spawns once, with the cwd equal to the folder. A
  second call asks again.
- A different command, shell or folder after approval → no match, new card.
  An approval for tab A cannot be used by tab B.
- `decide` with `scope="always"` or `"task"` on `run_shell_outside` → stored
  as once. No `task_grants` or `saved_permissions` entry is added.
- The spawned environment has no AI Gator secrets or tokens.
- `stop_all_background` kills every running entry (mock Popen). The stop route
  returns 404 for a pid that is not in `_BG_REGISTRY`.
- `tests/test_csrf_route_inventory.py` passes with the stop route removed from
  the baseline and nothing added.
- URL extraction picks the first localhost URL from a coloured Vite/Slidev
  log, ignores `http://localhost.evil.com:80`, and returns no `url` when
  there is none.
- JS: the outside card renders only Run and Deny and hides the generic rows.
  The status card shows Open only when a URL was found. `agents-pane.js`
  sends the CSRF token on stop.
- Manual: the model explores the deck with `list_dir`/`read_file`, edits
  `slides.md`, starts the server, Open works, live edit shows in the browser,
  Stop works, and closing the app leaves no `node.exe` running. Then write a
  `package.json` with `write_file`, restart AI Gator, and confirm the start is
  refused.
