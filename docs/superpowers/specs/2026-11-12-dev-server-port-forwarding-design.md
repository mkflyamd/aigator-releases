# Preview a dev server from the sandbox with port forwarding

## Use case
A user asks AI Gator to edit a local web project (for example a Slidev deck in
`Documents\Gator\gator-source`) and preview it live. Today that cannot work:

- `run_shell(background=true)` is refused while the sandbox is on.
- A server started inside the Windows AppContainer sandbox cannot be reached
  from the browser. Loopback is isolated, so a request from outside times out.

## Desired experience
1. The user asks "start the deck so I can preview it".
2. AI Gator shows the normal sandbox approval card for the command and folder.
3. On approval, the server starts inside the sandbox. A status card shows
   "Running at http://localhost:3030" with **Open** and **Stop**.
4. The user edits slides through AI Gator and the page reloads live.
5. Closing AI Gator stops the server.

The server never leaves the sandbox. AI Gator only forwards a localhost port to
it.

## How it works
Loopback works between processes inside the same AppContainer (verified, with
`network=False` too). So a small relay process inside the sandbox can reach the
dev server, and the relay talks to AI Gator over its stdin and stdout pipes,
which the launcher already owns.

```
browser -> 127.0.0.1:P (AI Gator listener) -> relay pipes -> relay (sandbox) -> 127.0.0.1:devport (dev server, sandbox)
```

- Starting a sandbox process takes about 1.5s, so one relay carries every
  connection. A relay per connection is too slow.
- The relay is a Python script. Node's piped `child_process` hangs in the
  sandbox, Python's does not.
- The relay also starts the dev server as its child, so the relay and the
  server share one sandbox process tree and one Job Object. This is required:
  loopback works only inside one launch's process tree. Two separate sandbox
  launches with the same profile cannot reach each other (verified).
- A program under `C:\Program Files` is readable from inside the sandbox only if
  it carries an ALL APPLICATION PACKAGES access entry. A default Node install
  does not, and the user cannot change that ACL. The launcher's first process
  starts fine, but the relay's child `node.exe` fails with Access denied. So a
  tool the sandbox cannot read is copied to a folder it can (see Runtime copy).

## Rules
1. **Scope.** Windows only in v1. `run_shell(background=true)` is allowed while
   the sandbox is on, and always runs sandboxed. Foreground commands are
   unchanged. On other platforms, and when the sandbox is off, background
   commands behave as today.
2. **Approval.** Same gate and card as a foreground sandboxed `run_shell`: exact
   command, folder, and the existing Allow / Always / Deny choices. The card
   adds one line: "Runs in the sandbox and is made available at localhost."
   `policy.require_sandbox` is satisfied because the run is sandboxed.
3. **Unattended runs** are refused for `background=true`. A forwarded port needs
   a person in a tab.
4. **One port.** v1 forwards the first localhost port the server prints. The
   forwarding listener binds `127.0.0.1` only. It uses the same port number as
   the dev server when that is free, so the page origin, the Host header and
   Vite's HMR websocket all keep working. Otherwise it uses a free port.
5. **Lifetime.** The launcher holds the Job Object with kill-on-close. Stopping,
   closing AI Gator, a crash and Electron's hard kill of the backend all end
   the tree, because the kernel closes the handle. No pid file is needed for
   these processes.
6. **Limits.** The existing cap of 10 background processes. At most 64 open
   forwarded connections per process.
7. **Telemetry.** Existing `sandbox.telemetry_record` call for the run. No new
   fields, no command, paths or output.

Out of scope for v1: more than one forwarded port per process, macOS and Linux,
static build preview, and a UI to choose the port.

## Design

### Streaming launcher — `web/sandbox/launcher_windows.py`
New `start_sandboxed(request) -> SandboxProcess` next to `launch_sandboxed`. It
reuses the same profile, ACL grants, environment and Job Object setup as
`_run_contained`, with three differences:
- stdin is a pipe (not `NUL`);
- it returns right after `ResumeThread` instead of waiting for exit;
- it returns a handle that owns the process, the job and the pipes.

