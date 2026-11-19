"""Draft the share message as an email. Drafts only: the author approves it before it sends."""

import html


def _with_note(note: str, message: str, message_html: str) -> tuple[str, str]:
    """Put the sender's own words in front of the shared message, in both the plain and the HTML form."""
    note = (note or "").strip()
    if not note:
        return message, message_html
    lines = note.splitlines()
    note_html = "<p>" + "<br>".join(html.escape(line, quote=False) for line in lines) + "</p>"
    return f"{note}\n\n{message}", (note_html + message_html if message_html else message_html)


def build(*, skill_id: str, people: list[dict], message: str, message_html: str = "", note: str = "") -> dict:
    """Create one email approval draft to everyone. `unmatched` is always empty: an email needs no lookup."""
    from skills.email.tools import _tool_email_open_compose

    message, message_html = _with_note(note, message, message_html)
    names = [" ".join((p.get("name") or "").replace(",", " ").split()) for p in people]
    draft = _tool_email_open_compose(
        to=",".join(p["email"].lower() for p in people),
        to_names=",".join(names) if all(names) else "",
        subject=f'AI Gator skill shared with you: "{skill_id}"',
        body=message,
        body_html=message_html,
    )
    return {"drafts": [draft], "unmatched": []}
