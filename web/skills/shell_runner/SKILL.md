---
name: Shell Runner
description: Execute shell commands (bash/WSL, PowerShell, cmd) — git, npm, build scripts, terminal operations
version: "1.0"
---

# Shell Runner

Use this skill to run terminal commands — git operations, npm/pip builds, batch scripts, or any command-line task.

## When to use run_shell

- User asks to run a git command (git status, git log, git pull)
- User asks to run npm, pip, or build scripts
- User asks for a command pipeline (grep, find, dir)
- User asks to run a .py, .ps1, or .sh script via command line
- Any task that requires a full terminal operation

## Prefer file_ops for simple file tasks

Use read_file, write_file, list_dir from file_ops instead of run_shell when you only need to read or list files. run_shell is for operations that need the full shell environment.

## Shell auto-detection

You do not need to specify shell — the system auto-detects bash/WSL -> Git Bash -> PowerShell -> cmd in that priority order. Specify shell only if the user explicitly asks for a particular shell.

## Destructive operations

Never attempt rm, del, rmdir, Remove-Item, or format — these are blocked. Tell the user to run those commands manually.

## Working directory (cwd)

- **Operating on a real project** (the user's repo/app): pass that path as `cwd`. It is always honored.
- **Scratch or build work** (creating a deck, scratch generators, temp npm installs): **OMIT `cwd`.** It defaults to an app-owned working dir (`~/.gator/work`) so transient files — `node_modules`, build scripts, intermediate assets — don't splatter into the user's home directory or repo. The folder persists across calls, so a multi-step build (npm install, then run the generator) shares one location and relative paths resolve.
- Write the *final deliverable* (the .pptx/.docx/etc.) to where the user expects, and report its path — don't leave it buried in the scratch dir.

## Examples

Run git status (real project — explicit cwd):
  run_shell(command="git status", cwd="C:/Users/me/project")

Run a Python script (real project — explicit cwd):
  run_shell(command="python my_script.py", cwd="C:/Users/me/project")

NPM build in the user's app (explicit cwd):
  run_shell(command="npm run build", cwd="C:/Users/me/myapp")

Scratch build (OMIT cwd — runs in ~/.gator/work):
  run_shell(command="npm install pptxgenjs")
  run_shell(command="node build_deck.js")
