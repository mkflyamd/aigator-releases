"""Validate model-supplied tool inputs against the schema the model was offered."""
from __future__ import annotations

import logging

from jsonschema import exceptions as _jx
from jsonschema.validators import validator_for

import shared

_log = logging.getLogger(__name__)
_CACHE: dict[str, tuple[dict, object | None]] = {}
_WARNED: set[str] = set()
_HINT = "Fix the argument named in 'field' so it matches the tool's schema, then call the tool again."


def _schema_for(tool_name: str) -> dict | None:
    for d in shared.TOOLS:
        if d.get("name") == tool_name:
            schema = d.get("input_schema")
            return schema if isinstance(schema, dict) else None
    return None


def _validator_for(tool_name: str, schema: dict):
    cached = _CACHE.get(tool_name)
    if cached is not None and cached[0] is schema:
        return cached[1]
    try:
        cls = validator_for(schema)
        cls.check_schema(schema)
        validator = cls(schema)
    except Exception as exc:
        if tool_name not in _WARNED:
            _WARNED.add(tool_name)
            _log.warning("tool_validation: schema for %s is unusable, validation skipped: %s", tool_name, exc)
        validator = None
    _CACHE[tool_name] = (schema, validator)
    return validator


def validate_tool_inputs(tool_name: str, inputs: dict) -> dict | None:
    schema = _schema_for(tool_name)
    if schema is None:
        return None
    validator = _validator_for(tool_name, schema)
    if validator is None:
        return None
    required = set(schema.get("required") or ())
    # A null for an optional field means "not given"; handlers already default it.
    checked = {k: v for k, v in (inputs or {}).items() if v is not None or k in required}
    try:
        error = _jx.best_match(validator.iter_errors(checked))
    except Exception:
        _log.exception("tool_validation: validating %s failed, skipped", tool_name)
        return None
    if error is None:
        return None
    return {
        "error": "invalid_tool_input",
        "tool": tool_name,
        "field": ".".join(str(p) for p in error.absolute_path),
        "reason": error.message[:300],
        "hint": _HINT,
    }
