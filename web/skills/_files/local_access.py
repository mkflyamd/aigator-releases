"""The user's approval before a file tool reads a local file AI Gator did not write.

Reuses the sandbox access requests (sandbox/approvals.py): only the CSRF-guarded approve
route can approve one, so the model cannot grant itself access.
"""
from __future__ import annotations

import os
from collections.abc import Callable

from config import OUTPUTS_DIR
from sandbox import approvals
from sandbox.paths import PathNotGrantable, is_within, normalize_grant_paths

_ASK_MSG = (
    "The user must approve reading this file first; an approval card is now shown in the chat. "
    "Tell the user briefly which file you want to read and why, then stop and wait. When the user "
    "says they approved, call {tool} again with exactly the same arguments. If they deny, do not retry."
)
_DENIED_MSG = "The user denied reading this file. Do not retry; continue without it or ask the user what to do."
_EXPIRED_MSG = "This approval expired (approvals last 10 minutes). Ask the user before requesting it again."


def require_local_read(
    context_id: str, local_path: str, tool: str, destination: str = "",
    destination_label: Callable[[], str] = lambda: "",
) -> tuple[str, dict | None]:
    """(path to read, None) when the file may be read now, else (path, the result to return to the model).

    Files under AI Gator's own outputs folder need no approval. Any other file needs the user's
    Allow for this one call, bound to the destination so an approval cannot be reused to send the
    file somewhere else. Read the returned path, not the argument: it is the one that was checked."""
    if not os.path.exists(os.path.expanduser(local_path)):
        return local_path, None  # nothing to read: the tool reports the missing file itself
    try:
        (path,) = normalize_grant_paths(local_path)
    except PathNotGrantable as exc:
        return local_path, {"error": f"{exc} Do not retry with this value."}
    checked = str(path)
    if is_within(path, OUTPUTS_DIR):
        return checked, None
    tab, read = context_id or "default", [checked]
    status, req = approvals.lookup(tab, read, [], [], tool=tool, command=destination)
    if status == "approved":
        return checked, None
    if status == "denied":
        return checked, {"error": _DENIED_MSG}
    if status == "expired":
        return checked, {"error": _EXPIRED_MSG}
    if req is None:
        req = approvals.create(tab, read, [], [], tool=tool, command=destination)
    card = {
        "request_id": req.id, "read_paths": list(req.read_paths), "write_paths": [],
        "network_hosts": [], "context_id": req.context_id, "tool": tool,
        "destination": destination_label(),
    }
    return checked, {
        "approval_required": True, "request_id": req.id, "read_paths": card["read_paths"],
        "message": _ASK_MSG.format(tool=tool), "_sandbox_approval": card,
    }
