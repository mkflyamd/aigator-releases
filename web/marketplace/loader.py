"""Hot-load and unload tools.py from marketplace-installed skills."""

import importlib.util
import json
import logging
import os as _os
import re as _re
import shutil
import sys
import threading
from pathlib import Path

# Guards concurrent read-modify-write of os.environ["PATH"] across parallel skill loads.
_PATH_LOCK = threading.Lock()

import shared
from skills._skill_utils import validate_tool_contract

logger = logging.getLogger(__name__)


def load_plugin_manifest(skill_dir: Path) -> dict:
    """Return parsed plugin.json if present, else parse SKILL.md YAML frontmatter.
    Returns {} if neither exists or both are malformed."""
    plugin_json = skill_dir / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        try:
            data = json.loads(plugin_json.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Malformed plugin.json in %s — skipping", skill_dir)
            return {}
        if not isinstance(data, dict):
            logger.warning("plugin.json in %s is not a JSON object — skipping", skill_dir)
            return {}
        return data

    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        return _parse_skill_md_frontmatter(skill_md.read_text(encoding="utf-8"))

    return {}


def _parse_skill_md_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from SKILL.md. Returns {} if not present."""
    match = _re.match(r"^---\r?\n(.*?)\r?\n---", content, _re.DOTALL)
    if not match:
        return {}
    try:
        import yaml
        return yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}


# Maps skill_id → list of MCP server names started for that skill
_PLUGIN_MCP_SERVERS: dict[str, list[str]] = {}


def load_plugin_mcp(skill_id: str, skill_dir: Path) -> None:
    """Start per-plugin MCP server if .mcp.json is present.

    A prior load with the same skill_id must be cleaned up first so we don't
    leak server-name entries if the plugin's .mcp.json changed between loads.
    """
    if skill_id in _PLUGIN_MCP_SERVERS:
        unload_plugin_mcp(skill_id)

    mcp_json = skill_dir / ".mcp.json"
    if not mcp_json.exists():
        return
    try:
        config = json.loads(mcp_json.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Malformed .mcp.json for skill %s: %s", skill_id, exc)
        return

    servers = config.get("mcpServers", {})
    if not servers:
        return

    # Only track servers that actually started — otherwise unload would try to
    # stop servers that never came up, generating noise and masking real failures.
    if start_plugin_mcp(skill_id, servers):
        _PLUGIN_MCP_SERVERS[skill_id] = list(servers.keys())
        logger.info("Started MCP servers for skill %s: %s", skill_id, list(servers.keys()))


def unload_plugin_mcp(skill_id: str) -> None:
    """Stop per-plugin MCP servers when skill is disabled."""
    server_names = _PLUGIN_MCP_SERVERS.pop(skill_id, [])
    for name in server_names:
        stop_plugin_mcp(skill_id, name)
    if server_names:
        logger.info("Stopped MCP servers for skill %s", skill_id)


def start_plugin_mcp(skill_id: str, servers: dict) -> bool:
    """Delegate to mcp.manager to start servers. Returns True on success.

    TODO(P1): `mcp.manager.register_plugin_servers` is not yet implemented —
    this is scaffolding for the per-plugin MCP lifecycle wired in Task 5.
    Until the manager-side function lands, the import fails and we return
    False so the tracking dict is never populated with phantom entries.
    """
    try:
        from mcp.manager import register_plugin_servers
    except ImportError:
        logger.debug("mcp.manager.register_plugin_servers not implemented yet — skipping MCP start for %s", skill_id)
        return False
    try:
        register_plugin_servers(skill_id, servers)
        return True
    except Exception as exc:
        logger.warning("Could not start MCP for skill %s: %s", skill_id, exc)
        return False


def stop_plugin_mcp(skill_id: str, server_name: str) -> None:
    """Delegate to mcp.manager to stop a server. Separated for testability.

    TODO(P1): paired with `register_plugin_servers` above — both land together.
    """
    try:
        from mcp.manager import deregister_plugin_server
    except ImportError:
        logger.debug("mcp.manager.deregister_plugin_server not implemented yet — skipping MCP stop for %s", skill_id)
        return
    try:
        deregister_plugin_server(skill_id, server_name)
    except Exception as exc:
        logger.warning("Could not stop MCP server %s for skill %s: %s", server_name, skill_id, exc)


def inject_bin_path(skill_dir: Path, skill_id: str | None = None) -> None:
    """Add skill_dir/bin/ to PATH if it exists and isn't already present.

    When skill_id is provided, the injected path is tracked in
    shared.SKILL_BIN_PATHS so unload_skill_tools can remove it.
    """
    bin_dir = skill_dir / "bin"
    if not bin_dir.is_dir():
        return
    bin_str = str(bin_dir)
    with _PATH_LOCK:
        current = _os.environ.get("PATH", "")
        entries = current.split(_os.pathsep)
        if bin_str not in entries:
            _os.environ["PATH"] = bin_str + _os.pathsep + current
            logger.info("Added %s to PATH", bin_str)
        if skill_id is not None:
            shared.SKILL_BIN_PATHS[skill_id] = bin_str


def _remove_bin_path(skill_id: str) -> None:
    """Strip a previously-injected bin path from PATH (called on unload)."""
    bin_str = shared.SKILL_BIN_PATHS.pop(skill_id, None)
    if not bin_str:
        return
    with _PATH_LOCK:
        current = _os.environ.get("PATH", "")
        entries = [e for e in current.split(_os.pathsep) if e != bin_str]
        _os.environ["PATH"] = _os.pathsep.join(entries)


def load_skill_tools(skill_id: str, skill_dir: Path, tier: str) -> dict:
    """Load tools.py from skill_dir into shared dispatch. Returns {"ok": True} or {"ok": False, "error": ...}.

    Tool names are namespaced as {skill_id}__{tool_name} to prevent collisions.
    If tools.py does not exist, returns ok=True (SKILL.md-only skill is valid).
    """
    # bin/ and .mcp.json must be processed regardless of whether tools.py exists
    # — a plugin can ship MCP-bridged tools or CLI shims with no Python tools.py.
    inject_bin_path(skill_dir, skill_id)
    load_plugin_mcp(skill_id, skill_dir)

    # Register skill dependencies from SKILL.md.
    # Explicit `requires` frontmatter takes precedence; content-based auto-detection
    # is the fallback so user-created skills don't need to know the syntax.
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        try:
            skill_md_text = skill_md.read_text(encoding="utf-8")
            fm = _parse_skill_md_frontmatter(skill_md_text)
            raw_requires = fm.get("requires") or []
            if isinstance(raw_requires, list):
                deps = [
                    {"id": str(r["id"]), "reason": str(r.get("reason", ""))}
                    for r in raw_requires
                    if isinstance(r, dict) and r.get("id")
                ]
                if deps:
                    shared.SKILL_DEPENDENCIES_MAP[skill_id] = deps
            # Auto-detect shell_runner need from skill body when not explicitly declared
            if skill_id not in shared.SKILL_DEPENDENCIES_MAP:
                _shell_signals = ("gh ", "bash", "shell", "subprocess", "terminal",
                                  "```bash", "```sh", "run ", "execute ", "command")
                if any(sig in skill_md_text.lower() for sig in _shell_signals):
                    shared.SKILL_DEPENDENCIES_MAP[skill_id] = [
                        {"id": "shell_runner", "reason": "detected shell usage in skill"}
                    ]
        except Exception:
            pass  # malformed frontmatter — skip dependency registration

    tools_py = skill_dir / "tools.py"
    if not tools_py.exists():
        return {"ok": True}

    # Unload first if already registered (prevents duplicate TOOLS list entries)
    if skill_id in shared.INSTALLED_TOOL_MODULES:
        unload_skill_tools(skill_id)

    module_key = f"_marketplace_skill_{skill_id.replace('-', '_')}"

    # Evict stale cached module (handles reinstall case)
    if module_key in sys.modules:
        del sys.modules[module_key]

    # Clear __pycache__ so a replaced tools.py is never shadowed by stale bytecode
    pycache = skill_dir / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache, ignore_errors=True)

    try:
        spec = importlib.util.spec_from_file_location(module_key, tools_py)
        if spec is None or spec.loader is None:
            err = "could not build module spec for tools.py (unrecognized file type or loader)"
            shared.FAILED_SKILLS[skill_id] = err
            return {"ok": False, "error": err}
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        shared.FAILED_SKILLS[skill_id] = str(exc)
        logger.warning("Failed to load tools.py for skill %s: %s", skill_id, exc)
        return {"ok": False, "error": str(exc)}

    if not validate_tool_contract(mod, skill_id):
        err = "tool contract mismatch (TOOL_DEFS/TOOL_HANDLERS/TOOL_STATUS inconsistent)"
        shared.FAILED_SKILLS[skill_id] = err
        return {"ok": False, "error": err}

    shared.FAILED_SKILLS.pop(skill_id, None)  # clear any previous failure

    defs = getattr(mod, "TOOL_DEFS", [])
    handlers = getattr(mod, "TOOL_HANDLERS", {})
    status = getattr(mod, "TOOL_STATUS", {})

    # Namespace all tool names: skill_id__tool_name (hyphens preserved in skill_id portion)
    # Prefix every description with the marketplace tier ([Verified], [Community],
    # [Mine]) so the LLM can prefer higher-fidelity variants over [Native] ones
    # of the same domain (e.g. Anthropic's docx skill beats native docx).
    prefix = skill_id + "__"
    tier_tag = f"[{tier}] " if tier else ""
    namespaced_defs = []
    for d in defs:
        nd = dict(d)
        nd["name"] = prefix + d["name"]
        nd["description"] = f"{tier_tag}{d.get('description', '')}".rstrip()
        namespaced_defs.append(nd)

    namespaced_handlers = {prefix + k: v for k, v in handlers.items()}
    namespaced_status = {prefix + k: v for k, v in status.items()}

    # Register into shared state
    shared.TOOLS.extend(namespaced_defs)
    shared.TOOL_DISPATCH.update(namespaced_handlers)
    shared.TOOL_STATUS.update(namespaced_status)
    tool_names = {d["name"] for d in namespaced_defs}
    shared.SKILL_TOOLS_MAP.setdefault(skill_id, set()).update(tool_names)

    # Track tier and module key for future use
    shared.TOOL_TIER_MAP[skill_id] = tier
    shared.INSTALLED_TOOL_MODULES[skill_id] = module_key

    logger.info("Loaded tools.py for skill %s (tier=%s): %s", skill_id, tier, sorted(tool_names))
    return {"ok": True}


def unload_skill_tools(skill_id: str) -> None:
    """Remove all tools registered for skill_id from shared dispatch."""
    prefix = skill_id + "__"

    # Remove from TOOLS list
    shared.TOOLS[:] = [d for d in shared.TOOLS if not d["name"].startswith(prefix)]

    # Remove from TOOL_DISPATCH and TOOL_STATUS
    for key in list(shared.TOOL_DISPATCH.keys()):
        if key.startswith(prefix):
            del shared.TOOL_DISPATCH[key]
    for key in list(shared.TOOL_STATUS.keys()):
        if key.startswith(prefix):
            del shared.TOOL_STATUS[key]

    # Remove from SKILL_TOOLS_MAP
    shared.SKILL_TOOLS_MAP.pop(skill_id, None)

    # Evict cached module
    module_key = shared.INSTALLED_TOOL_MODULES.pop(skill_id, None)
    if module_key and module_key in sys.modules:
        del sys.modules[module_key]

    # Remove tier mapping and dependency declarations
    shared.TOOL_TIER_MAP.pop(skill_id, None)
    shared.TOOL_SEMAPHORES.pop(skill_id, None)
    shared.SKILL_DEPENDENCIES_MAP.pop(skill_id, None)

    unload_plugin_mcp(skill_id)

    # Strip the injected bin/ entry from PATH so a re-install picks up changes
    # and uninstalled skills don't leave dangling PATH entries pointing at deleted dirs.
    _remove_bin_path(skill_id)

    logger.info("Unloaded tools for skill %s", skill_id)
