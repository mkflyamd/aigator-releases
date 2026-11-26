"""Draft the share message as an email. Drafts only: the author approves it before it sends."""

import hashlib
import json


def content_digest(params: dict) -> str:
    """Fingerprint of what an email draft would send: recipients, subject and the rendered body."""
    from skills import _rich_text as rich

    markup = rich.normalize(
        body=params.get("message" if "message" in params else "body") or "", body_html=params.get("body_html") or ""
    )

    def addresses(field: str) -> list[str]:
        return [a.strip().lower() for a in (params.get(field) or "").split(",") if a.strip()]

    shown = [addresses("to"), addresses("cc"), addresses("bcc"), params.get("subject") or "", rich.render("email", markup).content]
    return hashlib.sha256(json.dumps(shown).encode("utf-8")).hexdigest()


def build(*, skill_id: str, people: list[dict], message: str) -> dict:
    """Create one email approval draft to everyone. `unmatched` is always empty: an email needs no lookup."""
    from skills._drafts import get_draft
    from skills.email.tools import _tool_email_open_compose

    names = [" ".join((p.get("name") or "").replace(",", " ").split()) for p in people]
    draft = _tool_email_open_compose(
        to=",".join(p["email"].lower() for p in people),
        to_names=",".join(names) if all(names) else "",
        subject=f'AI Gator skill shared with you: "{skill_id}"',
        body=message,
    )
    stored = get_draft(draft["data"]["draft_id"])
    stored["share_digest"] = content_digest(stored["params"])
    draft["data"]["locked"] = True
    return {"drafts": [draft], "unmatched": []}
