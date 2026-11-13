"""People already seen in this request's tool results, used to resolve a bare name to the right person.

Any tool that reads a conversation (Teams chat, email thread, ...) puts `participants`
([{"name", "email"}]) in its result. search_people then ranks those people first, so a first name
mentioned in a chat is not resolved by a global directory search that ignores who is in the chat.

A participant marked "unverified" has a name taken from mail headers, which the sender controls. Such a
person only counts when the directory search also returns that email.
"""

import re

_MAX_DEPTH = 4

# Only these built-in tools build `participants` themselves. Output from browser, MCP, plugin or any
# other tool is shaped by outside parties and must never decide who a bare name resolves to.
TRUSTED_TOOLS = frozenset({"read_email", "search_email", "read_teams_chats"})


def collect(result, known: dict[str, dict]) -> None:
    """Add every participant found in a tool result to `known` (keyed by lowercase email)."""

    def walk(node, depth):
        if depth > _MAX_DEPTH:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "participants" and isinstance(value, list):
                    for p in value:
                        email = str((p or {}).get("email") or "").strip().lower()
                        if not email:
                            continue
                        entry = {"name": str(p.get("name") or "").strip(), "email": email}
                        if p.get("unverified"):
                            entry["unverified"] = True
                        if email not in known or (known[email].get("unverified") and not entry.get("unverified")):
                            known[email] = entry
                else:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(result, 0)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _matches(query: str, person: dict) -> bool:
    """Every word of the query is a whole word of the name or of the email's local part ("Ann" is not "Anne")."""
    email = str(person.get("email", "")).lower()
    query = query.strip().lower()
    if "@" in query:
        return query == email
    words = _words(str(person.get("name", ""))) | _words(email.split("@")[0])
    wanted = _words(query)
    return bool(wanted) and wanted <= words


def apply(query: str, result: dict, known: dict[str, dict]) -> dict:
    """Put people from the conversation first in a search_people result and mark them.

    When exactly one person from the conversation matches the query, the result says so and tells
    the model to use that person instead of asking which one was meant.
    """
    if not known or not isinstance(result, dict) or result.get("error"):
        return result
    found = {str(p.get("email", "")).lower(): p for p in result.get("people", [])}
    in_context = [
        p for p in known.values() if _matches(query, p) and (not p.get("unverified") or p["email"] in found)
    ]
    if not in_context:
        return result
    emails = {p["email"] for p in in_context}
    first = [{**found.get(p["email"], {"name": p["name"], "email": p["email"]}), "in_context": True} for p in in_context]
    rest = [p for e, p in found.items() if e not in emails]
    out = {**result, "people": first + rest, "total": len(first) + len(rest)}
    if len(in_context) == 1:
        out["resolved_from_context"] = in_context[0]["email"]
        out["hint"] = (
            "Exactly one match is in the conversation you already read (see resolved_from_context). "
            "Use this person and do not ask which one was meant."
        )
    return out
