# run_shell sandbox — design

Date: 2026-10-06
Branch: security/threatmodel-remediation
Closes the open gap in finding `H_Code_runner_skill_used_for_lateral_movem_06` (`run_shell` is unsandboxed and bypasses the code-runner sandbox). Also completes `M_Localhost_CSRF_token_exposure_via_browse_05` on Linux and Windows (see "Why this also finishes the CSRF fix").

## Goal

`run_shell` runs inside the same OS sandbox as `run_python`. Widening that access needs a human decision on an approval card. Friction stays low: most commands show no card, one approval covers a whole task, and the user can save an approval ("Always allow") and manage saved approvals in Settings.

## Decisions (agreed with the user, 2026-10-06)

1. Same launcher, same deny list, same admin policy file, same card as `run_python`. No second mechanism.
2. Approval has two buttons: **Allow for this task** (default) and **Always allow this**.
3. "Task" means the assistant's work on one user message. A task approval ends when the user sends the next message in that tab, or after 10 minutes, whichever is first.
4. Saved permissions are made only through the card and are removed only in Settings. The model cannot create, change or remove them.
5. No permission is granted by default. Interpreters can never be saved with network access.

## Behavior

### What runs with no card
A command runs in the sandbox with no card when it needs only:
- read and write in its working folder, if the working folder is the default scratch folder (`~/.gator/work`) or a folder the user already approved (this task or saved);
- read of the runtime (shell, system tools, Git for Windows, Node, Python);
- no network.

### What triggers a card
- A working folder (`cwd`) that is not the scratch folder and not yet approved: card "write to <folder>" (first use in a project asks once; Always allow makes it permanent for that folder).
- The model declares extra read/write paths or network need (`extra_read_paths`, `extra_write_paths`, `network_hosts`, the same parameters and normalization as `run_python`).
- A command that fails inside the sandbox with a permission or network error returns the same sandbox hint `run_python` uses, so the model asks again with the right declaration. The sandbox is never relaxed silently.

### Never grantable
The existing deny list applies unchanged (drive roots, home folder, `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud`, `~/.gator` except outputs, autostart locations, Windows UNC/device/stream/dot-or-space spellings, network drives). A card is never shown for these; the call is refused.

### Task approvals
- Stored server-side next to the existing `approvals` store, keyed by tab (`context_id`).
- A command may run when its required access is a subset of the union of the tab's live task approvals.
- Created only by the CSRF-guarded approve route. Ended after 10 minutes, or when the user sends a new message in that tab. The automatic message the chat UI sends after an Approve or Deny click is not a new message: the UI marks it (`sandbox_followup: true` on the chat request) and the chat route ends the tab's task approvals only when that flag is absent.
- The existing single-use approvals for `run_python` are unchanged.

### Saved permissions ("Always allow this")
- Offered only when the card requests:
  - folder access only (read or write on a path that passed the deny list); the saved permission is that path and mode; or
  - network, where every statement of the command starts with a plain program name that is not an interpreter and the command has no substitution; the saved permission is the set of program names plus network.
- Never offered, per task only: any command whose programs include an interpreter or shell (`python`, `python3`, `py`, `node`, `deno`, `bun`, `ruby`, `perl`, `php`, `bash`, `sh`, `zsh`, `pwsh`, `powershell`, `cmd`, `wsl`, `npx`), a command containing `$(`, backticks, `eval`, `source`, process substitution, or `-c`/`-Command`/`-e` style code arguments, and anything the parser cannot read. Unparseable fails closed to per task only.
- A saved network permission is stated honestly on the card: programs such as `git` and `npm` run scripts stored in the project, so it lets those project scripts use the network. The user chose it knowingly; it is revocable.
- Stored in the encrypted credential store (`secure_store.get_json/set_json`, name `sandbox/saved-permissions`), not in a plain file. The store protects against casual reading and against the model's own file tools: `file_ops`, the Word/Excel/PowerPoint tools (including image paths they embed), `download_onedrive_file` and `describe_images` refuse any path inside the secrets folder (`sandbox.paths.is_secrets_path`), so a tricked model cannot write itself "always allow curl with network". It is not a defense against same-user code that runs outside the sandbox: on Windows the blob is DPAPI with a fixed entropy and on Linux the key-file fallback is readable by the user, so malware, an MCP filesystem server or a `run_python`/`run_shell` with the sandbox turned off could forge a valid entry; that is out of scope. A corrupted or deleted blob simply means no saved permissions (fail closed).
- Settings gets a "Saved permissions" section listing each saved permission in plain words, with Remove and Remove all. Routes are CSRF-guarded: `GET /api/sandbox/saved-permissions`, `DELETE /api/sandbox/saved-permissions/{id}`, `DELETE /api/sandbox/saved-permissions`.
- Admin policy gains `saved_permissions: allow|deny` (default allow). `deny` hides "Always allow", ignores saved entries and keeps task approvals. A missing, unreadable or invalid policy file already fails closed.
- Telemetry (metadata only, no paths, hosts or commands): decision values gain `task_approved`, `saved`, `saved_created`.

## Shell choice and credentials

