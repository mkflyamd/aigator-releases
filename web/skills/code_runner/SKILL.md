---
name: Code Runner
description: Execute Python code in a sandboxed subprocess — produce files, read local filesystem, run calculations, generate images and charts
version: "1.1"
---

# Code Runner

Use this skill any time you need to execute Python code — whether to produce output files, read the local filesystem, run calculations, or process data.

## When to use run_python

- User asks to "make", "create", "generate", or "build" a file
- User asks what's in a local folder or file (`what is at C:\...`, `list files in ...`, `read this file`)
- User asks you to run a calculation, transform data, or produce a chart/image
- A marketplace skill describes a Python API you should call
- Any task that requires reading from or writing to the local machine

## Local filesystem access

The subprocess runs on the user's machine and has **full read access** to the local filesystem. Use `pathlib.Path` or `os` to read files and list directories.

```python
import os
# List a directory
files = os.listdir(r'C:\Users\maykulka\pocs\agenticpoc')
for f in sorted(files):
    print(f)
```

```python
from pathlib import Path
# Read a file
text = Path(r'C:\some\file.txt').read_text(encoding='utf-8')
print(text)
```

**Write operations outside OUTPUT_DIR** will be flagged by the AST scanner and require user confirmation.

## Critical: each run_python call is a fresh subprocess

Every `run_python` call starts a **brand-new Python process** — no variables, imports, or state carry over from a previous call. If you called `from pathlib import Path` in the first block, you must import it again in the second block. Treat each call as a completely standalone script.

**Always start every code block with its full imports, even if you imported the same thing one call ago.**

Before writing any file, always create the parent directory first:

```python
# Every block must be self-contained — imports included
from pathlib import Path
import os, json

# Always mkdir before writing — parent may not exist
output = Path(OUTPUT_DIR) / 'subdir' / 'file.txt'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('hello', encoding='utf-8')
```

## Rules

- **Write output files to `OUTPUT_DIR`** — injected automatically. Never hardcode absolute output paths.
- Use absolute paths when *reading* existing local files — the user's path is real.
- Every code block must declare all its own imports — no state persists between calls.
- Use `print()` for progress so the user sees what's happening.

## Running code on behalf of another skill

When a skill's SKILL.md tells you to run code, pass that skill's id as `skill_id` so its bundled Python modules and data files become available:

```python
run_python(code="from core import process; process()", skill_id="my-skill")
```

Inside the code, two variables are injected automatically when `skill_id` is provided:
- `SKILL_DIR` — absolute path to the skill's folder (use for reading bundled templates, data files, scripts)
- The skill folder is also prepended to `sys.path`, so `from helpers import X` works for any `.py` file in the skill folder

Example reading a bundled template:
```python
from pathlib import Path
template = (Path(SKILL_DIR) / 'templates' / 'email.txt').read_text()
```

## Standard packages available

`pillow`, `numpy`, `imageio`, `matplotlib`, `json`, `csv`, `math`, `random`, `pathlib`, `os`, `glob`

## On-the-fly package install

For packages not in the standard list, pass them in the `packages` parameter:

```python
run_python(
    code="import pandas as pd; print(pd.__version__)",
    packages=["pandas"],
)
```

pip runs before the code executes. Already-installed packages are a no-op (instant). If install fails, an error is returned before the code runs.

## Example

```python
import math
from PIL import Image, ImageDraw

img = Image.new('RGB', (200, 200), (30, 30, 60))
draw = ImageDraw.Draw(img)
draw.ellipse([50, 50, 150, 150], fill=(255, 200, 0))
img.save(OUTPUT_DIR + '/circle.png')
print('Saved circle.png')
```

## Slack GIF specs

| Type | Size | Max colors | Max duration |
|---|---|---|---|
| Emoji | 128×128 | 128 | 3 sec |
| Message | 480×480 | 128 | flexible |
