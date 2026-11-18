"""Draft the share message as an email. Drafts only: the author approves it before it sends."""


def build(*, skill_id: str, people: list[dict], message: str) -> dict:
    """Create one email approval draft to everyone. `unmatched` is always empty: an email needs no lookup."""
    from skills.email.tools import _tool_email_open_compose

    names = [" ".join((p.get("name") or "").replace(",", " ").split()) for p in people]
    draft = _tool_email_open_compose(
        to=",".join(p["email"].lower() for p in people),
        to_names=",".join(names) if all(names) else "",
        subject=f'AI Gator skill shared with you: "{skill_id}"',
        body=message,
    )
    return {"drafts": [draft], "unmatched": []}