`SandboxProcess` has `pid`, `poll()`, `stdin`/`stdout` byte streams, and
`terminate()` (closes the job, which kills the tree). `stderr` is merged with
the child's output inside the relay, not read separately. The existing
`launch_sandboxed` path is not changed.

Other platforms get a `start_sandboxed` that raises `NotImplementedError`, and
`run_shell` keeps its current refusal there.

### Relay — `web/sandbox/relay.py` (new, runs inside the sandbox)
Started as `python relay.py -- <argv of the user's command>`. Stdlib only.
- Starts the command (`cwd` is the project folder, stdin `NUL`, stdout and
  stderr merged) and pumps its output to Gator as `LOG` frames. When the command
  exits it sends `EXIT` with the code and stops.
- On `OPEN(conn, port)` it dials `localhost:port`, then forwards `DATA` both
  ways until either side sends `CLOSE`.
- A reader thread per direction. Frames are written under one lock.

### Runtime copy — `web/sandbox/runtime_copy.py` (new)
For a background run, the first word of the command and `npm`/`npx` resolve
through `PATH`. If the resolved tool's folder is not readable by the container
(`launcher_windows._container_can_read` is false and `_can_change_acl` is false),
the folder is copied once to `~/.gator/sandbox/runtime/<name>-<version>/` and
that copy is put first in the relay's `PATH` and granted read and execute
through `runtime_paths`. For Node this copies the install folder (about 100 MB).
Nothing is copied when the tool is already readable, for example a user-owned
Node under `%LOCALAPPDATA%` or Python.

### Wire format — `web/sandbox/wire.py` (new, shared)
Frame: `!BII` (type, connection id, payload length), then the payload. Types:
`OPEN` (payload: port), `DATA`, `CLOSE`, `LOG`, `EXIT`. Max payload 64 KB.
Both ends share this module. The framing follows the pattern in the MIT
project hello-127. We write our own because that package needs Python 3.14 or
newer, and AI Gator supports 3.12 and 3.13.

### Forwarder — `web/sandbox/forward.py` (new, runs in the backend)
`ForwardedProcess` wraps a `SandboxProcess`:
- A reader thread decodes frames from the relay's stdout. `LOG` frames go to
  the same log file `check_shell_process` already reads. `DATA`/`CLOSE` go to
  the matching connection. `EXIT` marks the process stopped.
- The event loop is never blocked. Pipe reads and writes run on threads and
  hand off with `call_soon_threadsafe`, and the listener is an asyncio server.
- Port detection: after stripping ANSI codes, the first match of
  `https?://(localhost|127\.0\.0\.1|\[::1\]):(\d+)` in the log. The port must
  follow the host directly, so `localhost.evil.com` cannot match.
- When the port is found and the listener is up, the status is "ready". Each
  accepted browser connection becomes an `OPEN` frame plus `DATA`/`CLOSE`.
- `url`, `listen_port`, and `ready` are exposed to the tool result and the
  background-process listing.

### Shell tool — `web/skills/shell_runner/tools.py`
- `_run_sandboxed` stops refusing `background=True` when the platform supports
  `start_sandboxed`. It goes through the existing approval lookup unchanged
  (including the exact-command match), then starts the relay.
- A new `_spawn_sandboxed_background` creates the `ForwardedProcess` and adds a
  `_BG_REGISTRY` entry with the log file, the command and `"sandboxed": True`.
  `poll()` comes from the handle, so the existing listing and
  `check_shell_process` work as they are.
- The call waits up to 30s for "ready". It then returns `url` when found, or
  "started, no URL yet, use check_shell_process" when not.
- `_tool_stop_shell_process` calls `terminate()` for a sandboxed entry, and
  refuses a pid that is not in `_BG_REGISTRY`. Today it kills any pid it is
  given.
- The `run_shell` description steers the model to inspect with `list_dir`,
  `read_file` and `grep_files`, edit with `write_file`/`edit_file`, and use
  `background=true` for a dev server.
- Shell and `python3` rewrites are the same as the foreground path, and the
  card shows the final command.

