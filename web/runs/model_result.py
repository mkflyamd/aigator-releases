"""What the model is told about a run: the record's facts, never a verdict on whether the command "worked"."""
from __future__ import annotations

_ACTIVE_NOTES = {
    "awaiting_approval": "The user has not clicked Run yet. Wait for them; do not propose it again.",
    "preparing": "The command is still running. Ask the user to tell you when it finishes.",
    "running": "The command is still running. Ask the user to tell you when it finishes.",
}
_END_NOTES = {
    "denied": "The user declined to run it. Do not retry; carry on without it or ask what they want.",
    "policy_blocked": "Running commands on this computer is turned off by the administrator. Do not retry.",
    "expired": "The user did not click Run within 10 minutes. Propose the command again only if they ask.",
    "interrupted": "AI Gator restarted while the command was running. What it did before that is not recorded.",
    "cancelled": "The user stopped the command and its process tree was stopped.",
    "timed_out": "The command reached its time limit and its process tree was stopped.",
}
_ABNORMAL_EXIT_NOTE = (
    "A program can exit with an error code after it has already started something. "
    "Check urls_seen, ports_opened and children_left before telling the user anything is down; "
    "probe_local_url can test an address the run printed."
)


def exit_class(exit_info: dict | None) -> str:
    if not exit_info:
        return "none"
    if exit_info.get("code") == 0:
        return "zero"
    return "ntstatus_range" if exit_info.get("is_crash_value") else "nonzero"


def model_result(record: dict, result: dict | None) -> dict:
    """The one result shape: run_id, state, exit, facts, capped stdout and stderr, and a note when one applies."""
    state = record.get("state", "")
    facts = dict(record.get("facts") or {})
    exit_info = record.get("exit")
    out: dict = {"run_id": record.get("id", ""), "state": state}
    note = _ACTIVE_NOTES.get(state) or _END_NOTES.get(state, "")
    if state == "failed_to_start":
        reason = record.get("reason") or record.get("error") or "the command did not start"
        note = f"The command did not start: {reason}."
    if exit_info:
        out["exit"] = {"code": exit_info.get("code"), "hex": exit_info.get("hex"), "class": exit_class(exit_info)}
        if exit_info.get("code") != 0 and any(facts.get(k) for k in ("urls_seen", "ports_opened", "children_left")):
            note = (note + " " + _ABNORMAL_EXIT_NOTE).strip()
    if facts:
        out["facts"] = facts
    result = result or {}
    for key in ("stdout", "stderr", "error", "cwd", "ran_on"):
        if result.get(key):
            out[key] = result[key]
    if "stdout" not in out and "stderr" not in out and record.get("output_tail"):
        out["stdout"] = record["output_tail"]
    if note:
        out["message"] = note
    return out
