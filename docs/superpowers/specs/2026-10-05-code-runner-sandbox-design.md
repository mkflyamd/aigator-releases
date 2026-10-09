# Code-runner sandbox — design

**Finding:** `H_Code_runner_skill_used_for_lateral_movem_06` (High): the Code-runner skill can be used for
lateral movement and unrestricted network and filesystem egress.

## Problem

`run_python` (`web/skills/code_runner/tools.py`) runs model-written Python as the user, with the user's
full filesystem access, full network access, and the server's whole environment (including
`GITHUB_TOKEN`, `JIRA_*`). Its only guard is an AST scan whose "confirmation" (`confirmed=True`) is
passed by the model itself, so a prompt-injected model can approve its own request. Any code it runs
can read `~/.ssh`, reach internal hosts, or exfiltrate data.

## Approach

Run the code in an OS-level sandbox on all three platforms behind one small interface, and gate every
widening of access on a real human approval that the model cannot grant itself.

| OS      | Mechanism                                                                                                                         | Needs admin / new install                                       |
| ------- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Windows | AppContainer launched through `ctypes` (CreateProcessW + `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`), Job Object for tree kill | No                                                              |
| macOS   | Seatbelt, `/usr/bin/sandbox-exec -p <profile>`                                                                                    | No (ships with the OS)                                          |
| Linux   | `bwrap` (bubblewrap) with `--unshare-all`                                                                                         | Needs the `bubblewrap` package and unprivileged user namespaces |

No off-the-shelf library is used. Codex's Windows sandbox needs elevation, `@anthropic-ai/sandbox-runtime`
needs Node and is beta, MXC is an early preview and not yet a security boundary, and microsandbox is VM
based. A Windows spike
(2026-10-05, scratch code only) showed a ~200-line `ctypes` AppContainer launcher works without admin:
run folder writable, other user folders unreadable, external and loopback network blocked, parent
secrets absent from the child, extra-path grant and revoke work, a Job Object kills the tree, cleanup
leaves nothing behind.

## Interface (`web/sandbox/`)

```python
@dataclass(frozen=True)
class SandboxRequest:
    argv: list[str]            # command to run (python/node + script)
    cwd: Path                  # run folder; always read/write
    env: dict[str, str]        # complete child environment (already filtered)
    runtime_paths: list[Path]  # read+execute: interpreter, stdlib, site-packages, SKILL_DIR, NODE_PATH root
    read_paths: list[Path]     # extra read-only paths the user approved for this run
    write_paths: list[Path]    # extra read-write paths the user approved for this run
    network: bool              # outbound network approved for this run
    timeout: int

@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool

def sandbox_level() -> str                 # "enforced" | "unavailable"
def sandbox_unavailable_reason() -> str | None
def launch_sandboxed(req: SandboxRequest) -> SandboxResult   # raises SandboxUnavailable
```

`launcher_windows.py`, `launcher_macos.py`, `launcher_linux.py` implement it; `launch_sandboxed`
dispatches on `sys.platform`. Pure builders (Seatbelt profile text, `bwrap` argv, Windows ACL grant list)
are separate functions so they are unit-tested on every OS. The marketplace-skill finding
(`H_Malicious_marketplace_or_MCP_skill_execu_03`) is intended to reuse the same interface later.

## Default sandbox contents (what code can do with no approval)

- Read and write: its own run folder only (`~/.gator/outputs/<run_id>`).
- Read and execute: the runtime paths (interpreter and libraries, the skill folder when `skill_id` is
  given, the global npm root for Node) plus the OS system directories the platform needs to start a
  process (Seatbelt: `/usr`, `/System`, `/Library`, `/bin`, `/private/etc`; `bwrap`: `/usr`, `/lib*`, `/bin`,
  a minimal `/etc`; AppContainer: no extra, ALL APPLICATION PACKAGES covers `System32`).
- No network. No access to any other part of the user profile.
- Environment: an allow-list only (PATH, OS-required variables such as `SystemRoot`, `LOCALAPPDATA`,
  `APPDATA`, `USERPROFILE`, `TEMP`, `TMP`, `windir` on Windows, `HOME`/`TMPDIR`/`LANG` elsewhere,
  `NODE_PATH`, `PYTHONIOENCODING`). Everything else, including every token, is dropped.
