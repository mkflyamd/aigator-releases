# Session State — `.gator-session.json`

Single small JSON file at `.gator-session.json` in the repo root (gitignored).
Holds the current fixing session so a later `/loop` check-in or re-invocation
resumes cleanly.

## Schema

```json
{
  "date": "2026-06-13",
  "batch_size": 5,
  "pause_between_batches": true,
  "selected": [
    {
      "number": 76,
      "subsystem": "code_runner",
      "labels": ["bug", "priority:high"],
      "status": "pending",
      "fix_commits": ["120f148"],
      "pr": "#NN or null",
      "test_hint": "python -m pytest tests/code_runner/test_x.py::test_y -v",
      "verified": false
    }
  ],
  "architecture_decisions": [
    {"number": 77, "question": "...", "decision": "..."}
  ],
  "already_fixed": [
    {"number": 80, "evidence": "test passes on main", "comment_drafted": true}
  ],
  "parked": [
    {"number": 58, "question": "add explicit body_html param?", "options": "add | skip (auto-detect covers it)", "lean": "skip", "safe_default_applied": "skipped speculative param; core already fixed"}
  ],
  "drafted_comments": [
    {"number": 80, "body": "Looks already fixed in web/routes/settings.py ..."}
  ]
}
```

## Field rules
- `status` ∈ `pending | fixed | skipped-already-fixed | non-actionable | blocked | closed`.
  - `non-actionable` — duplicate / question / wontfix / needs-info (Phase 3); record a `reason`.
  - `blocked` — selected but genuinely couldn't make ANY progress (Phase 6); record a `reason`. Prefer `parked` over `blocked` for HITL judgment calls.
- `parked` — HITL decisions (design/judgment calls or external side-effects) deferred so the session doesn't stall. Each: `number`, `question`, `options`, `lean`, `safe_default_applied`. Resolved as a batch in Phase 8.
- `fix_commits` / `pr` / `test_hint` / `verified` are filled in Phase 6–7:
  `fix_commits` after each commit, `test_hint` + `verified` during Phase 7
  verification, `pr` if a PR exists. `verified` must be `true` before a closure
  comment is drafted.
- `batch_size` default 5, set during Phase 2 negotiation; not a hard cap.
- `pause_between_batches` set during Phase 2.
- Write the file after Phase 2 (selection), update after Phase 3.5, Phase 4,
  after each issue in Phase 6, after verify/close in Phase 7, and finalize in Phase 8.

## Read/write rules
- Read with the Read tool; write with the Write tool (overwrite whole file).
- If the file is missing or `selected` is empty → treat as "no pending work" → fetch fresh.
- Never store secrets. Issue numbers and short strings only.