### Orphan cleanup — `web/skills/shell_runner/tools.py`
`cleanup_orphan_bg_procs` kills any pid listed in `bg-pids.json`, a file in a
folder the sandbox can write. It now verifies that the process command line
still matches the recorded command before killing. Sandboxed entries never
write to that file.

### Stop route — `web/routes/tasks.py`, `web/static/agents-pane.js`
`POST /api/shell/background-processes/{pid}/stop` gets
`dependencies=[Depends(verify_csrf)]` and is removed from
`tests/csrf_route_baseline.txt`. It returns 404 for a pid that is not in
`_BG_REGISTRY`. `agents-pane.js` sends the CSRF token the same way the sandbox
card does, with the 403 refresh and retry.

### Frontend — `web/static/app.js`
- The sandbox card shows the extra line from rule 2 when the request is a
  background run.
- The tool result carries `url`. A status card shows "Running at <url>" with
  **Open** and **Stop**. Without a url it shows "Running (pid N)" and Stop. It
  polls `GET /api/shell/background-processes` every 5s while visible and shows
  "Stopped" when the pid is gone.
- **Open** is a link with `target="_blank"`, allowed only when the URL matches
  the localhost pattern above. Electron's window-open handler already sends
  http(s) links to the system browser, so no new bridge is needed.

### Docs
`docs/security/threatmodel-remediation.md`, H_06 row: background commands are
no longer refused. A long-running background command runs inside the sandbox
under the same approval as a foreground run, and AI Gator forwards a loopback
port to it. The server never runs with user access.

## Tests
- Wire: encode and decode round trip, a frame split across reads, an oversized
  payload is rejected.
- Relay and forwarder, using a plain Python `http.server` child and no real
  sandbox: a browser-side connection reaches the server through the frames,
  many connections at once, `CLOSE` from either side, the 64 connection cap,
  `EXIT` ends everything, a malformed frame closes the process.
- Port detection: the first localhost URL in a coloured Vite or Slidev log,
  ignores `http://localhost.evil.com:80`, no match gives no url.
- Listener: binds only `127.0.0.1`, prefers the dev server's port, falls back
  to a free port when it is taken.
- Shell tool: `background=true` with the sandbox on asks for approval first
  and starts nothing until it is approved. Unattended is refused. The result has
  `url`. `_tool_stop_shell_process` refuses a pid not in the registry and
  terminates a sandboxed entry.
- The event loop is not blocked while a connection streams data.
- `cleanup_orphan_bg_procs` leaves a pid alone when its command line does not
  match.
- The stop route returns 404 for an unknown pid. `tests/test_csrf_route_inventory.py`
  passes with the route removed from the baseline and nothing added.
- JS: the background card line, the status card with and without url, and
  `agents-pane.js` sending the CSRF token on stop.
- Runtime copy: a tool folder the container cannot read is copied once and
  put first in `PATH`, a readable one is not copied, and a second run reuses
  the copy.
- Windows only, run on a real machine: `start_sandboxed` of the relay and a
  Vite+React dev server started with `npm run dev`, the page loads through the
  forwarded port, HMR updates after an edit, Stop ends `node.exe`, and killing
  the backend process also ends it.

## Spike results (2026-11-12, Windows, scratch scripts)
- Vite+React under a Python supervisor inside the sandbox, with a readable copy
  of Node: `node.exe vite.js` gave 200 for `/`, `/src/main.jsx` and
  `/@vite/client` in 2s, and `npm run dev` through `cmd` gave 200 for `/` in 3s.
- Same server, a second separate sandbox launch as client: connection timed
  out. Plain Python server and client in two launches: refused. Same tree works.
- Default Node under `C:\Program Files\nodejs`: the container cannot list the
  folder and a child `node.exe` start gives Access denied.
- Not yet verified: the streaming launcher (stdin pipe, no wait) carrying
  frames, and the Job Object ending the tree when the backend dies. These are
  the first tasks of the plan.
- Manual: the Slidev deck end to end through the Gator chat.