- Children spawned by the code inherit the sandbox (all three mechanisms propagate).
- Windows only: launch Node with `--preserve-symlinks --preserve-symlinks-main` (it otherwise fails with
  `EPERM lstat 'C:\'`). Grants are `icacls` inheritable `(OI)(CI)RX` for the container SID on each
  runtime directory and `(OI)(CI)M` on the run folder, applied without admin because the user owns
  those paths (the installer is per-user); they are removed after the run.

## Approval flow (the model cannot grant itself access)

`run_python` gains three optional arguments: `extra_read_paths`, `extra_write_paths`, `network_hosts`
(list of `host:port` strings, informational). When any is present:

1. Paths are normalized (absolute, resolved). A built-in deny list is never grantable, even by the user:
   filesystem and drive roots, the home directory itself, `~/.gator` (except `outputs`), `~/.ssh`,
   `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud`, and autostart/persistence locations
   (`~/.bashrc`, `~/.profile`, `~/.bash_profile`, `~/.zshrc`, `~/.zprofile`, `~/Library/LaunchAgents`,
   `~/.config/autostart`, the Windows Startup folder under `AppData/Roaming`). On Windows the
   extended-length prefix (`\\?\C:\...`) is stripped before the check, and every other `\\`-prefixed
   form (UNC shares, `\\?\UNC`, volume GUIDs, `\\.\` devices), alternate data streams (`:` after the
   drive letter), path names ending in a dot or space (Win32 trims them, so `.ssh.` opens `.ssh`) and
   mapped network drives (fail closed if the drive type cannot be read) are refused. On macOS the firmlinked
   `/System/Volumes/Data/...` spelling of the home folder and of each protected entry is denied too.
2. If there is no matching approval, nothing runs. The tool returns `approval_required` with a request
   id and the normalized paths and hosts, and stores a pending request server-side.
3. The UI shows an approval card (what code wants to read, write, connect to). **Approve** and **Deny**
   call `POST /api/sandbox/requests/{id}/approve|deny`, protected by `verify_csrf` (same guard as
   `/api/drafts/{id}/approve`); the agent loop's tools do not call these routes. Code that reaches
   AI Gator's localhost API (`run_shell`, a network-approved run on Linux) cannot read the CSRF token,
   which is served only to the Electron shell (see Known gaps). After the click the UI sends
   a short chat message so the model knows to re-call (or not).
4. On the re-call, the server finds an approved, unexpired (10 minutes), unconsumed request for the same
   conversation tab and exactly the same normalized set, consumes it, and runs with those grants for
   this run only. Any difference in the set requires a new approval.
5. Network approval turns outbound access on for the whole run. The approved `host:port` is shown to
   the user but is not enforced per destination (AppContainer, Seatbelt and `bwrap` are all or nothing
   without a proxy). This is a stated partial against the report; a filtering proxy is added only if
   reviewers require it.
6. When denied or expired the tool returns a fixed error and the model is told not to retry.

When sandboxed code fails with a permission or network error, `stderr` is followed by a one-line hint
telling the model to re-call with `extra_read_paths`, `extra_write_paths` or `network_hosts` if it
really needs them. The `SKILL.md` and the tool description are rewritten: remove "full read access".

## Policy (machine-wide, admin controlled)

One JSON file, read on each run (cheap, mtime cached):
Windows `%ProgramData%\AIGator\sandbox-policy.json`, macOS `/Library/Application Support/AIGator/sandbox-policy.json`,
Linux `/etc/aigator/sandbox-policy.json`.

```json
{
  "code_runner": "enabled|disabled",
  "network": "ask|deny",
  "filesystem": "ask|strict",
  "require_sandbox": true
}
```

- `disabled`: `run_python` returns a fixed error and does nothing.
- `network: deny`: any `network_hosts` request is refused, no card is shown.
- `filesystem: strict`: any extra path request is refused, no card is shown.
- `require_sandbox: true`: the user opt-out below is ignored.
- Missing file: defaults (`enabled`, `ask`, `ask`, `false`). A present but unreadable, invalid, or (POSIX)
  group/world-writable or non-root-owned file fails closed to `network: deny`, `filesystem: strict`, and
  `require_sandbox: true`, logged once. On Windows the file inherits the admin-only ProgramData ACL;
  the code does not check it.

## When the sandbox is unavailable

`sandbox_level()` is `unavailable` when the platform mechanism cannot run (Linux without `bwrap` or with
user namespaces disabled, macOS without `sandbox-exec`, Windows AppContainer creation failing). Default
behaviour is fail closed: `run_python` returns an error naming the reason and the fix (for example
"install bubblewrap"). Settings shows a notice (text only, like the credential-storage notice) and, only
when the policy does not set `require_sandbox`, a checkbox "Allow code to run without a sandbox on this
machine", stored as `code_runner_sandbox: "off"` in `config.json`. With the opt-out the old unsandboxed
path runs and every result carries `sandbox: "off"`. `GET /api/sandbox/status` returns
`{level, reason, opted_out, policy}`.

## Telemetry

One metadata-only line per run in the existing turn telemetry: run id, skill id, sandbox level
(`enforced|off`), network (bool), extra read count, extra write count, and each approval decision
(`approved|denied|expired`). No paths, hosts, code, or output.

## Packaging and platforms

- Windows needs no new dependency. macOS needs none. Linux needs `bubblewrap` from the distro; the
  Linux packaging and `docs/BUILD_INSTRUCTIONS.md` must list it, and the unavailable notice explains it.
- Frozen (PyInstaller) builds run code through `sys.executable --run-python`; the sandbox treats the
  backend bundle directory as a runtime path. The spike saw the frozen `aigator-backend.exe --run-python`
  hang at exit even without a sandbox; diagnosing and fixing that is the first implementation task.

## Testing

- Pure builders and policy/approval logic run on every OS.
- Windows launcher: real runs (containment, network, env, extra-path grant and revoke, tree kill,
  cleanup, stale-ACE sweep) on this machine.
- Linux launcher: the WSL Ubuntu on this machine is used for real runs if `bubblewrap` can be installed
  there; otherwise argv builder tests only.
- macOS launcher: **cannot be run here**. Profile builder tests only. A manual smoke test on a Mac and on
  a Linux desktop is a release gate and the security write-up says it was not run.
- Existing `tests/code_runner/test_run_python.py` keeps passing with the sandbox off (autouse fixture)
  plus new tests with a fake launcher; one marked integration test runs a real sandboxed run on Windows.

## Known gaps (stated plainly, not hidden)

- `shell_runner` (`run_shell`) is also always-on and unsandboxed; the model can run `python` through it
  and bypass this control. It is not named in the report and is not changed here.
- `packages=[...]` pip installs of any PyPI name run unsandboxed in the server process with the full
  environment and need no approval (enforced mode only refuses URLs, paths, options and archive names).
- Network approval is all or nothing per run (no per-destination enforcement).
- Linux: a network-approved run shares the host network namespace (`--share-net`), so the code can still
  reach AI Gator's localhost API. It cannot obtain the CSRF token: the token endpoints (`GET /` and
  `GET /api/csrf`) now require a per-launch key that only the Electron shell holds (finding
  `M_Localhost_CSRF_token_exposure_via_browse_05`, closed by the shell key; see
  `2026-10-06-csrf-token-shell-key-design.md`), so the code cannot approve its own later requests or
  draft approvals. Other unauthenticated, non-CSRF-guarded routes are still reachable and are separate
  findings. Windows (AppContainer blocks loopback) and macOS (a
  `(deny network-outbound (remote ip "localhost:*"))` rule after the network allow; not verified on a
  real Mac) never had this exposure.
- Windows: the run lock is per process. Two backends running at once (dev and desktop) share the
  container SID and the grant ledger, so one backend's launch-time sweep can revoke the other's grants.
- macOS: `/System/Volumes/Data` (the firmlinked data volume) is denied after the `/System` read
  allowance; this rule has not been run on a real Mac.
- Same-user malware outside AI Gator is out of scope; sandbox escapes through OS bugs are inherited.
- A crashed launcher on Windows can leave the container ACEs behind; a startup sweep removes them.
- macOS and Linux launchers verified by unit tests only (and WSL if available), not on real systems.
- Windows 10, antivirus/EDR reactions, long paths, and per-machine loopback exemptions were not tested.

## Out of scope

Per-destination network filtering proxy, sandboxing `run_shell` or MCP stdio servers, marketplace
skill sandboxing (separate finding), sandboxing pip installs, resource limits (CPU, memory).