- **Windows:** WSL bash reaches the whole user profile through `/mnt/c`, so it cannot be sandboxed by an AppContainer and is **never used when the sandbox is enforced**. The only shell that runs under the AppContainer launcher is **cmd.exe** (spike on the dev machine, 2026-10-06): Git Bash cannot start (msys fails with 0xC0000142 in an AppContainer, even `echo.exe`), and PowerShell cannot set its working folder (it falls back to `C:\`). With the sandbox enforced, `run_shell` on Windows therefore runs the command in cmd.exe, and a call that asks for `bash` or `powershell` gets an error that says so. This is a behavior change on machines where WSL was the default shell.
- **Windows limits of cmd in the AppContainer:** python, file writes in the working folder, and reads of granted folders work; a read outside the granted folders is denied. `dir` and `git` fail inside a project folder (`fatal: Unable to read current working directory`): both resolve the long path of the working folder, which needs list access on its parent folders, and the AppContainer has none. This is a Windows limit of v1; the error hint tells the model to use the file tools to list files and to ask the user to run git. Granting ancestor-folder listing is a possible later launcher change.
- **macOS and Linux:** the detected `bash`/`sh` run through Seatbelt/bubblewrap with the system tool folders read-only.
- **Environment:** the same allow-list as `run_python` (`build_env`); no token or credential variable reaches the shell, and `AIGATOR_SHELL_KEY` is already gone.
- **Credentials:** the sandbox has no access to `~/.gitconfig`, `~/.ssh`, credential helpers or tokens. `git push` or `gh` against a private remote therefore fails inside the sandbox, even with network approved. This is a deliberate v1 limit; the error hint tells the model to ask the user to run it, or to use the existing GitHub tools. Passing a credential into the sandbox is a separate decision and is not part of this work.

## Background commands

`run_shell(background=true)` today starts a detached process. It must not stay unsandboxed. The plan decides per launcher whether a sandboxed non-blocking start is small enough to add. If it is not, `background=true` is **refused** when the sandbox is enforced, with a clear message; it never runs unsandboxed. `check_shell_process` and `stop_shell_process` only look at pids and are unchanged.

## Unchanged behavior

- The delete blocklist (`rm`, `del`, `rmdir`, `Remove-Item`, `format`) stays and runs before everything else.
- Frozen-python routing, output-file reporting and the timeout stay.
- Fail closed: if the sandbox cannot start, the command does not run unsandboxed. The existing opt-out (`code_runner_sandbox: off`, only when the sandbox cannot run and policy does not require it) is shared with `run_python`.

## Why this also finishes the CSRF fix

The shell key stops a web page and a network-approved sandbox run from fetching the CSRF token. An unsandboxed `run_shell` running as the user can still read the backend's startup environment (`/proc/<pid>/environ` on Linux, process memory on Windows) and so can still obtain the key. Once `run_shell` is sandboxed, with its own process namespace on Linux and an AppContainer on Windows, that route is closed. Same-user malware outside AI Gator stays out of scope.

## Components

- `web/skills/shell_runner/tools.py`: build the `SandboxRequest`, parse programs, call the approval gate, launch, shape the result; remove the unsandboxed path.
- `web/sandbox/approvals.py` (or a small new `task_grants.py`): task approvals with tab key, union subset check, end on next message, 10-minute expiry.
- `web/sandbox/saved_permissions.py` (new): load, save, remove, match on top of `secure_store`; versioned JSON; any read error or unknown version is treated as no saved permissions.
- `web/sandbox/command_programs.py` (new): `programs_in(command) -> set[str] | None` with the interpreter and substitution rules above; small, table-tested.
- `web/routes/sandbox_routes.py`: `remember` flag on approve (honored only when the server confirms the request is saveable), saved-permission list/remove routes.
- `web/sandbox/policy.py`: `saved_permissions` field.
- `web/routes/chat.py`: end the tab's task approvals when a new user message arrives.
- `web/static/app.js` and the Settings page: card with two buttons and the command text, Saved permissions section.
- Docs: `docs/BUILD_INSTRUCTIONS.md` (policy field, WSL behavior change, smoke test), tracker row, REDLINE docx section.

## Testing

- Unit: program parser (interpreters, substitution, separators, quoting, unparseable), task-grant subset and expiry, saved-permission match and corrupt-file handling, policy field, deny list through the shell path, WSL excluded when enforced, background refused or sandboxed.
- Routes: CSRF required, `remember` ignored for an unsaveable request, Remove works, the model-side tool cannot reach any of them.
- Real runs: Windows (cmd under the AppContainer: working-folder write, denied read outside, network denied) and Linux in WSL; existing `tests/shell_runner` and background tests updated.
- Release gate (unchanged in kind): a manual smoke test on a real Mac and a real Linux desktop, now including a sandboxed `run_shell` command and the Saved permissions page.

## Known limits (to state in the docx)

- Network approval is all or nothing per run, as for `run_python`.
- A saved network permission for `git`/`npm`-like programs lets project scripts use the network (stated on the card).
- Credentialed commands (`git push`, `gh`, `ssh`) do not work in the sandbox in v1.
- Windows users whose default shell was WSL now get cmd.exe while the sandbox is enforced; `dir` and `git` do not work inside it (see Shell choice).
- The macOS Seatbelt profile is still unverified on a real Mac.
