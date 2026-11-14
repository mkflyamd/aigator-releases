---
name: Shell Runner
description: Execute shell commands (bash/WSL, PowerShell, cmd) — git, npm, build scripts, terminal operations
version: '1.0'
---

# Shell Runner

Use this skill to run terminal commands — git operations, npm/pip builds, batch scripts, or any command-line task.

## When to use run_shell

- User asks to run a git command (git status, git log, git pull)
- User asks to run npm, pip, or build scripts
- User asks for a command pipeline (grep, find, dir)
- User asks to run a .py, .ps1, or .sh script via command line
- Any task that requires a full terminal operation

## When run_shell cannot do it: run_on_host

Some commands cannot work inside the sandbox: node, npm, git or gh installed under Program Files, sign-in prompts, anything that needs the user's own network, VPN, proxy, certificates or credentials, and publishing or pushing the user asked for. For these, call `run_on_host` instead of asking the user to open a terminal and paste.

- It shows the user a card with the exact command, folder and shell. Nothing runs until they click Run. They can click Cancel.
- Give a one-sentence `reason` that says why the command is needed and why it cannot run in the sandbox.
- After calling it, stop and wait. When the user says they ran it, call `host_command_result` with the `request_id` to read stdout, stderr and the exit code. If they cancelled, do not propose it again.
- One foreground command that ends by itself. No servers, no interactive prompts. Delete operations are refused.
- Try `run_shell` first for ordinary build and scratch work; use `run_on_host` when the sandbox is the obstacle.

## Prefer file_ops for simple file tasks

Use read_file, write_file, list_dir from file_ops instead of run_shell when you only need to read or list files. run_shell is for operations that need the full shell environment.

For generated Python snippets that use Gator's bundled packages, use `run_python` instead of invoking `python` through run_shell. In the packaged app, direct `python`, `python3`, and `py` commands are routed through Gator's bundled Python runtime; other shell-managed Python environments remain unchanged.

## Shell auto-detection

You do not need to specify shell — the system auto-detects bash/WSL -> Git Bash -> PowerShell -> cmd in that priority order. Specify shell only if the user explicitly asks for a particular shell.

## Destructive operations

Never attempt rm, del, rmdir, Remove-Item, or format — these are blocked. Tell the user to run those commands manually.

## Working directory (cwd)

- **Operating on a real project** (the user's repo/app): pass that path as `cwd`. It is always honored.
- **Scratch or build work** (creating a deck, scratch generators, temp npm installs): **OMIT `cwd`.** It defaults to an app-owned working dir (`~/.gator/work`) so transient files — `node_modules`, build scripts, intermediate assets — don't splatter into the user's home directory or repo. The folder persists across calls, so a multi-step build (npm install, then run the generator) shares one location and relative paths resolve.
- Write the _final deliverable_ (the .pptx/.docx/etc.) to where the user expects, and report its path — don't leave it buried in the scratch dir.

## Examples

Run git status (real project — explicit cwd):
run_shell(command="git status", cwd="C:/Users/me/project")

Run a Python script (real project — explicit cwd):
run_shell(command="python my_script.py", cwd="C:/Users/me/project")

NPM build in the user's app (explicit cwd):
run_shell(command="npm run build", cwd="C:/Users/me/myapp")

Scratch build (OMIT cwd — runs in ~/.gator/work):
run_shell(command="npm install some-js-tool")
run_shell(command="node build_script.js")

## Prefer native tools for Office file generation

When asked to create a .pptx, .docx, or .xlsx **without a specific skill instructing otherwise**, prefer `run_python` with `python-pptx` / `python-docx` / `openpyxl` (already installed) or the built-in `create_pptx` / `create_docx` / `create_excel` tools — they are faster and require no npm install. Only reach for Node.js libraries like `pptxgenjs` if a skill's SKILL.md explicitly calls for it.
