"""Declared permissions of a marketplace skill and the summary the install card shows."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_ENTRIES = 20
MAX_ENTRY_LEN = 200
MAX_HOOK_LEN = 300
_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)
_PLUGIN_JSON = ".claude-plugin/plugin.json"


def _clean_list(value) -> tuple[str, ...] | None:
    """() for a missing value, a deduped tuple for a valid list, None when malformed."""
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_ENTRY_LEN:
            return None
        if item not in out:
            out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class Permissions:
    filesystem: tuple[str, ...] = ()
    network: tuple[str, ...] = ()
    invalid: bool = False

    @property
    def wants_network(self) -> bool:
        return bool(self.network) and not self.invalid

    def to_dict(self) -> dict:
        return {"filesystem": list(self.filesystem), "network": list(self.network), "invalid": self.invalid}

    @classmethod
    def from_dict(cls, data) -> "Permissions":
        if not isinstance(data, dict):
            return cls()
        fs, net = _clean_list(data.get("filesystem")), _clean_list(data.get("network"))
        if fs is None or net is None or data.get("invalid"):
            return cls(invalid=True)
        return cls(filesystem=fs, network=net)


def parse_permissions(raw) -> Permissions:
    if raw is None:
        return Permissions()
    if not isinstance(raw, dict):
        return Permissions(invalid=True)
    fs, net = _clean_list(raw.get("filesystem")), _clean_list(raw.get("network"))
    if fs is None or net is None:
        return Permissions(invalid=True)
    return Permissions(filesystem=fs, network=net)


def _frontmatter(data: bytes) -> dict:
    match = _FRONTMATTER.match(data.decode("utf-8", errors="replace").lstrip("\ufeff"))
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def declared_permissions(files: dict[str, bytes]) -> Permissions:
    """plugin.json's `permissions` wins; otherwise the union over every SKILL.md frontmatter."""
    raw_plugin = files.get(_PLUGIN_JSON)
    if raw_plugin is not None:
        try:
            plugin = json.loads(raw_plugin.decode("utf-8", errors="replace"))
        except ValueError:
            plugin = None
        if isinstance(plugin, dict) and "permissions" in plugin:
            return parse_permissions(plugin["permissions"])
    fs: list[str] = []
    net: list[str] = []
    for path in sorted(files):
        if path.rsplit("/", 1)[-1] != "SKILL.md":
            continue
        front = _frontmatter(files[path])
        if "permissions" not in front:
            continue
        perms = parse_permissions(front["permissions"])
        if perms.invalid:
            return Permissions(invalid=True)
        fs += [p for p in perms.filesystem if p not in fs]
        net += [h for h in perms.network if h not in net]
    return Permissions(filesystem=tuple(fs), network=tuple(net))


def files_digest(files: dict[str, bytes]) -> str:
    outer = hashlib.sha256()
    for path in sorted(files):
        outer.update(path.encode("utf-8"))
        outer.update(b"\0")
        outer.update(hashlib.sha256(files[path]).digest())
    return outer.hexdigest()


def _hook_commands(files: dict[str, bytes]) -> list[str]:
    raw = files.get("hooks.json")
    if raw is None:
        return []
    try:
        config = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return []
    hooks = config.get("hooks") if isinstance(config, dict) else None
    out: list[str] = []
    for hook in hooks if isinstance(hooks, list) else []:
        command = hook.get("command") if isinstance(hook, dict) else None
        if isinstance(command, str) and command.strip():
            out.append(command[:MAX_HOOK_LEN])
    return out


def _mcp_server_names(files: dict[str, bytes]) -> list[str]:
    from marketplace import installer

    try:
        return sorted(installer._discover_plugin_mcp_manifest_from_files(files) or {})
    except Exception:
        return []


def summarize_package(files: dict[str, bytes]) -> dict:
    perms = declared_permissions(files)
    hooks = _hook_commands(files)
    bin_files = sorted(p for p in files if p.startswith("bin/"))
    servers = _mcp_server_names(files)
    has_tools = "tools.py" in files
    lines: list[str] = []
    if perms.invalid:
        lines.append("The permission declaration in this package is invalid, so it gets no folder or network access.")
    if perms.filesystem:
        lines.append("Reads these folders: " + ", ".join(perms.filesystem))
    else:
        lines.append("Reads these folders: none declared")
    if perms.network:
        lines.append("Network access, not limited to these hosts: " + ", ".join(perms.network))
    else:
        lines.append("Network access: none declared")
    if has_tools:
        lines.append("Adds tools the assistant can call. They run in a restricted sandbox, "
                     "with the folders and network access shown above.")
    for command in hooks:
        lines.append("Runs this command on your computer before an email or Teams message is sent, "
                     "in a restricted sandbox: " + command)
    if bin_files:
        lines.append("Ships programs: " + ", ".join(bin_files))
    for name in servers:
        lines.append(f"Starts the MCP server '{name}' on your computer (not sandboxed).")
    return {
        "permissions": perms.to_dict(),
        "has_tools": has_tools,
        "hooks": hooks,
        "bin": bin_files,
        "mcp_servers": servers,
        "lines": lines,
        "digest": files_digest(files),
    }


def readable_paths(perms: Permissions) -> list[Path]:
    """Declared folders that exist and may be granted. The never-grantable list always wins."""
    from sandbox.paths import PathNotGrantable, is_secrets_path, normalize_grant_paths

    if perms.invalid:
        return []
    out: list[Path] = []
    for item in perms.filesystem:
        try:
            resolved = normalize_grant_paths([item])
        except (PathNotGrantable, OSError, ValueError):
            continue
        out += [p for p in resolved if not is_secrets_path(p) and p not in out]
    return out
