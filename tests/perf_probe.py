#!/usr/bin/env python3
"""Dev-only latency probe for AI Gator's hot endpoints.

Hits a set of read endpoints against an already-running local server, reports
cold (first call) vs warm (subsequent) p50/p95, and dumps the server's own
/api/perf phase breakdown. Use it to capture a baseline now and compare after
caching work lands.

This is NOT a pytest — it talks to a live server and is meant to be run by hand:

    # from the repo root, with the app running on :8000
    python tests/perf_probe.py
    python tests/perf_probe.py --runs 10 --base-url http://127.0.0.1:8000

It resets /api/perf at the start so the server-side aggregates reflect only this
run. Nothing is written to disk; all data is in-memory and printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

# (label, path). GET-only, read-only endpoints. The chat-messages probe needs a
# chat id, so it's resolved dynamically from the chat list below.
ENDPOINTS = [
    ("teams.chats", "/api/teams/chats?delta=false&top=50"),
    ("teams.chats_delta", "/api/teams/chats?delta=true&top=50"),
    ("email.inbox_full", "/api/email/inbox?top=50&delta=false"),
    ("email.inbox_delta", "/api/email/inbox?top=50&delta=true"),
]


def _get(base_url: str, path: str, timeout: float = 60.0):
    """Return (status, elapsed_ms, parsed_json_or_none)."""
    start = time.perf_counter()
    req = urllib.request.Request(base_url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ms = (time.perf_counter() - start) * 1000
            try:
                return resp.status, ms, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, ms, None
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - start) * 1000
        return e.code, ms, None
    except Exception as e:  # noqa: BLE001 — probe should never crash the run
        ms = (time.perf_counter() - start) * 1000
        print(f"    ! {path} failed: {e}", file=sys.stderr)
        return 0, ms, None


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def _server_up(base_url: str) -> bool:
    status, _, _ = _get(base_url, "/health", timeout=3)
    return status == 200


def _resolve_a_chat_id(base_url: str) -> str | None:
    status, _, data = _get(base_url, "/api/teams/chats?top=1")
    if status == 200 and data and data.get("chats"):
        return data["chats"][0].get("id")
    return None


def probe(base_url: str, runs: int) -> None:
    endpoints = list(ENDPOINTS)

    chat_id = _resolve_a_chat_id(base_url)
    if chat_id:
        import urllib.parse
        enc = urllib.parse.quote(chat_id, safe="")
        endpoints.append(("teams.messages", f"/api/teams/chats/{enc}/messages?top=30"))
    else:
        print("  (no Teams chat id resolved — skipping teams.messages probe)")

    # Clean server-side baseline for this run (reset is POST-only).
    try:
        urllib.request.urlopen(
            urllib.request.Request(base_url + "/api/perf/reset", method="POST"), timeout=5
        )
    except Exception:
        pass

    print(f"\n== AI Gator perf probe ==  base={base_url}  runs={runs}\n")
    print(f"{'endpoint':<24}{'cold ms':>10}{'warm p50':>10}{'warm p95':>10}{'warm max':>10}")
    print("-" * 64)

    for label, path in endpoints:
        cold_status, cold_ms, _ = _get(base_url, path)
        warm = []
        for _ in range(max(0, runs - 1)):
            _, ms, _ = _get(base_url, path)
            warm.append(ms)
        p50 = _pct(warm, 0.50)
        p95 = _pct(warm, 0.95)
        mx = round(max(warm), 1) if warm else 0.0
        flag = "" if cold_status == 200 else f"  [HTTP {cold_status}]"
        print(f"{label:<24}{cold_ms:>10.1f}{p50:>10.1f}{p95:>10.1f}{mx:>10.1f}{flag}")

    # Server-side phase breakdown.
    status, _, snap = _get(base_url, "/api/perf")
    if status == 200 and snap:
        print("\n-- server /api/perf (phase breakdown, sorted by p95) --")
        print(f"{'name':<34}{'count':>7}{'avg':>9}{'p50':>9}{'p95':>9}{'max':>9}{'slow':>6}")
        print("-" * 83)
        for row in snap.get("endpoints", []):
            print(f"{row['name']:<34}{row['count']:>7}{row['avg']:>9.1f}"
                  f"{row['p50']:>9.1f}{row['p95']:>9.1f}{row['max']:>9.1f}{row['slow']:>6}")
        if snap.get("recent_slow"):
            print(f"\n  {len(snap['recent_slow'])} recent slow (>{snap['slow_threshold_ms']:.0f}ms) sample(s)")
    else:
        print(f"\n  (/api/perf unavailable — HTTP {status}; is this a loopback client / DEV_MODE?)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Gator latency probe (dev-only).")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default {DEFAULT_BASE_URL}")
    ap.add_argument("--runs", type=int, default=6, help="total calls per endpoint (1 cold + N-1 warm)")
    args = ap.parse_args()

    if not _server_up(args.base_url):
        print(f"Server not reachable at {args.base_url} — start AI Gator first "
              f"(e.g. python web/watchdog.py).", file=sys.stderr)
        return 1

    probe(args.base_url, args.runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
