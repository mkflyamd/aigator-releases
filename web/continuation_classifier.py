"""Continuation classifier — runs before skill detection on every turn.

Two public functions:
  classify(message, state) -> ClassifierResult
      Rule-based, no LLM call. Returns one of four modes.
  detect_pending(assistant_text, turn_index) -> PendingInfo | None
      Scans the last 3 sentences of an assistant response to set up
      pending state for the next turn.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from task_state import PendingInfo, TaskState


# ── detect_pending helpers ────────────────────────────────────────────────────

_CONFIRM_PHRASES = [
    "shall i", "should i", "do you want me to", "would you like me to",
    "want me to", "ok to proceed", "is that correct", "is that right",
    "shall i send", "shall i save", "shall i create", "shall i add",
    "shall i update", "shall i delete", "shall i post",
]

# (trigger phrases, expected_format, purpose)
_DATA_FORMATS: list[tuple[list[str], str, str]] = [
    (["email address", "their email", "recipient email", "your email"], "email", "email_address"),
    (["their name", "recipient's name", "full name", "who should i address"], "name", "recipient_name"),
    (["what date", "which date", "by when", "start date", "end date", "what time"], "date", "date_input"),
    (["how many", "what number", "what count", "what quantity"], "number", "number_input"),
    (["please provide", "please share", "can you give me", "what is the",
      "what would you like", "what should i use"], "any", "generic_input"),
]


def _last_n_sentences(text: str, n: int) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    return " ".join(sentences[-n:]).lower()


def detect_pending(assistant_text: str, turn_index: int) -> PendingInfo | None:
    """Scan the tail of an assistant response for question/confirmation signals.

    Returns a PendingInfo if the model is clearly awaiting user input,
    None otherwise.
    """
    tail = _last_n_sentences(assistant_text, 3)

    # Confirmation first (higher priority than data input)
    for phrase in _CONFIRM_PHRASES:
        if phrase in tail:
            return PendingInfo(
                type="confirmation",
                expected_format=None,
                purpose="action_confirm",
                asked_on_turn=turn_index,
            )

    # Data input — check for trigger phrases (some need question mark, some don't)
    for trigger_list, fmt, purpose in _DATA_FORMATS:
        for trigger in trigger_list:
            if trigger in tail:
                # "please provide" and similar generic phrases don't need a question mark
                if trigger.startswith("please") or trigger.startswith("can you") or trigger.startswith("what would"):
                    return PendingInfo(
                        type="data_input",
                        expected_format=fmt,
                        purpose=purpose,
                        asked_on_turn=turn_index,
                    )
                # Other triggers require a question mark at the end
                elif tail.rstrip().endswith("?"):
                    return PendingInfo(
                        type="data_input",
                        expected_format=fmt,
                        purpose=purpose,
                        asked_on_turn=turn_index,
                    )

    return None


# ── classify helpers ──────────────────────────────────────────────────────────

_EMAIL_RE  = re.compile(r"^[\w.+%-]+@[\w.-]+\.[a-z]{2,}$", re.IGNORECASE)
_DATE_RE   = re.compile(r"^\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?$|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
_NAME_RE   = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")

_FORMAT_PATTERNS: dict[str, re.Pattern] = {
    "email":  _EMAIL_RE,
    "date":   _DATE_RE,
    "number": _NUMBER_RE,
    "name":   _NAME_RE,
    "any":    re.compile(r".+"),
}

_CONFIRM_TOKENS = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go ahead",
    "do it", "proceed", "confirm", "confirmed", "correct", "sounds good",
    "looks good", "perfect", "please do", "go for it", "absolutely",
})

# Tokens that only count as confirmations when they appear as the entire message
# (or very short message ≤3 words), to avoid matching "right column", "great but..."
_WEAK_CONFIRM_TOKENS = frozenset({"great", "right", "exactly", "please"})

# If any negation word appears before or adjacent to a confirm token, it's not a confirmation.
_NEGATION_RE = re.compile(
    r"\b(not|no|don't|dont|never|cancel|stop|wrong|incorrect|nope|nah|bad|disagree)\b",
    re.IGNORECASE,
)

# Multi-word phrases checked as substrings of msg_lower
_INHERIT_PHRASES = frozenset({
    "add it", "add that", "use that", "try again", "redo", "retry",
    "change it", "update it", "fix it", "keep going", "and also",
    "also add", "also include", "do the same", "same thing",
    "make it", "change to", "update to", "remove it", "delete it",
})

_PRONOUN_RE = re.compile(
    r"\b(it|that|this|them|those|the same|the file|the email|the doc|the sheet|the slide)\b",
    re.IGNORECASE,
)


@dataclass
class ClassifierResult:
    mode: str                              # "confirmation" | "data_input" | "inherit" | "new"
    reason: str                            # debug label logged to console
    resolved_pending: PendingInfo | None = None


def _low_entropy(msg: str) -> bool:
    return len(msg.split()) <= 4


def classify(message: str, state: TaskState | None) -> ClassifierResult:
    """Classify a user message relative to the current task state.

    Returns ClassifierResult.mode:
      "confirmation" — user confirmed a pending action; inherit skills
      "data_input"   — user supplied expected data format; inherit skills
      "inherit"      — high-confidence continuation; inherit skills
      "new"          — ambiguous or new request; fall through to skill detector
    """
    msg = message.strip()
    msg_lower = msg.lower()

    # Rule 1: no prior state
    if state is None or not state.active_skills:
        return ClassifierResult(mode="new", reason="no_prior_state")

    # Rule 2: pending confirmation
    if state.pending and state.pending.type == "confirmation":
        has_negation = bool(_NEGATION_RE.search(msg_lower))
        if not has_negation:
            tokens = {w.strip(".,!?") for w in msg_lower.split()}
            strong_match = bool(tokens & _CONFIRM_TOKENS or
                                any(p in msg_lower for p in _CONFIRM_TOKENS if " " in p))
            weak_match = bool(tokens & _WEAK_CONFIRM_TOKENS and len(tokens) <= 3)
            if strong_match or weak_match:
                return ClassifierResult(mode="confirmation", reason="confirm_vocab",
                                        resolved_pending=state.pending)
            if _low_entropy(msg) and _PRONOUN_RE.search(msg):
                return ClassifierResult(mode="confirmation", reason="low_entropy_pronoun",
                                        resolved_pending=state.pending)

    # Rule 3: pending data input — check format match
    if state.pending and state.pending.type == "data_input":
        fmt = state.pending.expected_format or "any"
        pattern = _FORMAT_PATTERNS.get(fmt, _FORMAT_PATTERNS["any"])
        if pattern.match(msg):
            return ClassifierResult(mode="data_input", reason=f"format_match:{fmt}",
                                    resolved_pending=state.pending)

    # Rule 4: no pending, but high-confidence continuation
    if state.confidence >= 0.75 and not _NEGATION_RE.search(msg_lower):
        if any(phrase in msg_lower for phrase in _INHERIT_PHRASES):
            return ClassifierResult(mode="inherit", reason="inherit_phrase")
        if _low_entropy(msg) and _PRONOUN_RE.search(msg):
            return ClassifierResult(mode="inherit", reason="low_entropy_pronoun")

    # Rule 5: fall through
    return ClassifierResult(mode="new", reason="no_signal")
