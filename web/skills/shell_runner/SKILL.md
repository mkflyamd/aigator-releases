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

## Examples

Run git status:
  run_shell(command="git status", cwd="C:/Users/me/project")

Run a Python script:
  run_shell(command="python my_script.py", cwd="C:/Users/me/project")

NPM build:
  run_shell(command="npm run build", cwd="C:/Users/me/myapp")
