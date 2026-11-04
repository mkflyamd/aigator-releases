"""Every kind of permission AI Gator can ask for, and what its card may offer.

A category id is also its per-tab grant key in data_sources ("data:Jira", "web:<host>",
"capability:code_runner", "mcp:<connection>"). A new gate adds one entry here; the
Settings page and the card buttons are built from this list.
"""
from __future__ import annotations

from dataclasses import dataclass

SCOPES = ("always", "tab", "once")


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
    Category("capability:shell_runner", "Run shell commands", "Let the assistant run shell commands in the sandbox.",
             "high", always_on_card=False),
)


def _native_categories() -> list[Category]:
    import data_sources

    seen: dict[str, Category] = {}
    for label in data_sources._NATIVE_SOURCES.values():
        key = f"data:{label}"
        seen.setdefault(key, Category(key, label, "", "low"))
    return list(seen.values())


def mcp_category(category_id: str, label: str = "") -> Category:
    name = label or category_id.removeprefix("mcp:")
    return Category(category_id, name, f"Use the {name} MCP server on your behalf.", "low")


def known() -> list[Category]:
    """Categories that always exist, in display order. MCP servers come and go, so get() builds those on demand."""
    return _native_categories() + list(_STATIC)


def get(category_id: str, label: str = "") -> Category | None:
    for category in known():
        if category.id == category_id:
            return category
    if category_id.startswith("mcp:") and len(category_id) > len("mcp:"):
        return mcp_category(category_id, label)
    return None
