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
2. **Ask every time.** Each start needs a new approval. There is no Always
   allow and no Allow in this tab. The approval is for this tab, one use, and
   this exact command, folder and shell. Gator runs exactly the approved
   command.
3. **Admin policy.** If `policy.require_sandbox` is true (this includes the
   fail-closed policy), the call is refused and no card is shown. The message
   tells the user to start the server in their own terminal.
4. **Folder taint.** The call is refused, with no card, if earlier in this app
   session AI Gator could have planted code that the server would run:
   - a sandboxed `run_shell` or `run_python` run had write access to the
     folder, a folder inside it, or a folder that contains it; or
   - `write_file` or `edit_file` changed a code or config file in that folder
     tree.

   The refusal message tells the user to start the server in their own
   terminal. Code and config files are files named `package.json`,
   `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `.npmrc`, or any file
   ending in `.js .cjs .mjs .ts .cts .mts .jsx .tsx .vue .svelte .json .py .sh
   .cmd .bat .ps1`, or any file whose name starts with `.env`. Content files
   (`.md`, `.css`, images, fonts) do not taint, so editing slides keeps working.
   Taint is in memory and is cleared when AI Gator restarts. A sandboxed
   `npm install` in the folder also taints it, so for a project without
   `node_modules` the refusal message tells the user to run the install and
   the server in their own terminal.
5. **Steering.** The `run_shell` description tells the model to change project
   files with `write_file`/`edit_file`, not with shell or Python, because a
   sandboxed write to the folder blocks the dev server.
6. **Lifetime.** All background processes started by AI Gator are stopped when
   the app shuts down. The existing cap (10), orphan cleanup at startup,
   `check_shell_process` and `stop_shell_process` stay as they are.
7. **Telemetry.** Metadata only, through `sandbox.telemetry_record`, with mode
   `"outside"` and the decision (`requested`, `approved`, `denied`, `refused`).
   No command, paths or output are recorded.

Out of scope for v1: sandboxed build plus static preview, URL detection beyond
the log, and port management.

## Design

### Taint tracking — `web/sandbox/taint.py` (new)
- `mark_folder(path)`: records a folder that a sandboxed run could write.
- `mark_file(path)`: records the file's parent folder if the file is code or
  config (rule 4).
- `is_tainted(folder) -> bool`: true if any recorded folder is equal to,
  inside, or contains `folder` (`is_within` both ways, `normcase`).
- `_reset()` for tests. Module-level set behind a lock.

Callers:
- `shell_runner/tools.py::_run_sandboxed` marks every path in `write_paths`
  (the project cwd and `extra_write_paths`) right before `launch_sandboxed`.
- `code_runner/tools.py` marks its granted write paths at the same point.
- `file_ops/tools.py::_tool_write_file` and `_tool_edit_file` call
  `mark_file` after a successful write.

### Outside-sandbox gate — `web/skills/shell_runner/tools.py`
`_run_sandboxed` stops refusing `background=True` and calls a new
`_run_outside(cr, command, shell, cwd, policy, context_id)`:

1. If `policy.require_sandbox`, refuse (rule 3).
2. Resolve the folder with the existing `_locate_cwd`. An empty cwd is refused
   ("pass the project folder as cwd"). A string error is returned as is.
3. If `taint.is_tainted(folder)`, refuse (rule 4).
4. Look up an approval with `sandbox_approvals.lookup(tab, [], [folder], [],
   tool="run_shell_outside", command=command)`:
   - `approved` → `_spawn_background(command, argv_prefix, shell_used,
     str(folder))`, where argv_prefix and shell_used come from the same shell
     resolution `_run_unsandboxed` uses. The resolution is moved into a small
     helper and shared.
   - `denied`/`expired` → the existing denied and expired messages.
   - `pending` → return the card again.
   - none → create a request with `tool="run_shell_outside"` and return
     `approval_required` with a `_sandbox_approval` card that has
     `"outside": true`.

The command must be identical between the request and the run. The shell is
part of what is approved: it is included in the stored command string as
`"<shell_used>\n<command>"`.

### Approval store — `web/sandbox/approvals.py`
- `lookup` matches the exact command for `run_shell_outside` too, as it does
  for `run_shell`.
- `decide` forces `scope="once"` for `run_shell_outside`, whatever scope the
  client sent.

`/api/sandbox/requests/{id}/approve` and `/deny` are reused unchanged
(CSRF-guarded already). No new routes.

### Shutdown — `web/app.py`
In the lifespan shutdown, after `stop_worker()`, call a new
`shell_runner.tools.stop_all_background()`. It runs the same tree-kill
`_tool_stop_shell_process` uses on every running entry in `_BG_REGISTRY`. It is
best effort and never raises.

### Frontend — `web/static/app.js`
`_showSandboxApproval` checks `card.outside`:
- Title "Run outside the sandbox". It shows the command (monospace), the
  folder, and "Runs outside the sandbox with your full access. AI Gator stops
  it when you close the app."
- Only **Run** (approve with scope once) and **Deny**. No scope choice.

The background-start tool result gets a small status card. It shows the first
`http://localhost:<port>` or `http://127.0.0.1:<port>` URL in the log tail.
The backend extracts the URL and returns it as `url` in the
`run_shell(background=true)` result, after a short wait for the log (up to 5s).
The card has **Open**, which opens the URL in the system browser through the
existing external-link path, and **Stop**, which calls
`POST /api/shell/background-processes/{pid}/stop`. If no URL is found, the card
says "Running (pid N)" with Stop only. The card checks
`GET /api/shell/background-processes` every 5 s while it is visible and shows
"Stopped" once the pid is gone.

### Stop route hardening — `web/routes/tasks.py`
`POST /api/shell/background-processes/{pid}/stop` is given
`dependencies=[Depends(verify_csrf)]` and removed from
`tests/csrf_route_baseline.txt`.

### Docs
`docs/security/threatmodel-remediation.md`, H_06 row: one factual sentence.
"A long-running background command can run outside the sandbox only after a
per-run approval of the exact command and folder. It is refused when the
policy requires the sandbox or when AI Gator changed code in that folder
during the session."

## Tests
- `require_sandbox` → refused, no request created.
- A tainted folder (sandboxed write to the folder, a parent, or a child, or a
  `write_file` to `package.json` or `vite.config.ts`) → refused. A `write_file`
  to `slides.md` or `style.css` → not tainted.
- First call → `approval_required` with `outside: true`. Approve, then a call
  with the same command spawns once, with the cwd equal to the folder. A
  second call asks again.
- A different command, shell or folder after approval → no match, new card.
- `decide` with `scope="always"` or `"task"` on `run_shell_outside` → stored
  as once. No `task_grants` or `saved_permissions` entry is added.
- `stop_all_background` kills every running entry (mock Popen).
- Foreground sandboxed `run_shell` is unchanged (existing suites pass).
- `tests/test_csrf_route_inventory.py` passes with the stop route removed from
  the baseline and nothing added.
- URL extraction picks the first localhost URL from a Vite/Slidev-style log and
  returns no `url` when there is none.
- JS: the outside card renders only Run and Deny; the status card shows Open
  only when a URL was found.
- Manual: Slidev deck start, open, live edit of `slides.md`, Stop, and app
  close kills `node.exe`.
