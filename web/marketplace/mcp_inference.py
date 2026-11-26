"""Infer how to launch an MCP server that a skill ships as plain Python files.

A skill written for Claude may carry a stdio MCP server (a FastMCP script plus a
pyproject.toml) and rely on a setup script to register it. Gator has no such script,
so this works the launch command out from the files themselves. It is a pure function
of the file contents: the preview digest and everything the user approves stay the same.
"""
from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass

_SERVER_CLASSES = {"FastMCP", "Server", "MCPServer"}
_SKIPPED_DIRS = {"tests", "test", "node_modules", "venv", "site-packages", "__pycache__"}
_MAX_SOURCE_BYTES = 512 * 1024
_SERVER_PACKAGES = {"fastmcp", "mcp"}
_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXACT_PIN = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(\[[A-Za-z0-9._,\s-]*\])?\s*===?\s*[A-Za-z0-9][A-Za-z0-9._+!-]*\s*(;.*)?$")
_EXACT_PYTHON = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class LaunchSpec:
    name: str
    entry: str
    dependencies: tuple[str, ...]
    python: str = ""

    command = "uv"

    def args(self) -> list[str]:
        out = ["run", "--no-project"]
        if self.python:
            out += ["--python", self.python]
        out += [f"--with={dep}" for dep in self.dependencies]
        out.append(self.entry)
        return out

    def unpinned(self) -> list[str]:
        """Packages not pinned with ==, and a Python request that is not an exact X.Y.Z."""
        out = [dep for dep in self.dependencies if not _EXACT_PIN.match(dep)]
        if self.python and not _EXACT_PYTHON.match(self.python):
            out.append("Python " + self.python)
        return out

    def to_record(self) -> dict:
        return {"name": self.name, "entry": self.entry, "dependencies": list(self.dependencies), "python": self.python}

    @classmethod
    def from_record(cls, record: dict) -> "LaunchSpec":
        return cls(
            name=record["name"],
            entry=record["entry"],
            dependencies=tuple(record["dependencies"]),
            python=record.get("python", ""),
        )


def infer_launch_spec(files: dict[str, bytes]) -> LaunchSpec | None:
    entries = [path for path in sorted(files) if _is_server_entry(path, files[path])]
    if len(entries) != 1:
        return None
    meta = _project_metadata(files.get("pyproject.toml"))
    if meta is None:
        return None
    dependencies, python = meta
    if not any(_requirement_name(dep) in _SERVER_PACKAGES for dep in dependencies):
        return None
    entry = entries[0]
    return LaunchSpec(
        name=_server_name(files, entry),
        entry=entry,
        dependencies=tuple(dependencies),
        python=python,
    )


def _is_server_entry(path: str, raw: bytes) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if not name.endswith(".py") or name.startswith(("test_", "-")):
        return False
    if any(part.startswith(".") or part in _SKIPPED_DIRS for part in parts[:-1]):
        return False
    if len(raw) > _MAX_SOURCE_BYTES:
        return False
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        return False
    return _imports_server_library(tree) and _constructs_server(tree) and _runs_when_main(tree)


def _imports_server_library(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "fastmcp" or a.name.startswith(("fastmcp.", "mcp.server")) for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "fastmcp" or node.module.startswith(("fastmcp.", "mcp.server")):
                return True
    return False


def _constructs_server(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if called in _SERVER_CLASSES:
                return True
    return False


def _calls_run(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
        for n in ast.walk(node)
    )


def _runs_when_main(tree: ast.Module) -> bool:
    runners = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_run(n)}
    for node in tree.body:
        if isinstance(node, ast.If) and _is_main_guard(node.test):
            if _calls_run(node):
                return True
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in runners for n in ast.walk(node)):
                return True
    return False


def _is_main_guard(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _project_metadata(raw: bytes | None) -> tuple[list[str], str] | None:
    if raw is None:
        return None
    try:
        project = tomllib.loads(raw.decode("utf-8")).get("project")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(project, dict):
        return None
    deps = project.get("dependencies")
    python = project.get("requires-python", "")
    if not isinstance(deps, list) or not deps or not all(isinstance(d, str) and _safe_value(d) for d in deps):
        return None
    if not isinstance(python, str) or (python and not _safe_value(python)):
        return None
    return [d.strip() for d in deps], python.strip()


def _safe_value(value: str) -> bool:
    return bool(value.strip()) and not value.strip().startswith("-") and not _UNSAFE.search(value)


def _requirement_name(requirement: str) -> str:
    match = _REQ_NAME.match(requirement)
    return match.group(1).lower().replace("_", "-") if match else ""


def _server_name(files: dict[str, bytes], entry: str) -> str:
    skill_md = files.get("SKILL.md", b"").decode("utf-8", errors="replace")
    match = re.search(r"^name:\s*(.+?)\s*$", skill_md.split("\n---", 1)[0], re.MULTILINE)
    raw = match.group(1).strip("\"'") if match else entry.rsplit("/", 1)[-1].removesuffix(".py")
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "skill-server"
