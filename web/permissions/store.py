"""Permissions the user chose to keep with "Always allow".

Stored in the encrypted credential store, whose folder the model's file tools are refused
(sandbox.paths.is_secrets_path), so a tricked model cannot grant itself a permission. An
unreadable, malformed or unknown-version blob means no rules. Rules are created only through
the CSRF-guarded routes and removed only from Settings.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

_NAME = "permissions/rules"
_VERSION = 1
_SUBJECT_MAX = 200
_LOCK = threading.Lock()
_log = logging.getLogger(__name__)


def _valid(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("category"), str)
            and bool(entry["category"]) and isinstance(entry.get("subject"), str)
            and isinstance(entry.get("created"), (int, float)) and not isinstance(entry["created"], bool))


def _load() -> list[dict] | None:
    """The valid rules; [] when nothing is stored; None when the store is unreadable or not ours."""
    try:
        import secure_store
        data = secure_store.get_json(_NAME)
    except Exception as exc:
        _log.warning("permission rules unreadable (%s); treating as none", type(exc).__name__)
        return None
    if data is None:
        return []
    if not isinstance(data, dict) or data.get("version") != _VERSION or not isinstance(data.get("rules"), list):
        return None
    return [r for r in data["rules"] if _valid(r)]


def _save(rules: list[dict]) -> None:
    import secure_store
    secure_store.set_json(_NAME, {"version": _VERSION, "rules": rules})


def list_rules() -> list[dict]:
    return _load() or []


def has(category: str, subject: str = "") -> bool:
    return any(r["category"] == category and r["subject"] == subject for r in list_rules())


def add(category: str, subject: str = "") -> dict:
    subject = subject.strip()[:_SUBJECT_MAX]
    with _LOCK:
        rules = _load()
        if rules is None:
            raise RuntimeError("permission rules are unreadable; not overwriting them")
        for existing in rules:
            if existing["category"] == category and existing["subject"] == subject:
                return existing
        rule = {"id": uuid.uuid4().hex, "category": category, "subject": subject, "created": time.time()}
        _save(rules + [rule])
    return rule


def remove(rule_id: str) -> bool:
    with _LOCK:
        rules = _load()
        if rules is None:
            return False
        kept = [r for r in rules if r["id"] != rule_id]
        if len(kept) == len(rules):
            return False
        _save(kept)
    return True


def remove_category(category: str) -> None:
    """Drop the whole-category rule (not a website's or other subject's)."""
    with _LOCK:
        rules = _load()
        if rules is None:
            return
        kept = [r for r in rules if not (r["category"] == category and r["subject"] == "")]
        if len(kept) != len(rules):
            _save(kept)


def remove_all() -> None:
    with _LOCK:
        _save([])
