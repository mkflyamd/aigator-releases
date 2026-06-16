---
name: File Ops
description: Read, write, list, search, and find local files and directories on the user's machine
version: "1.0"
---

# File Ops

Use this skill for local file operations — reading, writing, listing, and searching files.

## When to use each tool

| Task | Tool |
|------|------|
| Read a file's content | read_file |
| Write or create a file | write_file |
| List what's in a folder | list_dir |
| Find files by name pattern | glob_files |
| Search file contents for text | grep_files |

## Rules

- Never delete files — tell the user to delete manually.
- Prefer read_file over run_shell cat — faster, no subprocess.
- Prefer list_dir over run_shell ls — structured output, no parsing needed.
- Binary files (images, PDFs): read_file returns binary=true, base64=... — do NOT paste base64 into chat.
- Files larger than 5 MB: returns error with size — tell the user.

## Examples

Read a file:
  read_file(path=r"C:\Users\me\notes.txt")

Write output:
  write_file(path=r"C:\Users\me\output\report.md", content="# Report\n...")

List a folder:
  list_dir(path=r"C:\Users\me\project")

Find Python files:
  glob_files(pattern="*.py", base_path=r"C:\Users\me\project")

Search for a function:
  grep_files(pattern="def authenticate", path=r"C:\Users\me\project", file_glob="*.py")
