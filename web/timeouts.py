"""One budget table for every step of a run: setup, run and teardown, each with its own reserved time.

Milliseconds throughout, so tests inject a few hundred instead of sleeping real seconds.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace

_FIELDS = ("setup_ms", "run_ms", "teardown_ms")


@dataclass(frozen=True)
class Budgets:
    setup_ms: int
    run_ms: int
    teardown_ms: int


_DEFAULTS = {
    "host": Budgets(setup_ms=0, run_ms=120_000, teardown_ms=5_000),
}
_overrides: dict[str, dict[str, int]] = {}


def budgets_for(path: str, run_ms: int | None = None) -> Budgets:
    """Budgets for a run path. A caller-supplied run time (the command's own timeout) applies unless a test overrode it."""
    base = _DEFAULTS[path]
    if run_ms is not None:
        base = replace(base, run_ms=int(run_ms))
    return replace(base, **_overrides.get(path, {}))


@contextmanager
def override(path: str, **ms: int):
    """Inject budgets for a path, in milliseconds, for the duration of the block."""
    unknown = set(ms) - set(_FIELDS)
    if unknown:
        raise ValueError(f"unknown budget field: {sorted(unknown)}")
    previous = _overrides.get(path)
    _overrides[path] = {**(previous or {}), **ms}
    try:
        yield
    finally:
        if previous is None:
            _overrides.pop(path, None)
        else:
            _overrides[path] = previous
