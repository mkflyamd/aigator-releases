"""Should this tool call ask the user, or is it already allowed?

Order: admin policy, a rule saved with "Always allow", this tab's grant, otherwise ask.
Unattended runs (no context_id) always get "ask", so each gate keeps its existing
refusal for background work and a saved rule never widens what a background run may do.
"""
from __future__ import annotations

import logging

import data_sources
from sandbox.policy import load_policy

from . import registry, store

_log = logging.getLogger(__name__)


def persistent_allowed() -> bool:
    return load_policy().persistent_permissions != "deny"


def _rule_subject(category: registry.Category, subject: str) -> str:
    return subject.strip() if category.subject_scoped else ""


def grant_key(category: registry.Category, subject: str = "") -> str:
    """The data_sources key for this tab's grant."""
    return f"{category.id}:{subject}" if category.subject_scoped else category.id


def decision(context_id: str | None, category_id: str, subject: str = "") -> str:
    """"allow" or "ask"."""
    category = registry.get(category_id)
    if category is None or not context_id:
        return "ask"
    rule_subject = _rule_subject(category, subject)
    if category.subject_scoped and not rule_subject:
        return "ask"
    if category.rememberable and persistent_allowed() and store.has(category.id, rule_subject):
        _log.info("permission allowed by saved rule category=%s", category.id)
        return "allow"
    if "tab" in category.scopes and data_sources.is_allowed(context_id, grant_key(category, rule_subject)):
        return "allow"
    return "ask"


def covered_by_saved_rule(category_id: str, subject: str = "") -> bool:
    """True when a saved "Always allow" rule (not a tab grant) is what lets this call through."""
    category = registry.get(category_id)
    if category is None or not category.rememberable or not persistent_allowed():
        return False
    rule_subject = _rule_subject(category, subject)
    return bool(rule_subject or not category.subject_scoped) and store.has(category.id, rule_subject)


def card_options(category_id: str) -> dict | None:
    """Buttons a card for this category should offer, in display order, and which one leads."""
    category = registry.get(category_id)
    if category is None:
        return None
    scopes = [s for s in registry.SCOPES if s in category.scopes and (s != "always" or persistent_allowed())]
    primary = "always" if category.risk == "low" and "always" in scopes else next((s for s in ("tab", "once") if s in scopes), scopes[0])
    return {"scopes": scopes, "primary": primary}


def allow_for_tab(context_id: str, category_id: str, subject: str = "") -> None:
    category = registry.get(category_id)
    if category is None or "tab" not in category.scopes:
        raise ValueError("this permission cannot be allowed for a tab")
    data_sources.allow(context_id, grant_key(category, _rule_subject(category, subject)))


def remember(category_id: str, subject: str = "") -> dict:
    """Save an "Always allow" rule. Raises ValueError when the category cannot be remembered or policy forbids it."""
    category = registry.get(category_id)
    if category is None or not category.rememberable:
        raise ValueError("this permission cannot be remembered")
    if not persistent_allowed():
        raise ValueError("your administrator has turned off Always allow")
    rule_subject = _rule_subject(category, subject)
    if category.subject_scoped and not rule_subject:
        raise ValueError("this permission is remembered per item")
    return store.add(category.id, rule_subject)


def apply_scope(context_id: str, category_id: str, subject: str, scope: str | None, default: str = "tab") -> str:
    """Record what the user chose on a card and return the scope that took effect.

    A click that names no scope (an older page) gets `default`, what that card's Allow meant before scopes existed.

    "always" falls back to "tab" when the category, policy or store does not allow a saved rule.
    A category this module does not know gets no grant at all ("once"), so it asks again next time.
    """
    if registry.get(category_id) is None:
        return "once"
    scope = scope or default
    if scope == "once":
        return "once"
    if scope == "always":
        try:
            remember(category_id, subject)
            return "always"
        except (ValueError, RuntimeError):
            pass
    try:
        allow_for_tab(context_id, category_id, subject)
        return "tab"
    except ValueError:
        return "once"


def set_mode(category_id: str, mode: str) -> None:
    """Settings switch for a whole category: "always" saves its rule, "ask" removes it."""
    category = registry.get(category_id)
    if category is None or category.subject_scoped:
        raise ValueError("this permission has no category-wide setting")
    if mode == "always":
        remember(category_id)
    elif mode == "ask":
        store.remove_category(category.id)
    else:
        raise ValueError("mode must be ask or always")
