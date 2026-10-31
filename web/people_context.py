"""People already seen in this request's tool results, used to resolve a bare name to the right person.

Any tool that reads a conversation (Teams chat, email thread, ...) puts `participants`
([{"name", "email"}]) in its result. search_people then ranks those people first, so a first name
mentioned in a chat is not resolved by a global directory search that ignores who is in the chat.
"""

_MAX_DEPTH = 4


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
                        if email and email not in known:
                            known[email] = {"name": str(p.get("name") or "").strip(), "email": email}
                else:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(result, 0)


def _matches(query: str, person: dict) -> bool:
    haystack = f"{person.get('name', '')} {person.get('email', '')}".lower()
    tokens = [t for t in query.lower().replace(",", " ").split() if t]
    return bool(tokens) and all(t in haystack for t in tokens)


def apply(query: str, result: dict, known: dict[str, dict]) -> dict:
    """Put people from the conversation first in a search_people result and mark them.

    When exactly one person from the conversation matches the query, the result says so and tells
    the model to use that person instead of asking which one was meant.
    """
    if not known or not isinstance(result, dict) or result.get("error"):
        return result
    in_context = [p for p in known.values() if _matches(query, p)]
    if not in_context:
        return result
    emails = {p["email"] for p in in_context}
    found = {str(p.get("email", "")).lower(): p for p in result.get("people", [])}
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
