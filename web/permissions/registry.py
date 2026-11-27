"""Every kind of permission AI Gator can ask for, and what its card may offer.

A category id is also its per-tab grant key in data_sources ("data:Jira:read", "web:<host>",
"capability:code_runner", "mcp:<connection>:read"). A new gate adds one entry here; the
Settings page and the card buttons are built from this list.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import actions

SCOPES = ("always", "tab", "once")
SANDBOX_SHELL = "sandbox:shell"   # extra folders/network for a shell command; its saved rules live in sandbox/saved_permissions
SANDBOX_PYTHON = "sandbox:python"


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    description: str
    risk: str  # "low" = the card leads with "Always allow"; "high" = it leads with "Allow in this tab"
    scopes: tuple[str, ...] = ("always", "tab")
    subject_scoped: bool = False  # "Always allow" remembers one subject (a website), not the whole category
    always_on_card: bool = True  # False = "Always allow" can only be set in Settings, never from a card

    @property
    def rememberable(self) -> bool:
        return "always" in self.scopes


_STATIC = (
    Category("web", "Websites", "Open web pages the assistant asks for. Each website is remembered separately.",
             "low", subject_scoped=True),
    Category("browser", "Browser control", "Drive a browser window to search, navigate and complete web tasks.",
             "high", always_on_card=False),
    Category("schedule_task", "Scheduled tasks", "Create tasks that run later on their own.",
             "high", always_on_card=False),
    Category("capability:code_runner", "Run Python code", "Let the assistant run Python in the sandbox.",
             "high", always_on_card=False),
    Category("failover", "Switch to the fallback model",
             "When the main model stalls, resend the conversation to the fallback model instead.",
             "high", scopes=("always", "tab", "once"), always_on_card=False),
    Category("capability:shell_runner", "Run shell commands", "Let the assistant run shell commands in the sandbox.",
             "high", always_on_card=False),
    Category(SANDBOX_SHELL, "Shell command access",
             "Let shell commands reach extra folders or the network. Each saved set of folders and programs is listed below.",
             "high", scopes=("always", "tab"), subject_scoped=True),
    Category(SANDBOX_PYTHON, "Python code access", "Let Python code reach extra folders or the network.",
             "high", scopes=("tab", "once")),
)


def _action_category(prefix: str, name: str, action: str) -> Category:
    return Category(f"{prefix}:{action}", f"{name}: {actions.PHRASE[action]}", actions.DESCRIPTION[action],
                    "high" if action == actions.WRITE_PUBLIC else "low")


def _native_categories() -> list[Category]:
    import data_sources
    import shared

    found: dict[str, set[str]] = {}
    for skill_id, label in data_sources._NATIVE_SOURCES.items():
        kinds = found.setdefault(label, set())
        for tool in shared.SKILL_TOOLS_MAP.get(skill_id, ()):
            kinds |= actions.gate_actions_possible(tool)
    categories = []
    for label, kinds in found.items():
        for action in actions.REMEMBERABLE:
            if action in kinds:
                categories.append(_action_category(f"data:{label}", label, action))
    return categories


def mcp_category(category_id: str, label: str = "") -> Category | None:
    """An MCP server's category is "mcp:<connection>:<action type>". Only a server's read-only tools and the tools it
    parks as drafts have one; every other MCP tool asks on every call."""
    server, _, action = category_id.rpartition(":")
    if action not in (actions.READ, actions.WRITE_PRIVATE) or not server.removeprefix("mcp:") or not server.startswith("mcp:"):
        return None
    name = label or f"{server.removeprefix('mcp:')} (MCP server)"
    return _action_category(server, name, action)


def known() -> list[Category]:
    """Categories that always exist, in display order. MCP servers come and go, so get() builds those on demand."""
    return _native_categories() + list(_STATIC)


def get(category_id: str, label: str = "") -> Category | None:
    for category in known():
        if category.id == category_id:
            return category
    return mcp_category(category_id, label)
