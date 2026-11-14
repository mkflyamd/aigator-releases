"""Find web/ modules that skills import but PyInstaller cannot see.

Skills ship as data files and are loaded with importlib at runtime, so their
imports are invisible to PyInstaller's static analysis. Any web/ module that is
only imported from a skill must be listed in hiddenimports explicitly.
"""

import ast
from pathlib import Path


def _local_module(web: Path, dotted: str) -> bool:
    parts = dotted.split(".")
    base = web.joinpath(*parts)
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def skill_imported_web_modules(web: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted((web / "skills").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            for name in names:
                if name.split(".")[0] != "skills" and _local_module(web, name):
                    found.add(name)
    return found
