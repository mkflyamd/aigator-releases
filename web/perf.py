"""Ephemeral, in-memory performance instrumentation for AI Gator.

This module records timing samples for backend hot paths so we can see where
request latency actually goes (which endpoint, and which phase inside it).

Design constraints (see plan "Gator Performance Measurement"):
  - IN-MEMORY ONLY. Nothing is written to disk; all data resets on restart.
  - Records timings + phase/endpoint NAMES only. Never message/email content.
    Callers must pass only non-content meta (counts, chat_type, phase flags).
  - Thread-safe: sync routes run in the threadpool and requests overlap, so a
    single lock guards the shared buffers.

Usage:
    import perf
    with perf.span("teams.list_chats", top=50):
        ...

    perf.record("GET /api/teams/chats", 812.4)

    perf.snapshot()   # -> aggregates + recent slow samples for /api/perf
"""

from __future__ import annotations

import threading
import time as _time
from collections import deque
from contextlib import contextmanager

# Requests slower than this (ms) are counted as "slow" and always retained in
# the recent-slow list. Matches the SLOW threshold in app.py's latency logger.
SLOW_MS = 2000.0

# How many raw samples to keep overall, and how many recent per-name durations
# to keep for percentile estimates. Both bounded so memory stays flat.
_MAX_SAMPLES = 2000
_MAX_RECENT_PER_NAME = 300
_MAX_SLOW = 100

_LOCK = threading.Lock()
# Most-recent raw samples across all names: {ts, name, ms, meta}
_samples: "deque[dict]" = deque(maxlen=_MAX_SAMPLES)
# Recent slow samples (ms > SLOW_MS), newest last.
_slow: "deque[dict]" = deque(maxlen=_MAX_SLOW)
# Per-name aggregates: name -> {count, sum, max, slow, recent(deque of ms)}
_agg: "dict[str, dict]" = {}

# Process start, so snapshot() can report an observation window.
_started_at = _time.time()


def _sanitize_meta(meta: dict) -> dict:
    """Keep only small scalar meta so we never accidentally retain content.

    Strings are length-capped; only str/int/float/bool/None survive. This is a
    safety net — callers should already pass non-content values.
    """
    clean: dict = {}
    for k, v in meta.items():
        if isinstance(v, bool) or v is None or isinstance(v, (int, float)):
            clean[k] = v
        elif isinstance(v, str):
            clean[k] = v[:80]
        # Silently drop anything else (dicts, lists, objects).
    return clean


def record(name: str, ms: float, **meta) -> None:
    """Record a single timing sample of `ms` milliseconds under `name`."""
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return
    clean_meta = _sanitize_meta(meta) if meta else {}
    sample = {"ts": _time.time(), "name": name, "ms": round(ms, 2), "meta": clean_meta}
    with _LOCK:
        _samples.append(sample)
        a = _agg.get(name)
        if a is None:
            a = {"count": 0, "sum": 0.0, "max": 0.0, "slow": 0,
                 "recent": deque(maxlen=_MAX_RECENT_PER_NAME)}
            _agg[name] = a
        a["count"] += 1
        a["sum"] += ms
        if ms > a["max"]:
            a["max"] = ms
        if ms > SLOW_MS:
            a["slow"] += 1
            _slow.append(sample)
        a["recent"].append(ms)


@contextmanager
def span(name: str, **meta):
    """Time a block and record it under `name`.

    Example:
        with perf.span("teams.resolve_chat_names", groups=len(chats)):
            _resolve_chat_names(chats)
    """
    start = _time.perf_counter()
    try:
        yield
    finally:
        record(name, (_time.perf_counter() - start) * 1000.0, **meta)


def _percentile(sorted_vals: list, pct: float) -> float:
    """Nearest-rank percentile from an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 2)


def snapshot(top: int = 40) -> dict:
    """Return a JSON-serializable view of current aggregates + recent slow samples.

    `endpoints` is sorted by p95 descending so the worst offenders surface first.
    Everything is derived from bounded in-memory buffers.
    """
    with _LOCK:
        rows = []
        for name, a in _agg.items():
            recent_sorted = sorted(a["recent"])
            count = a["count"]
            rows.append({
                "name": name,
                "count": count,
                "avg": round(a["sum"] / count, 2) if count else 0.0,
                "p50": _percentile(recent_sorted, 0.50),
                "p95": _percentile(recent_sorted, 0.95),
                "max": round(a["max"], 2),
                "slow": a["slow"],
            })
        slow_recent = [dict(s) for s in list(_slow)[-25:]][::-1]
        total_samples = len(_samples)
        window_s = round(_time.time() - _started_at, 1)

    rows.sort(key=lambda r: r["p95"], reverse=True)
    return {
        "window_seconds": window_s,
        "total_samples": total_samples,
        "slow_threshold_ms": SLOW_MS,
        "endpoints": rows[:top],
        "recent_slow": slow_recent,
    }


def reset() -> None:
    """Clear all recorded data. Used by the benchmark harness to get a clean run."""
    global _started_at
    with _LOCK:
        _samples.clear()
        _slow.clear()
        _agg.clear()
        _started_at = _time.time()
